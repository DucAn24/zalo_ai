"""Build canonical, typed tables for one business from its raw files.

Canonical tables (all optional except what the data provides):
  orders, lines, products, unit_conv, customers, payments, imports, import_lines,
  stock, ledger, lots, lot_sales, prices, deliveries, debt_terms, expenses,
  returns, employees, suppliers, order_tables
plus `raw_<name>` tables (sanitized copies of every raw table).
"""
from __future__ import annotations

import collections
import datetime as dt
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd

from .loader import RawTable, load_business
from .mapping import TableMap, map_business
from .parse import is_blank, parse_bool, parse_date, parse_datetime, parse_number, parse_qty
from .readme import ReadmeInfo, parse_readme
from .schema import WALKIN_NAMES, match_payment, match_status
from .textnorm import col_norm, key_norm, nfc, remove_phone, strip_accents

log = logging.getLogger(__name__)


@dataclass
class CanonOptions:
    dedupe_lines: bool = True          # rulebook §8: identical rows of the same order counted once
    fill_group_blanks: bool = True     # rulebook §8: blank order cells in following rows = first row


@dataclass
class Business:
    biz_id: str
    tables: dict[str, pd.DataFrame] = field(default_factory=dict)
    raw: dict[str, pd.DataFrame] = field(default_factory=dict)
    maps: list[TableMap] = field(default_factory=list)
    readme: ReadmeInfo = field(default_factory=ReadmeInfo)
    notes: list[str] = field(default_factory=list)      # human-readable facts for the prompt
    raw_links: dict[str, dict[str, str]] = field(default_factory=dict)  # raw table -> {column: join role}
    raw_kinds: dict[str, str] = field(default_factory=dict)             # raw table -> detected kind
    flags: dict[str, Any] = field(default_factory=dict)  # capability flags


# ---------------------------------------------------------------- typed column helpers
def _col(tm: TableMap, role: str) -> Optional[pd.Series]:
    c = tm.roles.get(role)
    if c is None:
        return None
    return tm.raw.df[c]


def to_str(s: Optional[pd.Series], n: int) -> pd.Series:
    if s is None:
        return pd.Series([None] * n, dtype=object)
    def f(x):
        if is_blank(x):
            return None
        if isinstance(x, float) and x.is_integer():
            x = int(x)
        return nfc(str(x)).strip()
    return s.map(f).astype(object)


def to_num(s: Optional[pd.Series], n: int) -> pd.Series:
    if s is None:
        return pd.Series([np.nan] * n, dtype=float)
    return s.map(lambda x: parse_number(x)).astype(float)


def to_date(s: Optional[pd.Series], years: pd.Series, n: int) -> pd.Series:
    if s is None:
        return pd.Series([None] * n, dtype=object)
    out = [parse_date(x, None if pd.isna(y) else int(y)) for x, y in zip(s.tolist(), years.tolist())]
    return pd.Series(out, dtype=object)


def to_ts(s: Optional[pd.Series], years: pd.Series, n: int) -> pd.Series:
    if s is None:
        return pd.Series([None] * n, dtype=object)
    out = []
    for x, y in zip(s.tolist(), years.tolist()):
        if isinstance(x, dt.time):
            out.append(x)
            continue
        if isinstance(x, str) and re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", x.strip()):
            parts = [int(p) for p in x.strip().split(":")]
            out.append(dt.time(*parts))
            continue
        v = parse_datetime(x, None if pd.isna(y) else int(y))
        out.append(v)
    return pd.Series(out, dtype=object)


def _years(tm: TableMap) -> pd.Series:
    return tm.raw.df["_sheet_year"] if "_sheet_year" in tm.raw.df else pd.Series([None] * len(tm.raw.df))


def _date_col(series: pd.Series) -> pd.Series:
    return pd.to_datetime(pd.Series([v if isinstance(v, (dt.date, dt.datetime)) else None for v in series]),
                          errors="coerce").dt.normalize()


def _ts_col(series: pd.Series) -> pd.Series:
    vals = []
    for v in series:
        if isinstance(v, dt.datetime):
            vals.append(v)
        elif isinstance(v, dt.date):
            vals.append(dt.datetime.combine(v, dt.time()))
        else:
            vals.append(None)
    return pd.to_datetime(pd.Series(vals), errors="coerce")


def norm_status(x: Optional[str]) -> Optional[str]:
    if x is None:
        return None
    return match_status(strip_accents(str(x)).lower().strip())


def norm_payment(x: Optional[str]) -> Optional[str]:
    if x is None:
        return None
    return match_payment(strip_accents(str(x)).lower().strip())


def is_walkin_name(x: Optional[str]) -> bool:
    if x is None:
        return True
    k = key_norm(x)
    return k in WALKIN_NAMES or k.startswith("khach le") or k.startswith("khach vang lai")


def unit_key(u: Optional[str]) -> Optional[str]:
    if u is None:
        return None
    return key_norm(u)


# ---------------------------------------------------------------- builders per kind
def _frame(tm: TableMap, spec: dict[str, str]) -> pd.DataFrame:
    """spec: role -> type in {'str','num','date','ts','bool'}"""
    n = len(tm.raw.df)
    yrs = _years(tm)
    out = {}
    for role, typ in spec.items():
        s = _col(tm, role)
        if typ == "str":
            out[role] = to_str(s, n)
        elif typ == "num":
            out[role] = to_num(s, n)
        elif typ == "date":
            out[role] = to_date(s, yrs, n)
        elif typ == "ts":
            out[role] = to_ts(s, yrs, n)
        elif typ == "bool":
            out[role] = pd.Series([parse_bool(x) for x in s], dtype=object) if s is not None else pd.Series([None] * n, dtype=object)
    df = pd.DataFrame(out)
    df.index = tm.raw.df.index
    return df


LINE_SPEC = {"order_id": "str", "line_no": "num", "product_id": "str", "product_name": "str", "unit": "str",
             "qty": "str", "qty_base": "num", "unit_price": "num", "line_discount": "num", "line_amount": "num",
             "cost_unit": "num", "order_date": "date", "order_time": "ts", "status": "str",
             "customer_name": "str", "customer_id": "str", "note": "str"}
ORDER_SPEC = {"order_id": "str", "order_date": "date", "order_ts": "ts", "customer_id": "str", "customer_name": "str",
              "goods_amount": "num", "order_discount": "num", "shipping_fee": "num", "vat": "num",
              "total_payable": "num", "paid_amount": "num", "debt_amount": "num", "payment_method": "str",
              "status": "str", "channel": "str", "employee_id": "str", "note": "str", "shift_id": "str",
              "promo_code": "str", "branch_id": "str"}
ORDER_LEVEL_IN_LINES = ["order_date", "status", "customer_name", "customer_id", "note"]


def build_lines(tm: TableMap, opts: CanonOptions) -> pd.DataFrame:
    raw = tm.raw.df
    df = _frame(tm, LINE_SPEC)
    has_id = tm.roles.get("order_id") is not None
    present = [c for c in ORDER_LEVEL_IN_LINES if tm.roles.get(c)]
    if has_id and opts.fill_group_blanks:
        blank_id = df["order_id"].isna()
        if blank_id.any():
            for c in ["order_id"] + present:
                df.loc[:, c] = df[c].where(~blank_id, None).ffill() if c == "order_id" else df[c]
            # order-level cells blank in follow-up rows -> forward fill within the group of blank-id rows
            grp = (~blank_id).cumsum()
            for c in present:
                df[c] = df.groupby(grp)[c].ffill()
        for c in present:
            first = df.groupby("order_id")[c].transform("first")
            df[c] = df[c].where(df[c].notna(), first)
    # quantities
    qv, qu = zip(*[parse_qty(x) for x in df["qty"].tolist()]) if len(df) else ((), ())
    df["qty"] = pd.Series(qv, index=df.index, dtype=float)
    unit_from_qty = pd.Series(qu, index=df.index, dtype=object)
    df["unit"] = df["unit"].where(df["unit"].notna(), unit_from_qty)
    if has_id and opts.dedupe_lines:
        before = len(df)
        raw_cols = [c for c in raw.columns if not c.startswith("_sheet_")]
        key = raw[raw_cols].astype(str).copy()
        key["__oid"] = df["order_id"].astype(str)
        for c in present:
            key["__" + c] = df[c].astype(str)
        dup = key.duplicated()
        df = df[~dup.values]
        if before - len(df):
            log.info("%s: dropped %d duplicate line rows", tm.raw.name, before - len(df))
    df["status_raw"] = df["status"]
    df["status"] = df["status"].map(norm_status)
    df["src"] = tm.raw.name
    return df.reset_index(drop=True)


def build_orders(tm: TableMap) -> pd.DataFrame:
    df = _frame(tm, ORDER_SPEC)
    df = df[df["order_id"].notna()].drop_duplicates("order_id", keep="first")
    df["status_raw"] = df["status"]
    df["status"] = df["status"].map(norm_status)
    df["payment_method_raw"] = df["payment_method"]
    df["payment_method"] = df["payment_method"].map(norm_payment)
    return df.reset_index(drop=True)


SIMPLE_SPECS: dict[str, dict[str, str]] = {
    "products": {"product_id": "str", "product_name": "str", "group_name": "str", "base_unit": "str",
                 "price": "num", "cost": "num"},
    "conv": {"product_id": "str", "product_name": "str", "unit": "str", "factor": "num", "base_unit": "str",
             "unit_price": "num"},
    "customers": {"customer_id": "str", "customer_name": "str", "phone": "str", "customer_group": "str",
                  "address": "str", "gender": "str", "birthday": "date"},
    "payments": {"payment_id": "str", "order_id": "str", "pay_ts": "ts", "pay_method": "str", "pay_amount": "num",
                 "note": "str"},
    "imports": {"import_id": "str", "import_date": "date", "supplier_id": "str", "supplier_name": "str",
                "import_total": "num", "import_status": "str", "note": "str"},
    "import_lines": {"import_id": "str", "line_no": "num", "product_id": "str", "product_name": "str", "unit": "str",
                     "qty": "num", "qty_base": "num", "unit_cost": "num", "line_amount": "num", "lot": "str",
                     "expiry": "date", "supplier_name": "str", "supplier_id": "str", "import_date": "date",
                     "note": "str"},
    "stock": {"product_id": "str", "product_name": "str", "base_unit": "str", "stock_qty": "num"},
    "lots": {"import_id": "str", "product_id": "str", "lot": "str", "expiry": "date", "qty_base": "num",
             "unit_cost_base": "num"},
    "lot_sales": {"order_id": "str", "line_no": "num", "lot": "str", "qty_base": "num", "return_qty_base": "num"},
    "prices": {"product_id": "str", "product_name": "str", "effective_date": "date", "new_price": "num",
               "old_price": "num"},
    "deliveries": {"delivery_date": "date", "order_id": "str", "delivery_no": "num", "product_name": "str",
                   "base_unit": "str", "qty_base": "num", "plate": "str", "driver": "str"},
    "debt_terms": {"order_id": "str", "credit_days": "num", "due_date": "date"},
    "expenses": {"expense_date": "date", "category": "str", "amount": "num", "note": "str"},
    "drugs": {"product_id": "str", "active_ingredient": "str", "is_rx": "bool"},
    "returns": {"return_id": "str", "order_id": "str", "return_ts": "ts", "reason": "str", "refund_amount": "num",
                "refund_method": "str"},
    "ledger": {"txn_id": "str", "product_id": "str", "ts": "ts", "txn_type": "str", "qty_base": "num",
               "doc_type": "str", "doc_id": "str", "balance": "num"},
    "employees": {"employee_id": "str", "employee_name": "str", "role": "str", "start_date": "date",
                  "end_date": "date"},
    "suppliers": {"supplier_id": "str", "supplier_name": "str", "phone": "str", "address": "str"},
    "tables": {"order_id": "str", "table_name": "str", "area": "str", "guests": "num"},
}


def _concat(frames: list[pd.DataFrame]) -> Optional[pd.DataFrame]:
    frames = [f for f in frames if f is not None and len(f)]
    if not frames:
        return None
    return pd.concat(frames, ignore_index=True)


def sanitize_name(s: str) -> str:
    s = col_norm(s).replace(" ", "_")
    return s or "col"


# ---------------------------------------------------------------- main assembly
class _ProductIndex:
    """Resolve product names / ids (with spelling variants) to a canonical product."""

    def __init__(self, products: Optional[pd.DataFrame]):
        self.by_id: dict[str, dict] = {}
        self.by_key: dict[str, str] = {}   # key_norm(name) -> product_id or name
        self.names: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
        self.has_ids = products is not None and products["product_id"].notna().any()
        if products is not None:
            for r in products.to_dict("records"):
                pid = r.get("product_id")
                nm = r.get("product_name")
                if pid:
                    self.by_id[pid] = r
                if nm:
                    self.by_key.setdefault(key_norm(nm), pid or nm)

    def resolve(self, pid: Optional[str], name: Optional[str]) -> Optional[str]:
        if pid:
            return pid
        if name:
            return self.by_key.get(key_norm(name))
        return None


def _mode(values) -> Optional[str]:
    c = collections.Counter(v for v in values if v)
    if not c:
        return None
    # prefer spellings with diacritics / mixed case: most common first, tie -> longest unicode
    return sorted(c.items(), key=lambda kv: (-kv[1], -sum(1 for ch in kv[0] if ord(ch) > 127), kv[0]))[0][0]


def build_business(biz_dir: str, opts: Optional[CanonOptions] = None) -> Business:
    opts = opts or CanonOptions()
    raws, readme_text = load_business(biz_dir)
    if os.environ.get("DATAMATE_IGNORE_README") == "1":   # robustness evaluation: pretend README is missing
        readme_text = ""
    info = parse_readme(readme_text)
    biz = Business(biz_id=re.sub(r"[\\/]+$", "", biz_dir).replace("\\", "/").split("/")[-1], readme=info)
    maps = map_business(raws, info)
    biz.maps = maps
    for tm in maps:
        df = tm.raw.df.drop(columns=[c for c in tm.raw.df.columns if c.startswith("_sheet_")])
        df = df.copy()
        df.columns = [sanitize_name(c) for c in df.columns]
        df = df.loc[:, ~pd.Index(df.columns).duplicated()]
        rname = "raw_" + sanitize_name(tm.raw.name)
        biz.raw_kinds[rname] = tm.kind
        if tm.link_roles:
            biz.raw_links[rname] = {sanitize_name(c): r for r, c in tm.link_roles.items()}
        biz.raw[rname] = df.map(lambda x: None if is_blank(x) else (str(x) if not isinstance(x, (int, float)) else x))
    by_kind: dict[str, list[TableMap]] = collections.defaultdict(list)
    for tm in maps:
        by_kind[tm.kind].append(tm)
        for m in tm.raw.meta_lines:
            biz.notes.append(f"{tm.raw.label}: dòng tiêu đề '{m}'")

    # ---- simple kinds
    simple: dict[str, Optional[pd.DataFrame]] = {}
    for kind, spec in SIMPLE_SPECS.items():
        simple[kind] = _concat([_frame(tm, spec) for tm in by_kind.get(kind, [])])

    # ---- products: catalog + drugs + stock + conv info
    products = simple["products"]
    drugs = simple["drugs"]
    if drugs is not None:
        if products is None:
            products = drugs[["product_id"]].copy()
        products = products.merge(drugs.drop_duplicates("product_id"), on="product_id", how="left")
    pidx = _ProductIndex(products)

    # ---- unit conversions
    conv_rows = []
    if simple["conv"] is not None:
        conv_rows.append(simple["conv"])
    if info.conversions:
        conv_rows.append(pd.DataFrame(info.conversions))
    conv = _concat(conv_rows)

    # ---- lines + orders
    lines = _concat([build_lines(tm, opts) for tm in by_kind.get("lines", [])])
    orders_hdr = _concat([build_orders(tm) for tm in by_kind.get("orders", [])])
    flags = biz.flags
    flags["has_lines"] = lines is not None
    flags["has_order_header"] = orders_hdr is not None
    flags["has_order_id"] = bool((lines is not None and lines["order_id"].notna().any()) or orders_hdr is not None)

    if lines is not None:
        if orders_hdr is not None:
            hdr = orders_hdr.set_index("order_id")
            for c in ["order_date", "customer_name", "customer_id", "status"]:
                m = lines["order_id"].map(hdr[c]) if c in hdr else None
                if m is not None:
                    lines[c] = lines[c].where(lines[c].notna(), m) if c != "status" else m.where(m.notna(), lines[c])
        # product resolution
        lines["product_name_raw"] = lines["product_name"]
        if pidx.has_ids:
            pid = [pidx.resolve(p, n) for p, n in zip(lines["product_id"], lines["product_name"])]
            lines["product_id"] = pid
            names = {k: v.get("product_name") for k, v in pidx.by_id.items()}
            lines["product_name"] = [names.get(p) or n for p, n in zip(lines["product_id"], lines["product_name"])]
        else:
            keys = lines["product_name"].map(lambda x: key_norm(x) if x else None)
            cat_names = {}
            if products is not None:
                for nm in products["product_name"].dropna():
                    cat_names[key_norm(nm)] = nm
            canon = {}
            for k, grp in lines.groupby(keys)["product_name"]:
                canon[k] = cat_names.get(k) or _mode(grp.tolist())
            lines["product_name"] = keys.map(canon)
        # base qty
        lines = _fill_qty_base(lines, conv, products, pidx)
        lines["is_return_line"] = (lines["qty"] < 0) | (lines["line_amount"] < 0)
        lines["order_date"] = _date_col(lines["order_date"])
        lines["order_time"] = lines["order_time"].map(lambda v: v if isinstance(v, (dt.datetime, dt.time)) else None)

    orders = _assemble_orders(lines, orders_hdr, simple, flags)
    if lines is not None and orders is not None and "order_id" in orders:
        lines = lines.merge(orders[["order_id", "order_date"]].rename(columns={"order_date": "_od"}), on="order_id", how="left")
        lines["order_date"] = lines["_od"].where(lines["_od"].notna(), lines["order_date"])
        lines = lines.drop(columns=["_od"])

    # ---- customers (names cleaned) + customer keys on orders
    customers = simple["customers"]
    if customers is not None:
        customers = customers.drop_duplicates("customer_id") if customers["customer_id"].notna().any() else customers
        customers["customer_name_clean"] = customers["customer_name"].map(lambda x: remove_phone(x) if x else None)
    if orders is not None:
        orders = _customer_keys(orders, customers, flags)

    # ---- products final table
    if products is None and lines is not None:
        products = pd.DataFrame({"product_name": sorted(set(lines["product_name"].dropna()))})
        products["product_id"] = None
    if products is not None:
        products = _enrich_products(products, conv, simple["stock"], lines, pidx)
    unit_conv = _build_unit_conv(conv, products, pidx, lines)

    # ---- imports
    imports, import_lines = _build_imports(simple["imports"], simple["import_lines"], unit_conv, pidx, products)
    # ---- lots
    lots = _build_lots(simple["lots"], import_lines, imports)
    # ---- payments
    payments = simple["payments"]
    if payments is not None:
        payments["pay_ts"] = _ts_col(payments["pay_ts"])
        payments["pay_date"] = payments["pay_ts"].dt.normalize()
        payments["pay_method_raw"] = payments["pay_method"]
        payments["pay_method"] = payments["pay_method"].map(norm_payment)
    # ---- stock / ledger / prices / deliveries / others
    stock = simple["stock"]
    if stock is not None:
        if pidx.has_ids:
            stock["product_id"] = [pidx.resolve(p, n) for p, n in zip(stock["product_id"], stock["product_name"])]
            names = {k: v.get("product_name") for k, v in pidx.by_id.items()}
            stock["product_name"] = [names.get(p) or n for p, n in zip(stock["product_id"], stock["product_name"])]
        stock["as_of"] = pd.Timestamp(info.data_end) if info.data_end else None
    prices = simple["prices"]
    if prices is not None:
        if pidx.has_ids:
            prices["product_id"] = [pidx.resolve(p, n) for p, n in zip(prices["product_id"], prices["product_name"])]
        prices["effective_date"] = _date_col(prices["effective_date"])
        if pidx.has_ids:
            names = {k: v.get("product_name") for k, v in pidx.by_id.items()}
            prices["product_name"] = [names.get(p) or n for p, n in zip(prices["product_id"], prices["product_name"])]
    for k, col in [("deliveries", "delivery_date"), ("expenses", "expense_date"), ("debt_terms", "due_date")]:
        if simple[k] is not None:
            simple[k][col] = _date_col(simple[k][col])
    if simple["ledger"] is not None:
        simple["ledger"]["ts"] = _ts_col(simple["ledger"]["ts"])
    if simple["returns"] is not None:
        simple["returns"]["return_ts"] = _ts_col(simple["returns"]["return_ts"])
    lot_sales = simple["lot_sales"]

    # ---- has_return / status on orders using all signals
    if orders is not None:
        orders = _return_flags(orders, lines, lot_sales, simple["returns"])

    out = {
        "orders": orders, "lines": lines, "products": products, "unit_conv": unit_conv, "customers": customers,
        "payments": payments, "imports": imports, "import_lines": import_lines, "stock": stock,
        "ledger": simple["ledger"], "lots": lots, "lot_sales": lot_sales, "prices": prices,
        "deliveries": simple["deliveries"], "debt_terms": simple["debt_terms"], "expenses": simple["expenses"],
        "returns": simple["returns"], "employees": simple["employees"], "suppliers": simple["suppliers"],
        "order_tables": simple["tables"],
    }
    biz.tables = {k: v for k, v in out.items() if v is not None and len(v)}
    _finalize_flags(biz)
    return biz


def _fill_qty_base(lines, conv, products, pidx):
    fac: dict[tuple, float] = {}
    base_of: dict[str, str] = {}
    if conv is not None:
        for r in conv.to_dict("records"):
            pk = r.get("product_id") or (pidx.resolve(None, r.get("product_name")) if r.get("product_name") else None) \
                 or (key_norm(r["product_name"]) if r.get("product_name") else None)
            if pk is None or not r.get("unit") or not r.get("factor"):
                continue
            fac[(pk, unit_key(r["unit"]))] = float(r["factor"])
            if r.get("base_unit"):
                base_of[pk] = r["base_unit"]
    if products is not None and "base_unit" in products:
        for r in products.to_dict("records"):
            pk = r.get("product_id") or (key_norm(r["product_name"]) if r.get("product_name") else None)
            if pk and r.get("base_unit"):
                base_of.setdefault(pk, r["base_unit"])
    pkeys = [p if p else (pidx.resolve(None, n) or (key_norm(n) if n else None))
             for p, n in zip(lines["product_id"], lines["product_name"])]
    factors, filled = [], []
    for pk, u, q, qb in zip(pkeys, lines["unit"], lines["qty"], lines["qty_base"]):
        f = fac.get((pk, unit_key(u))) if u else None
        if f is None:
            f = 1.0
        factors.append(f)
        if pd.isna(qb) and not pd.isna(q):
            filled.append(q * f)
        else:
            filled.append(qb)
    lines["factor"] = factors
    lines["qty_base"] = pd.Series(filled, index=lines.index, dtype=float)
    lines["base_unit"] = [base_of.get(pk) for pk in pkeys]
    # infer base unit from rows where qty == qty_base
    miss = lines["base_unit"].isna()
    if miss.any():
        same = lines[(lines["qty"] == lines["qty_base"]) & lines["unit"].notna()]
        guess = same.groupby(lines.loc[same.index, "product_name"])["unit"].agg(lambda s: s.mode().iloc[0])
        lines.loc[miss, "base_unit"] = lines.loc[miss, "product_name"].map(guess)
    return lines


def _assemble_orders(lines, hdr, simple, flags) -> Optional[pd.DataFrame]:
    if lines is None and hdr is None:
        return None
    agg = None
    if lines is not None and lines["order_id"].notna().any():
        L = lines[lines["order_id"].notna()].copy()
        L["_pos_amt"] = L["line_amount"].where(L["line_amount"] > 0, 0)
        L["_ret"] = (L["qty"] < 0) | (L["line_amount"] < 0)
        nonret = L[~L["_ret"]]
        g = L.groupby("order_id", sort=False)
        agg = pd.DataFrame({
            "items_amount": g["_pos_amt"].sum(),
            "net_line_amount": g["line_amount"].sum(),
            "n_lines": g.size(),
            "has_return_line": g["_ret"].any(),
            "cost_amount": (L["cost_unit"] * L["qty"]).groupby(L["order_id"]).sum(min_count=1),
        })
        gd = nonret.groupby("order_id")
        agg["order_date_l"] = gd["order_date"].min()
        agg["order_date_l"] = agg["order_date_l"].where(agg["order_date_l"].notna(), g["order_date"].min())
        agg["order_time_l"] = gd["order_time"].first()
        pr = L["status"].map(_STATUS_PRIO)
        agg["status_l"] = pr.groupby(L["order_id"]).min().map(_PRIO_STATUS)
        agg["status_raw_l"] = g["status_raw"].first()
        agg["customer_name_l"] = g["customer_name"].first()
        agg["customer_id_l"] = g["customer_id"].first()
        agg = agg.reset_index()
    if hdr is None and agg is None:
        return None  # sales book without order ids: every line is its own record
    if hdr is None:
        o = agg.rename(columns={"order_date_l": "order_date", "status_l": "status", "status_raw_l": "status_raw",
                                "customer_name_l": "customer_name", "customer_id_l": "customer_id",
                                "order_time_l": "order_ts"})
        for c in ["goods_amount", "order_discount", "shipping_fee", "vat", "total_payable", "paid_amount",
                  "debt_amount", "payment_method", "payment_method_raw", "channel", "employee_id", "note",
                  "shift_id", "promo_code", "branch_id"]:
            o[c] = None
        o["goods_amount"] = o["items_amount"]
    else:
        o = hdr.copy()
        if agg is not None:
            o = o.merge(agg, on="order_id", how="left")
            o["order_date"] = o["order_date"].where(o["order_date"].notna(), o["order_date_l"])
            o["customer_name"] = o["customer_name"].where(o["customer_name"].notna(), o["customer_name_l"])
            o["customer_id"] = o["customer_id"].where(o["customer_id"].notna(), o["customer_id_l"])
            o["status"] = o["status"].where(o["status"].notna(), o["status_l"])
            if o["order_ts"].isna().all():
                o["order_ts"] = o["order_time_l"]
            o = o.drop(columns=[c for c in o.columns if c.endswith("_l")])
        else:
            o["items_amount"] = o["goods_amount"]
            o["net_line_amount"] = None
            o["n_lines"] = None
            o["has_return_line"] = False
            o["cost_amount"] = None
    o["order_date"] = _date_col(o["order_date"])
    # combine date + time-of-day
    ts = []
    for d, t in zip(o["order_date"], o["order_ts"]):
        if isinstance(t, dt.datetime):
            ts.append(t)
        elif isinstance(t, dt.time) and not pd.isna(d):
            ts.append(dt.datetime.combine(d.date(), t))
        else:
            ts.append(None)
    o["order_ts"] = pd.to_datetime(pd.Series(ts), errors="coerce")
    return o


_STATUS_PRIO = {"huy": 0, "tra_hang": 1, "dang_giao": 2, "hoan_thanh": 3}
_PRIO_STATUS = {v: k for k, v in _STATUS_PRIO.items()}


def _order_status(vals: list) -> Optional[str]:
    s = set(v for v in vals if v)
    for k in ("huy", "tra_hang", "dang_giao", "hoan_thanh"):
        if k in s:
            return k
    return None


def _customer_keys(orders, customers, flags):
    has_ids = orders["customer_id"].notna().any()
    flags["has_customer_id"] = bool(has_ids)
    flags["has_customer_name"] = bool(orders["customer_name"].notna().any())
    cname = {}
    if customers is not None and customers["customer_id"].notna().any():
        cname = dict(zip(customers["customer_id"], customers["customer_name_clean"]))
    if has_ids:
        orders["is_walkin"] = orders["customer_id"].isna()
        orders["customer_key"] = orders["customer_id"]
        disp = [cname.get(i) or (remove_phone(n) if n else None) for i, n in zip(orders["customer_id"], orders["customer_name"])]
        orders["customer_display"] = [d if not w else None for d, w in zip(disp, orders["is_walkin"])]
    else:
        orders["is_walkin"] = orders["customer_name"].map(is_walkin_name)
        keys = [None if w else key_norm(remove_phone(n)) for n, w in zip(orders["customer_name"], orders["is_walkin"])]
        orders["customer_key"] = keys
        disp = {}
        tmp = pd.DataFrame({"k": keys, "n": [remove_phone(n) if n else None for n in orders["customer_name"]]})
        for k, g in tmp.dropna().groupby("k")["n"]:
            disp[k] = _mode(g.tolist())
        orders["customer_display"] = [disp.get(k) if k else None for k in keys]
    if customers is not None and "customer_group" in customers and has_ids:
        grp = dict(zip(customers["customer_id"], customers["customer_group"]))
        orders["customer_group"] = orders["customer_id"].map(grp)
    else:
        orders["customer_group"] = None
    return orders


def _enrich_products(products, conv, stock, lines, pidx):
    products = products.copy()
    if "product_id" not in products:
        products["product_id"] = None
    if "base_unit" not in products:
        products["base_unit"] = None
    if lines is not None and products["base_unit"].isna().any():
        bu = lines.groupby("product_name")["base_unit"].agg(lambda s: s.dropna().iloc[0] if s.notna().any() else None)
        products["base_unit"] = products["base_unit"].where(products["base_unit"].notna(), products["product_name"].map(bu))
    if stock is not None and products["base_unit"].isna().any():
        if stock["product_id"].notna().any() and products["product_id"].notna().any():
            m = dict(zip(stock["product_id"], stock["base_unit"]))
            products["base_unit"] = products["base_unit"].where(products["base_unit"].notna(), products["product_id"].map(m))
        else:
            m = {key_norm(n): u for n, u in zip(stock["product_name"], stock["base_unit"]) if n}
            products["base_unit"] = products["base_unit"].where(products["base_unit"].notna(),
                                                                products["product_name"].map(lambda n: m.get(key_norm(n)) if n else None))
    for c in ["group_name", "price", "cost", "active_ingredient", "is_rx"]:
        if c not in products:
            products[c] = None
    # all spellings seen in data, for entity linking
    aliases = collections.defaultdict(set)
    if lines is not None:
        for pid, pn, raw in zip(lines["product_id"], lines["product_name"], lines["product_name_raw"]):
            if raw:
                aliases[pid or pn].add(raw)
    products["aliases"] = [" | ".join(sorted(aliases.get(p or n, set()) - {n})) or None
                           for p, n in zip(products["product_id"], products["product_name"])]
    return products


def _build_unit_conv(conv, products, pidx, lines):
    rows = []
    if conv is not None:
        for r in conv.to_dict("records"):
            pid = r.get("product_id")
            nm = r.get("product_name")
            if pid is None and nm is not None and pidx.has_ids:
                pid = pidx.resolve(None, nm)
            if nm is None and pid is not None and pid in pidx.by_id:
                nm = pidx.by_id[pid].get("product_name")
            rows.append({"product_id": pid, "product_name": nm, "unit": r.get("unit"), "factor": r.get("factor"),
                         "base_unit": r.get("base_unit")})
    if not rows:
        return None
    uc = pd.DataFrame(rows)
    if products is not None and uc["base_unit"].isna().any():
        if products["product_id"].notna().any():
            m = dict(zip(products["product_id"], products["base_unit"]))
            uc["base_unit"] = uc["base_unit"].where(uc["base_unit"].notna(), uc["product_id"].map(m))
    uc = uc.drop_duplicates(subset=["product_id", "product_name", "unit"])
    return uc


def _build_imports(hdr, lines, unit_conv, pidx, products):
    if hdr is None and lines is None:
        return None, None
    if lines is not None:
        if pidx.has_ids:
            lines["product_id"] = [pidx.resolve(p, n) for p, n in zip(lines["product_id"], lines["product_name"])]
            names = {k: v.get("product_name") for k, v in pidx.by_id.items()}
            lines["product_name"] = [names.get(p) or n for p, n in zip(lines["product_id"], lines["product_name"])]
        fac = {}
        if unit_conv is not None:
            for r in unit_conv.to_dict("records"):
                pk = r.get("product_id") or (key_norm(r["product_name"]) if r.get("product_name") else None)
                if pk and r.get("unit"):
                    fac[(pk, unit_key(r["unit"]))] = r["factor"]
        f, qb = [], []
        for pid, pn, u, q, b in zip(lines["product_id"], lines["product_name"], lines["unit"], lines["qty"], lines["qty_base"]):
            pk = pid or (key_norm(pn) if pn else None)
            ff = fac.get((pk, unit_key(u)), 1.0) if u else 1.0
            f.append(ff)
            qb.append(q * ff if pd.isna(b) and not pd.isna(q) else b)
        lines["factor"] = f
        lines["qty_base"] = qb
        if lines["qty"].isna().all():
            lines["qty"] = lines["qty_base"]
        amt = lines["line_amount"]
        calc = lines["qty"] * lines["unit_cost"]
        lines["line_amount"] = amt.where(amt.notna(), calc)
        lines["import_date"] = _date_col(lines["import_date"])
        lines["expiry"] = _date_col(lines["expiry"])
    if hdr is None:
        g = lines.groupby("import_id", sort=False)
        hdr = pd.DataFrame({
            "import_date": g["import_date"].min(),
            "supplier_name": g["supplier_name"].first(),
            "supplier_id": g["supplier_id"].first(),
            "import_total": g["line_amount"].sum(min_count=1),
            "note": g["note"].first(),
        }).reset_index()
        hdr["import_status"] = None
    else:
        hdr = hdr.drop_duplicates("import_id")
        hdr["import_date"] = _date_col(hdr["import_date"])
        if lines is not None:
            tot = lines.groupby("import_id")["line_amount"].sum(min_count=1)
            hdr["lines_total"] = hdr["import_id"].map(tot)
            hdr["import_total"] = hdr["import_total"].where(hdr["import_total"].notna(), hdr["lines_total"])
            lines["import_date"] = lines["import_date"].where(lines["import_date"].notna(), lines["import_id"].map(hdr.set_index("import_id")["import_date"]))
    hdr["is_cancelled"] = hdr["import_status"].map(lambda s: bool(s) and norm_status(s) == "huy")
    return hdr, lines


def _build_lots(lots, import_lines, imports):
    frames = []
    if lots is not None:
        lots = lots.copy()
        lots["expiry"] = _date_col(lots["expiry"])
        frames.append(lots)
    if import_lines is not None and "lot" in import_lines and import_lines["lot"].notna().any():
        il = import_lines[import_lines["lot"].notna()]
        x = pd.DataFrame({"import_id": il["import_id"], "product_id": il["product_id"], "product_name": il["product_name"],
                          "lot": il["lot"], "expiry": il["expiry"], "qty_base": il["qty_base"],
                          "unit_cost_base": il["unit_cost"] / il["factor"].replace(0, np.nan)})
        frames.append(x)
    if not frames:
        return None
    df = pd.concat(frames, ignore_index=True)
    agg = df.groupby("lot", sort=False).agg(lambda s: s.dropna().iloc[0] if s.notna().any() else None).reset_index()
    if imports is not None:
        agg["import_date"] = agg["import_id"].map(imports.set_index("import_id")["import_date"])
    return agg


def _return_flags(orders, lines, lot_sales, returns):
    hr = orders["has_return_line"].fillna(False).astype(bool) if "has_return_line" in orders else pd.Series(False, index=orders.index)
    hr = hr | (orders["status"] == "tra_hang")
    if lot_sales is not None:
        ret = set(lot_sales.loc[lot_sales["return_qty_base"].fillna(0) > 0, "order_id"].dropna())
        hr = hr | orders["order_id"].isin(ret)
    if returns is not None:
        hr = hr | orders["order_id"].isin(set(returns["order_id"].dropna()))
    orders["has_return"] = hr
    return orders


def _finalize_flags(biz: Business):
    t, f = biz.tables, biz.flags
    o = t.get("orders")
    L = t.get("lines")
    dates = []
    if o is not None:
        dates += [o["order_date"].min(), o["order_date"].max()]
    if L is not None:
        dates += [L["order_date"].min(), L["order_date"].max()]
    dates = [d for d in dates if not pd.isna(d)]
    f["data_start"] = min(dates).date() if dates else None
    f["data_end"] = biz.readme.data_end or (max(dates).date() if dates else None)
    if o is not None:
        f["status_values"] = sorted(set(o["status"].dropna()))
        f["status_raw_values"] = sorted(set(o["status_raw"].dropna()))[:30] if "status_raw" in o else []
        f["has_payment_method"] = bool(o["payment_method"].notna().any())
        f["has_channel"] = bool(o["channel"].notna().any())
        f["channel_values"] = sorted(set(o["channel"].dropna()))[:20]
        f["has_employee"] = bool(o["employee_id"].notna().any())
        f["has_debt"] = bool(o["debt_amount"].notna().any() or t.get("payments") is not None)
        f["has_order_time"] = bool(o["order_ts"].notna().any() and (o["order_ts"].dt.hour > 0).any())
        f["has_customer_group"] = bool(o.get("customer_group") is not None and o["customer_group"].notna().any())
    for name in ["imports", "stock", "ledger", "lots", "prices", "deliveries", "debt_terms", "expenses", "returns",
                 "payments", "employees", "order_tables"]:
        f["has_" + name] = name in t
    p = t.get("products")
    f["has_catalog_cost"] = bool(p is not None and p["cost"].notna().any())
    f["has_line_cost"] = bool(L is not None and L["cost_unit"].notna().any())
    f["has_drug_info"] = bool(p is not None and p["active_ingredient"].notna().any())
    f["has_product_group"] = bool(p is not None and p["group_name"].notna().any())
    f["export_filters"] = [n for n in biz.notes if "lọc" in n.lower() or "trạng thái" in n.lower() or "đã duyệt" in n.lower()]
