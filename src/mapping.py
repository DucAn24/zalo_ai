"""Classify raw tables into canonical kinds and map raw columns to roles."""
from __future__ import annotations

import collections
import re
from dataclasses import dataclass, field

from .loader import RawTable, logical_name
from .parse import is_blank, parse_datetime, parse_number, parse_qty
from .readme import ReadmeInfo
from .schema import DESC_ROLE_ALIASES, DESC_ROLES, ID_PREFIX_ROLE, KIND_NAME_KEYWORDS, ROLE_NAMES
from .textnorm import col_norm, fix_mojibake

_CODE_RE = re.compile(r"^([A-Z]{1,5})\d{2,}$")
_CODELIKE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\-_./]*$")
_NAME_ROLES = {"product_name", "customer_name", "employee_name", "supplier_name", "group_name", "customer_group"}


@dataclass
class ColProfile:
    name: str
    n: int
    n_blank: int
    n_distinct: int
    frac_num: float
    frac_date: float
    prefix: str | None
    samples: list
    frac_qty: float = 0.0
    frac_code: float = 0.0       # values that look like codes (no spaces, has a digit)
    frac_status: float = 0.0     # values recognized as order statuses


@dataclass
class TableMap:
    raw: RawTable
    kind: str
    roles: dict[str, str] = field(default_factory=dict)     # role -> raw column
    sources: dict[str, str] = field(default_factory=dict)   # role -> 'readme' | 'name' | 'value'
    unmapped: list[str] = field(default_factory=list)
    descs: dict[str, str] = field(default_factory=dict)
    profiles: dict[str, ColProfile] = field(default_factory=dict)
    link_roles: dict[str, str] = field(default_factory=dict)  # for 'other' tables: join keys found


def data_columns(raw: RawTable) -> list[str]:
    return [c for c in raw.df.columns if not str(c).startswith("_sheet_")]


def profile_column(raw: RawTable, col: str, k: int = 400) -> ColProfile:
    s = raw.df[col]
    vals = [v for v in s.tolist() if not is_blank(v)]
    sample = vals[:: max(1, len(vals) // k)][:k] if vals else []
    nn = len(sample) or 1
    num = sum(1 for v in sample if parse_number(v) is not None) / nn
    dat = sum(1 for v in sample if parse_datetime(v, 2000) is not None) / nn
    qty = sum(1 for v in sample if parse_qty(v)[0] is not None) / nn
    code = sum(1 for v in sample if _CODELIKE_RE.match(str(v).strip()) and re.search(r"\d", str(v))) / nn
    from .schema import match_status
    from .textnorm import strip_accents
    stat = sum(1 for v in sample if isinstance(v, str) and match_status(strip_accents(v).lower().strip())) / nn
    prefixes = collections.Counter()
    for v in sample:
        m = _CODE_RE.match(str(v).strip())
        if m:
            prefixes[m.group(1)] += 1
    prefix = None
    if prefixes:
        p, c = prefixes.most_common(1)[0]
        if c >= 0.8 * nn:
            prefix = p
    distinct = len(set(map(str, vals[:20000])))
    return ColProfile(col, len(s), len(s) - len(vals), distinct, num, dat, prefix, [str(v) for v in sample[:5]], qty,
                      code, stat)


def readme_cols_for(raw: RawTable, info: ReadmeInfo) -> dict[str, str]:
    """Find README column descriptions applying to this logical table."""
    out: dict[str, str] = {}
    for (fname, sheet), cols in info.columns.items():
        f = fix_mojibake(fname)
        stem = f.rsplit(".", 1)[0]
        names = {logical_name(stem), stem}
        if sheet:
            ok = raw.sheet == sheet or raw.name == sheet
        else:
            ok = raw.name in names or any(p.split("[")[0] == f for p in raw.parts) or raw.file == f
            if raw.sheet and raw.name not in names and raw.name != logical_name(stem):
                ok = ok and raw.name in names
        if ok:
            for c, d in cols.items():
                out.setdefault(c, d)
    return out


def _kind_by_name(raw: RawTable) -> str | None:
    keys = [col_norm(raw.name).replace(" ", ""), col_norm(raw.file.rsplit(".", 1)[0]).replace(" ", "")]
    for key in keys:
        best, best_end, best_len = None, -1, 0
        for kind, kws in KIND_NAME_KEYWORDS:
            for kw in kws:
                pos = key.rfind(kw)
                if pos < 0:
                    continue
                end = pos + len(kw)
                # the head noun of a Vietnamese compound comes last: prefer the keyword ending latest,
                # then the longest one
                if end > best_end or (end == best_end and len(kw) > best_len):
                    best, best_end, best_len = kind, end, len(kw)
        if best:
            return best
    return None


def _name_hits(cols: list[str], kind: str) -> dict[str, list[str]]:
    hits: dict[str, list[str]] = collections.defaultdict(list)
    table = ROLE_NAMES.get(kind, {})
    for c in cols:
        n = col_norm(c)
        for role, names in table.items():
            if n in names:
                hits[role].append(c)
    return hits


def classify(raw: RawTable, descs: dict[str, str], hints: dict[str, str] | None = None,
             profiles: dict | None = None) -> str:
    cols = data_columns(raw)
    kind = _kind_by_name(raw)
    hints = hints or {}
    profiles = profiles or {c: profile_column(raw, c) for c in cols}
    guess = set(hints.values()) | {_desc_role(d) for d in descs.values()}
    for c in cols:
        for score, role in role_candidates(c, profiles[c], "lines"):
            if score >= 80:
                guess.add(role)
    has_product = bool({"product_name", "product_id"} & guess)
    money = bool({"line_amount", "unit_price"} & guess)
    has_qty = bool({"qty", "qty_base"} & guess) or money
    has_order = "order_id" in guess
    if kind in ("lines", "orders", None):
        if kind is None:
            k2 = _structural_kind(raw, cols)
            if k2:
                return k2
        if has_product and (has_qty or has_order) and (money or has_qty):
            return "lines"
        if has_order:
            return "orders"
        return kind or "other"
    if kind == "imports" and has_product:
        return "import_lines"
    if kind == "products":
        if _name_hits(cols, "conv").get("factor") or any(
                sc >= 80 and r == "factor" for c in cols for sc, r in role_candidates(c, profiles[c], "conv")):
            return "conv"
        if has_order and has_product:
            return "lines"
    return kind


def _rn(kind: str, *roles: str) -> list[str]:
    t = ROLE_NAMES.get(kind, {})
    return [n for r in roles for n in t.get(r, [])]


def _structural_kind(raw: RawTable, cols: list[str]) -> str | None:
    names = {col_norm(c) for c in cols}
    def any_in(lst):
        return any(n in names for n in lst)
    if any_in(_rn("conv", "factor")):
        return "conv"
    if any_in(_rn("stock", "stock_qty")):
        return "stock"
    if any_in(_rn("lot_sales", "return_qty_base")):
        return "lot_sales"
    if any_in(_rn("prices", "effective_date")):
        return "prices"
    if any_in(_rn("deliveries", "delivery_no")):
        return "deliveries"
    if any_in(_rn("debt_terms", "credit_days", "due_date")):
        return "debt_terms"
    if any_in(_rn("drugs", "active_ingredient", "is_rx")):
        return "drugs"
    if any_in(_rn("lots", "expiry")) and any_in(_rn("lots", "lot")):
        return "lots"
    if any_in(_rn("customers", "phone")) and not any_in(_ORDERISH):
        return "customers"
    return None


_ORDERISH = ["ma hoa don", "ma don", "ma don hang", "ma bill"]


def _desc_role(desc: str) -> str | None:
    d = col_norm(desc)
    for pat, role in DESC_ROLES:
        if re.search(pat, d):
            return role
    return None


_NAME_ROLE_BY_KIND = {"products": "product_name", "customers": "customer_name", "employees": "employee_name",
                      "suppliers": "supplier_name", "conv": "product_name", "stock": "product_name"}


def _resolve_desc_role(kind: str, role: str | None) -> str | None:
    if role is None:
        return None
    if role == "_name":
        return _NAME_ROLE_BY_KIND.get(kind)
    if role in ("_empty", "_created"):
        return role
    role = DESC_ROLE_ALIASES.get((kind, role), role)
    if kind == "products" and role == "unit":
        role = "base_unit"
    if kind == "stock" and role == "unit":
        role = "base_unit"
    if kind == "import_lines" and role == "unit_price":
        role = "unit_cost"
    if kind == "lines" and role == "discount":
        role = "line_discount"
    if kind == "orders" and role == "discount":
        role = "order_discount"
    if kind == "lots" and role == "qty":
        role = "qty_base"
    return role if role in ROLE_NAMES.get(kind, {}) else None


_NUM_ROLES = {"qty", "qty_base", "unit_price", "line_discount", "line_amount", "cost_unit", "goods_amount",
              "order_discount", "shipping_fee", "vat", "total_payable", "paid_amount", "debt_amount", "price", "cost",
              "factor", "pay_amount", "import_total", "unit_cost", "stock_qty", "unit_cost_base", "return_qty_base",
              "new_price", "old_price", "delivery_no", "credit_days", "amount", "refund_amount", "balance", "guests",
              "line_no"}
_DATE_ROLES = {"order_date", "order_ts", "order_time", "pay_ts", "import_date", "expiry", "effective_date",
               "delivery_date", "due_date", "expense_date", "return_ts", "ts", "birthday", "start_date", "end_date"}


def _role_type(role: str) -> str:
    if role in _NUM_ROLES:
        return "num"
    if role in _DATE_ROLES:
        return "date"
    if role.endswith("_id") or role == "lot":
        return "id"
    return "str"


def _compatible(role: str, p: ColProfile, exact: bool = False) -> bool:
    """Can a column with profile p hold this role? `exact`: the header matched a dictionary name."""
    t = _role_type(role)
    if role in ("qty", "qty_base"):
        return p.frac_qty >= 0.9
    if t == "num":
        return p.frac_num >= 0.9
    if t == "date":
        return p.frac_date >= 0.8
    if role in ("is_rx",):
        return True
    if t == "id":
        if p.prefix and ID_PREFIX_ROLE.get(p.prefix) not in (None, role) and not exact:
            return False          # e.g. PN-codes are import ids, not product ids
        return exact or p.prefix is not None or (p.frac_code >= 0.9 and p.n_distinct > 1)
    if role in ("phone", "note"):
        return True
    if role in _NAME_ROLES:
        if p.frac_num >= 0.5 or p.prefix is not None or p.frac_code >= 0.5:
            return False
        return exact or p.n_distinct > 1
    if role == "status":
        return p.frac_status >= 0.5 or p.frac_num < 0.5
    return p.frac_num < 0.5


# generic Vietnamese spreadsheet header semantics (not tied to any business type)
_TOKEN_RULES: list[tuple[str, tuple[str, ...], int]] = [
    (r"^(ma|so|id)\s*(don|hd|hoa don|don hang|bill|ct|chung tu|phieu|gd|giao dich|order)\b", ("order_id",), 85),
    (r"^ma\s*(kh|khach)|^(so|id)\s*kh\b|customer id", ("customer_id",), 86),
    (r"^ma\s*(hang|sp|san pham|mat hang|hh|sku|mon|thuoc|vat tu)|^sku\b|^id\s*sp", ("product_id",), 86),
    (r"^ma\s*(phieu nhap|nhap|don nhap)", ("import_id",), 86),
    (r"^(sl|so luong|sluong|soluong|s l|slg|qty)\b.*\b(le|quy|co ban|qd)\b", ("qty_base",), 88),
    (r"^(sl|so luong|sluong|soluong|s l|slg|qty)\b", ("qty", "stock_qty"), 84),
    (r"^ton\b", ("stock_qty",), 84),
    (r"^gia von", ("cost_unit", "cost"), 88),
    (r"^(gia nhap|don gia nhap)", ("unit_cost",), 88),
    (r"^(gia|don gia|price)\b", ("unit_price", "price", "new_price", "unit_cost"), 82),
    (r"^(thanh tien|tien|tong|amount|tri gia|t tien|so tien)\b", ("line_amount", "total_payable", "pay_amount", "amount"), 82),
    (r"^(da tra|da thu|khach tra|da thanh toan)", ("paid_amount",), 86),
    (r"^(phai thu|khach phai tra|can thu|tong phai tra)", ("total_payable",), 86),
    (r"^(con no|du no|chua tra|con lai)\b", ("debt_amount",), 86),
    (r"^(ngay|thoi gian|date|thoi diem)\b", ("order_date", "import_date", "pay_ts", "effective_date", "expense_date",
                                            "delivery_date", "return_ts"), 82),
    (r"^gio\b", ("order_time",), 84),
    (r"(trang thai|tinh trang|status|ket qua|xu ly|ghi chu tt)", ("status", "import_status"), 84),
    (r"^(dvt|don vi|dv|unit|d vi)\b", ("unit", "base_unit"), 84),
    (r"\b(he so|ti le quy doi|ty le quy doi|quy doi)\b", ("factor",), 84),
    (r"\b(khach|kh|ben mua|nguoi mua|doi tac)\b", ("customer_name",), 80),
    (r"(phuong thuc|hinh thuc|pttt|httt|tra bang)", ("payment_method", "pay_method"), 84),
    (r"(kenh|nguon don|ban qua|loai ban)", ("channel",), 84),
    (r"(nhom|danh muc|phan loai|loai san pham|nganh)", ("group_name", "customer_group"), 80),
    (r"(dien thoai|phone|di dong|sdt)", ("phone",), 86),
    (r"(dia chi|addr)", ("address",), 86),
    (r"(han su dung|hsd|het han)", ("expiry",), 88),
    (r"^(lo|ma lo|so lo)\b", ("lot",), 86),
    (r"\b(ten|hang|mat hang|san pham|mon|sp|product|noi dung)\b", ("product_name",), 78),
]


def role_candidates(col: str, p: "ColProfile", kind: str) -> list[tuple[float, str]]:
    """Scored role guesses for a column under a table kind (exact name > header rules > fuzzy)."""
    from rapidfuzz import fuzz
    table = ROLE_NAMES.get(kind, {})
    n = col_norm(col)
    out: dict[str, float] = {}
    if not n or n.startswith("col ") or p.n_blank == p.n:
        return []
    toks = set(n.split())
    for role, names in table.items():
        if n in names:
            if _compatible(role, p, exact=True):
                out[role] = 100.0
            continue
        if not _compatible(role, p):
            continue
        best = 0.0
        for x in names:
            sc = max(fuzz.ratio(n, x), fuzz.token_sort_ratio(n, x))
            xt = x.split()
            if len(xt) >= 2 and _role_type(role) != "id" and re.search(r"" + re.escape(x) + r"", n):
                sc = max(sc, 88)
            best = max(best, sc)
        if best >= 82:
            # fuzzy only fills gaps: below header rules unless almost identical
            out[role] = best if best >= 95 else min(best, 83.0)
    for pat, roles, sc in _TOKEN_RULES:
        if re.search(pat, n):
            for r in roles:
                if r in table and _compatible(r, p) and out.get(r, 0) < sc:
                    out[r] = float(sc)
    if "status" in table and p.frac_status >= 0.95 and p.n_distinct <= 30:
        out["status"] = max(out.get("status", 0), 95.0)   # values are order statuses
        out.pop("note", None)
    return sorted(((v, r) for r, v in out.items()), reverse=True)


def map_table(raw: RawTable, info: ReadmeInfo, hints: dict[str, str] | None = None,
              force_kind: str | None = None) -> TableMap:
    descs = readme_cols_for(raw, info)
    cols = data_columns(raw)
    profiles = {c: profile_column(raw, c) for c in cols}
    kind = force_kind or classify(raw, descs, hints, profiles)
    tm = TableMap(raw=raw, kind=kind, descs=descs, profiles=profiles)
    roles_table = ROLE_NAMES.get(kind, {})
    taken: dict[str, str] = {}
    sources: dict[str, str] = {}
    empty_cols = set()
    # 1) README descriptions
    for c in cols:
        if c in descs:
            r = _resolve_desc_role(kind, _desc_role(descs[c]))
            if r == "_empty":
                empty_cols.add(c)
                continue
            if r and r != "_created" and r not in taken:
                taken[r], sources[r] = c, "readme"
    # 1b) hints from cross-table value linking
    for c, r in (hints or {}).items():
        if r in roles_table and r not in taken and c not in taken.values():
            taken[r], sources[r] = c, "link"
    # 2) dictionary / header rules / fuzzy, best score first
    used = set(taken.values()) | empty_cols
    cands = []
    for c in cols:
        if c in used:
            continue
        for sc, r in role_candidates(c, profiles[c], kind):
            cands.append((sc, -cols.index(c), c, r))
    for sc, _, c, r in sorted(cands, reverse=True):
        if r in taken or c in used:
            continue
        taken[r], sources[r] = c, ("name" if sc >= 100 else "rule")
        used.add(c)
    # 3) value prefixes: fix id roles / fill missing id roles
    for c in cols:
        p = tm.profiles[c].prefix
        if not p:
            continue
        vr = ID_PREFIX_ROLE.get(p)
        if not vr or vr not in roles_table:
            continue
        cur_role = next((r for r, cc in taken.items() if cc == c), None)
        if cur_role == vr:
            continue
        if cur_role and cur_role.endswith("_id") and sources.get(cur_role) != "readme":
            # name said one id, values say another -> trust values
            del taken[cur_role]
            if vr in taken and sources.get(vr) != "readme":
                taken.pop(vr)
            taken[vr], sources[vr] = c, "value"
        elif cur_role is None and vr not in taken:
            taken[vr], sources[vr] = c, "value"
    # 4) heuristic: unmapped status-like column in sales tables
    if kind in ("lines", "orders") and "status" not in taken:
        for c in cols:
            if c in taken.values():
                continue
            from .schema import match_status
            from .textnorm import strip_accents
            sm = tm.profiles[c].samples
            if sm and all(match_status(strip_accents(s).lower()) for s in sm):
                taken["status"], sources["status"] = c, "value"
                break
    tm.roles, tm.sources = taken, sources
    tm.unmapped = [c for c in cols if c not in taken.values() and c not in empty_cols]
    return tm


# ---------------------------------------------------------------- business-level pass
_SALES_MONEY = {"line_amount", "unit_price"}
_ORDER_EVIDENCE = {"total_payable", "goods_amount", "paid_amount", "debt_amount", "status", "customer_name",
                   "customer_id", "payment_method"}


def _values(raw: RawTable, col: str, limit: int = 50000) -> set:
    from .textnorm import key_norm
    out = set()
    for v in raw.df[col].tolist()[:limit]:
        if not is_blank(v):
            out.add(key_norm(str(v).strip()))
    return out


def _overlap(vals: set, vocab: set) -> float:
    return len(vals & vocab) / len(vals) if vals else 0.0


def map_business(raws: list[RawTable], info: ReadmeInfo) -> list[TableMap]:
    """Map all tables of one business: per-table mapping, then cross-table value linking,
    then pick the primary sales tables (secondary look-alikes become 'other')."""
    def demote(tm):
        tm2 = map_table(tm.raw, info, force_kind="other")
        tm2.link_roles = {r: c for r, c in tm.roles.items() if r.endswith("_id") or r in ("product_name", "lot")}
        return tm2

    maps = [map_table(r, info) for r in raws]
    # vocabularies of known entities
    prod_vocab, order_vocab = set(), set()
    for tm in maps:
        if tm.roles.get("product_name") and tm.kind in ("products", "conv", "stock", "prices", "import_lines", "lines"):
            prod_vocab |= _values(tm.raw, tm.roles["product_name"])
        if tm.roles.get("order_id") and tm.kind in ("lines", "orders"):
            order_vocab |= _values(tm.raw, tm.roles["order_id"])
    for i, tm in enumerate(maps):
        hints = {}
        for c in tm.unmapped:
            p = tm.profiles[c]
            if p.frac_num > 0.5:
                continue
            vals = _values(tm.raw, c, 5000)
            if prod_vocab and "product_name" not in tm.roles and _overlap(vals, prod_vocab) >= 0.5:
                hints[c] = "product_name"
            elif order_vocab and "order_id" not in tm.roles and _overlap(vals, order_vocab) >= 0.5:
                hints[c] = "order_id"
        if hints:
            maps[i] = map_table(tm.raw, info, hints)
    # primary sales tables
    line_ids = set()
    for tm in maps:
        if tm.kind == "lines" and tm.roles.get("order_id"):
            line_ids |= _values(tm.raw, tm.roles["order_id"])
    if line_ids:
        for i, tm in enumerate(maps):
            if tm.kind == "orders" and tm.roles.get("order_id"):
                cov = len(_values(tm.raw, tm.roles["order_id"]) & line_ids) / len(line_ids)
                if cov < 0.6:
                    maps[i] = demote(tm)
    for kind, need in (("lines", _SALES_MONEY), ("orders", _ORDER_EVIDENCE)):
        group = [i for i, tm in enumerate(maps) if tm.kind == kind]
        ok = [i for i in group if need & set(maps[i].roles)]
        for i in group:
            if i not in ok:
                maps[i] = demote(maps[i])
        if len(ok) > 1:
            # keep tables sharing the role signature of the richest one (split files), demote the rest
            best = max(ok, key=lambda i: (len(need & set(maps[i].roles)), len(maps[i].roles), len(maps[i].raw.df)))
            sig = set(maps[best].roles)
            for i in ok:
                if i != best and len(set(maps[i].roles) ^ sig) > 2:
                    maps[i] = demote(maps[i])
    return maps
