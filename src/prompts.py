"""Prompt construction: per-business schema description, capability notes, exemplar retrieval."""
from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass, field
from typing import Optional

import yaml

from .canon import Business
from .entities import EntityIndex
from .qnorm import plain
from .rules import Rules
from .sandbox import Sandbox, describe_all

WEEKDAYS = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ nhật"]

TABLE_ORDER = ["valid_orders", "orders", "valid_lines", "lines", "products", "unit_conv", "customers", "payments",
               "imports", "import_lines", "stock", "ledger", "lots", "lot_sales", "prices", "deliveries", "debt_terms",
               "expenses", "returns", "employees", "suppliers", "order_tables"]

TABLE_DOC = {
    "valid_orders": "ĐƠN HỢP LỆ tính vào doanh thu (không huỷ, không trả hàng; đơn đang giao vẫn tính). Một dòng = một đơn. "
                    "revenue = doanh thu của đơn.",
    "orders": "TẤT CẢ đơn mọi trạng thái (dùng để đếm đơn huỷ/tỉ lệ huỷ, nợ). status ∈ hoan_thanh|huy|tra_hang|dang_giao.",
    "valid_lines": "DÒNG HÀNG của đơn hợp lệ, kèm ngày/khách/kênh của đơn. line_amount = thành tiền dòng (đã trừ giảm giá dòng). "
                   "is_item=FALSE là dòng không phải mặt hàng (không xếp hạng/đếm, vẫn tính doanh thu).",
    "lines": "Dòng hàng của MỌI đơn (kể cả huỷ/trả), có status. Dùng cho giá bán theo ngày. factor = số đơn vị cơ bản trong 1 đơn vị của dòng.",
    "products": "Danh mục mặt hàng.",
    "unit_conv": "Quy đổi đơn vị lớn → đơn vị cơ bản (factor).",
    "customers": "Danh sách khách.",
    "payments": "Các lần khách trả tiền cho đơn (mỗi lần một dòng).",
    "imports": "Phiếu nhập hàng (tiền cả phiếu).",
    "import_lines": "Dòng nhập hàng (đơn giá/số lượng theo đơn vị nhập của dòng).",
    "stock": "Tồn kho CUỐI NGÀY CUỐI có dữ liệu (đơn vị cơ bản).",
    "ledger": "Thẻ kho: mỗi dòng một lần nhập/bán/trả, balance = tồn sau lần đó (đơn vị cơ bản).",
    "lots": "Lô hàng nhập: hạn dùng, số lượng nhập (đơn vị cơ bản).",
    "lot_sales": "Số lượng bán/trả lấy từ từng lô (đơn vị cơ bản).",
    "prices": "Lịch sử giá bán theo ngày áp dụng (đơn vị cơ bản).",
    "deliveries": "Sổ giao hàng (mỗi dòng một mặt hàng của một đợt giao).",
    "debt_terms": "Hạn thanh toán của đơn bán nợ.",
    "expenses": "Sổ chi phí.",
    "returns": "Phiếu trả hàng.",
    "employees": "Nhân viên.",
    "suppliers": "Nhà cung cấp.",
    "order_tables": "Bàn/khu vực/số khách của đơn.",
}

COL_DOC = {
    "order_date": "ngày đặt", "order_ts": "ngày giờ đặt", "customer_key": "khoá khách (mã hoặc tên chuẩn hoá)",
    "customer_display": "tên khách để trả lời (NULL nếu khách lẻ)", "is_walkin": "khách lẻ/vãng lai",
    "customer_group": "nhóm khách", "payment_method": "hình thức thanh toán ghi trên đơn",
    "channel": "kênh bán", "employee_id": "nhân viên bán", "revenue": "doanh thu đơn", "total_payable": "khách phải trả cả đơn (đã trừ giảm giá đơn, gồm phí giao)",
    "paid_amount": "đã thanh toán", "debt_amount": "còn nợ ghi trong file", "goods_amount": "tiền hàng trước giảm giá đơn",
    "items_amount": "tổng thành tiền các dòng", "order_discount": "giảm giá cả đơn", "shipping_fee": "phí giao", "vat": "thuế VAT",
    "has_return": "đơn có trả hàng", "qty": "số lượng theo đơn vị của dòng", "qty_base": "số lượng quy về đơn vị cơ bản",
    "unit_price": "đơn giá theo đơn vị của dòng (trước giảm giá dòng)", "line_discount": "giảm giá dòng",
    "line_amount": "thành tiền dòng", "cost_unit": "giá vốn một đơn vị bán (ghi trên dòng)", "base_unit": "đơn vị cơ bản",
    "group_name": "nhóm hàng", "is_item": "TRUE nếu là mặt hàng", "factor": "hệ số quy đổi của đơn vị dòng",
    "price": "giá bán hiện tại", "cost": "giá vốn hiện tại", "active_ingredient": "hoạt chất", "is_rx": "thuốc kê đơn",
    "pay_date": "ngày trả", "pay_ts": "giờ trả", "pay_method": "hình thức trả", "pay_amount": "số tiền trả",
    "import_date": "ngày phiếu", "import_total": "tổng tiền phiếu", "is_cancelled": "phiếu huỷ", "unit_cost": "giá nhập 1 đơn vị nhập",
    "lot": "số lô", "expiry": "hạn dùng", "stock_qty": "tồn", "as_of": "ngày của số tồn", "effective_date": "ngày áp dụng giá",
    "new_price": "giá mới", "old_price": "giá cũ", "delivery_date": "ngày giao", "delivery_no": "đợt giao", "due_date": "hạn thanh toán",
    "credit_days": "số ngày được nợ", "return_qty_base": "số lượng khách trả lại", "balance": "tồn sau giao dịch",
    "address": "địa chỉ", "gender": "giới tính", "phone": "điện thoại", "aliases": "các cách viết khác",
}

HIDE_COLS = {"status_raw", "payment_method_raw", "src", "product_name_raw", "n_lines", "net_line_amount", "has_return_line",
             "cost_amount", "branch_id", "shift_id", "promo_code", "einvoice_status", "customer_name_clean", "customer_id_raw",
             "lines_total", "note", "unit_cost_base", "txn_id", "doc_id", "doc_type", "txn_type"}
ALWAYS_COLS = {"is_item", "revenue", "order_date", "order_ts", "is_walkin", "customer_key", "customer_display",
               "group_name", "status", "is_cancelled", "has_return"}
ENUM_COLS = {"status": 8, "payment_method": 10, "channel": 20, "customer_group": 20, "group_name": 60, "base_unit": 25,
             "import_status": 8, "area": 20}

TYPE_ABBR = {"DATE": "DATE", "TIMESTAMP": "TS", "BIGINT": "INT", "INTEGER": "INT", "DOUBLE": "NUM", "VARCHAR": "TEXT",
             "BOOLEAN": "BOOL", "HUGEINT": "INT", "SMALLINT": "INT", "FLOAT": "NUM"}


@dataclass
class BizContext:
    biz_id: str
    system: str
    tables: set[str]
    nonnull: dict[str, set[str]]
    any_nonnull: set[str]
    data_start: Optional[dt.date]
    data_end: Optional[dt.date]
    entity_index: EntityIndex
    has_orders: bool

    def has(self, req: str) -> bool:
        if "." in req:
            t, c = req.split(".", 1)
            return c in self.nonnull.get(t, self.any_nonnull if t in self.tables else set())
        return req in self.tables or req in self.any_nonnull


# ---------------------------------------------------------------- capability notes
def capability_notes(biz: Business, tables: set[str], any_nonnull: set[str]) -> list[str]:
    n = []
    if "orders" not in tables:
        n.append("Sổ bán hàng KHÔNG có mã đơn và không có bảng đơn: không tính được số đơn, khách, tỉ lệ huỷ, nợ, giá trị trung bình "
                 "một đơn → các câu đó là unanswerable. Doanh thu/số lượng/mặt hàng dùng valid_lines.")
    if "lines" not in tables and "orders" in tables:
        n.append("Chỉ có bảng đơn, KHÔNG có dòng hàng: không có doanh thu theo mặt hàng/nhóm hàng/số lượng bán. Doanh thu dùng valid_orders.revenue.")
    if "imports" not in tables:
        n.append("Không có dữ liệu nhập hàng (tiền nhập, nhà cung cấp, giá nhập).")
    if "stock" not in tables and "ledger" not in tables:
        n.append("Không có dữ liệu tồn kho (tồn, giá trị tồn, hết hàng).")
    if "payments" not in tables and "debt_amount" not in any_nonnull:
        n.append("Không có dữ liệu thanh toán/công nợ (nợ, trả nợ, tuổi nợ).")
    elif "payments" not in tables:
        n.append("Không có bảng payments: công nợ chỉ có cột orders.debt_amount (nợ tính đến ngày cuối dữ liệu). Không tính được nợ thêm/trả nợ trong kỳ.")
    if "cost_unit" not in any_nonnull and "cost" not in any_nonnull:
        n.append("Không có giá vốn: không tính được lãi gộp/hàng lời nhất/giá trị tồn theo giá vốn.")
    if "orders" in tables and "payment_method" not in any_nonnull:
        n.append("Đơn không ghi hình thức thanh toán.")
    if "orders" in tables and "channel" not in any_nonnull:
        n.append("Đơn không ghi kênh bán.")
    if "orders" in tables and "employee_id" not in any_nonnull:
        n.append("Đơn không ghi nhân viên bán.")
    if "customers" in tables:
        miss = [x for x, c in (("địa chỉ", "address"), ("giới tính", "gender"), ("nhóm khách", "customer_group")) if c not in any_nonnull]
    else:
        miss = ["địa chỉ", "giới tính"]
    if miss:
        n.append("Khách không có thông tin: " + ", ".join(miss) + ".")
    if "lots" not in tables:
        n.append("Không có lô/hạn dùng.")
    if "order_ts" not in any_nonnull:
        n.append("Không có giờ đặt đơn: không tính được theo ca.")
    return n


# ---------------------------------------------------------------- schema text
def _enum_values(biz: Business, col: str, limit: int) -> list[str]:
    vals = []
    for df in biz.tables.values():
        if col in df.columns:
            vals += [str(v) for v in df[col].dropna().unique().tolist()]
    vals = sorted(set(vals))
    return vals if 0 < len(vals) <= limit else []


def build_context(biz: Business, sb: Sandbox, rules: Rules) -> BizContext:
    desc = describe_all(sb)
    tables = set(desc)
    nonnull = {t: {c for c in df.columns if df[c].notna().any()} for t, df in biz.tables.items()}
    any_nonnull = set().union(*nonnull.values()) if nonnull else set()
    enums = {c: _enum_values(biz, c, lim) for c, lim in ENUM_COLS.items()}
    parts = []
    shown_enum: set[str] = set()
    names = [t for t in TABLE_ORDER if t in tables]
    other = [t for t in tables if t not in TABLE_ORDER and not t.startswith("raw_") and not t.startswith("_")]
    for t in names + other:
        cols = []
        base_nn = nonnull.get(t)
        for c, typ in desc[t]:
            if c in HIDE_COLS:
                continue
            if c not in ALWAYS_COLS and (c not in (base_nn if base_nn is not None else any_nonnull)):
                continue
            ab = "TS" if typ.startswith("TIMESTAMP") else TYPE_ABBR.get(typ.split("(")[0], typ)
            s = f"{c} {ab}"
            doc = COL_DOC.get(c)
            if doc:
                s += f" [{doc}]"
            if enums.get(c) and c not in shown_enum:
                shown_enum.add(c)
                s += " ∈ {" + ", ".join(enums[c]) + "}"
            cols.append(s)
        n_rows = len(biz.tables[t]) if t in biz.tables else None
        head = f"### {t}" + (f" ({n_rows} dòng)" if n_rows else "") + f" — {TABLE_DOC.get(t, '')}"
        parts.append(head + "\n" + "; ".join(cols))
    raw_other = [r for r, k in biz.raw_kinds.items() if k == "other" and r in tables]
    for r in raw_other:
        cols = ", ".join(c for c, _ in desc[r])
        parts.append(f"### {r} (bảng thô chưa nhận diện) — cột: {cols}")
    notes = capability_notes(biz, tables, any_nonnull)
    f = biz.flags
    start, end = f.get("data_start"), f.get("data_end")
    ctx_text = [f"## Dữ liệu của cửa hàng", f"Có dữ liệu từ {start} đến hết {end}. Kỳ nằm hoàn toàn ngoài khoảng này → unanswerable (hệ thống tự kiểm tra)."]
    if notes:
        ctx_text.append("Lưu ý về những gì dữ liệu KHÔNG có (câu hỏi cần thông tin này → TYPE: unanswerable):\n" +
                        "\n".join("- " + x for x in notes))
    ctx_text.append("Các bảng/view dùng được:\n" + "\n".join(parts))
    system = SYSTEM_TEMPLATE.format(rulebook=(rules.prompt_text or rules.text).strip(), data="\n".join(ctx_text))
    return BizContext(biz.biz_id, system, tables, nonnull, any_nonnull, start, end, EntityIndex.build(biz), "orders" in tables)


SYSTEM_TEMPLATE = """Bạn là trợ lý phân tích dữ liệu bán hàng của một cửa hàng nhỏ ở Việt Nam. Người dùng hỏi bằng tiếng Việt (thường không dấu, viết tắt, có lỗi gõ). \
Bạn viết MỘT câu truy vấn SQL DuckDB trên các bảng dưới đây để tính đáp án. Bạn KHÔNG tự tính ngày: chỉ khai báo kỳ, hệ thống sẽ đổi thành điều kiện thật.

# RULEBOOK (luật tính đáp án; câu hỏi nói khác thì theo câu hỏi)
{rulebook}

{data}

# CÁCH TRẢ LỜI
Trả lời đúng định dạng sau, không giải thích thêm:
TYPE: number | percent | string | date | boolean | list | table | unanswerable
PERIODS: P1 = <biểu thức kỳ> ; P2 = <biểu thức kỳ>   (mỗi kỳ dùng trong SQL phải khai báo ở đây)
DECIMALS: 0   (tuỳ chọn, chỉ cho number: 0 = làm tròn về đồng/số nguyên)
COLUMNS: tên_cột_1, tên_cột_2   (chỉ cho table: cột đầu là tên đối tượng, các cột sau là số đo theo thứ tự câu hỏi)
REASON: <lý do>   (chỉ cho unanswerable)
SQL:
<một câu SELECT hoặc WITH ... SELECT>

Biểu thức kỳ: today, yesterday, this_week (thứ Hai→hết hôm nay), last_week (cả tuần trước), this_month (ngày 1→hết hôm nay), \
last_month, this_quarter, last_quarter, this_year (từ đầu năm→hết hôm nay), last_year, last_n_days:N (N ngày gần nhất kể cả hôm nay), \
day:YYYY-MM-DD, month:YYYY-MM, month:M (tháng không ghi năm), quarter:YYYY-Q1, quarter:Q (không ghi năm), year:YYYY, \
range:YYYY-MM-DD..YYYY-MM-DD (gồm hai đầu), until:YYYY-MM-DD (từ đầu dữ liệu đến hết ngày đó), until_today, tet:YYYY (mùa Tết năm YYYY), \
days_from:YYYY-MM-DD,N (N ngày kể từ ngày đó, gồm ngày đó), days_before:YYYY-MM-DD,N (N ngày ngay trước), ahead:N (từ hôm nay đến hết ngày hôm nay+N), \
prev(P1) (kỳ liền trước / cùng số ngày của kỳ trước), yoy(P1) (cùng kỳ năm ngoái). Dùng ngày ghi trong câu hỏi (dd/mm/yyyy → YYYY-MM-DD).
Trong SQL: {{P1:cột_ngày}} thành điều kiện lọc cột ngày; {{P1.start}}, {{P1.end}} (không gồm), {{P1.last}}, {{P1.days}}; \
{{SHIFT:ca_sang:cột_giờ}} / {{SHIFT:ca_chieu:cột_giờ}} cho ca. TUYỆT ĐỐI không viết ngày trực tiếp, không dùng current_date/INTERVAL.

Quy tắc SQL:
- Doanh thu/thành tiền: valid_lines.line_amount (hoặc valid_orders.revenue). Đếm đơn: valid_orders. Đếm đơn huỷ/tỉ lệ huỷ: orders (mọi trạng thái).
- Xếp hạng: sắp giảm dần theo số đo, đồng hạng sắp theo mã tăng dần (không có mã thì theo tên); ORDER BY ... LIMIT k. Bán chạy theo SUM(qty_base), loại dòng is_item=FALSE.
- Tên mặt hàng/nhóm/khách/kênh: sao chép NGUYÊN VĂN giá trị trong phần "Thực thể nhận diện" hoặc danh sách giá trị ở trên.
- string/list: trả về tên (không kèm nhãn). Tiền là số nguyên VND. Phần trăm là số phần trăm (12.5), giảm thì âm.
- list trả nhiều số: một dòng, mỗi số một cột theo đúng thứ tự câu hỏi; list tên: mỗi tên một dòng đã sắp thứ tự.
- Nếu dữ liệu không có thông tin cần để trả lời (xem mục "Lưu ý"), hoặc câu hỏi mang tính đánh giá chủ quan: TYPE: unanswerable.
"""


# ---------------------------------------------------------------- exemplars
@dataclass
class Exemplar:
    q: str
    type: str
    periods: list[str] = field(default_factory=list)
    sql: str = ""
    decimals: Optional[int] = None
    columns: list[str] = field(default_factory=list)
    reason: str = ""
    entities: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)
    absent: list[str] = field(default_factory=list)

    def render_answer(self) -> str:
        out = [f"TYPE: {self.type}"]
        if self.type == "unanswerable":
            out.append(f"REASON: {self.reason}")
            return "\n".join(out)
        out.append("PERIODS: " + " ; ".join(self.periods) if self.periods else "PERIODS:")
        if self.decimals is not None:
            out.append(f"DECIMALS: {self.decimals}")
        if self.columns:
            out.append("COLUMNS: " + ", ".join(self.columns))
        out.append("SQL:\n" + self.sql.strip())
        return "\n".join(out)

    def render_question(self, today: str = "2026-06-15") -> str:
        ents = ("Thực thể nhận diện trong câu hỏi:\n" + "\n".join("- " + e for e in self.entities) + "\n") if self.entities else ""
        return f"Hôm nay: {today}.\n{ents}CÂU HỎI: {self.q}"


class ExemplarStore:
    def __init__(self, path: Optional[str] = None):
        path = path or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "configs", "exemplars.yaml")
        raw = yaml.safe_load(open(path, encoding="utf-8")) or []
        self.items = [Exemplar(q=r["q"], type=r["type"], periods=r.get("periods") or [], sql=r.get("sql", ""),
                               decimals=r.get("decimals"), columns=r.get("columns") or [], reason=r.get("reason", ""),
                               entities=r.get("entities") or [], requires=r.get("requires") or [], absent=r.get("absent") or [])
                      for r in raw]
        from sklearn.feature_extraction.text import TfidfVectorizer
        self.vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), sublinear_tf=True)
        self.mat = self.vec.fit_transform([plain(e.q) for e in self.items])

    def select(self, question: str, ctx: BizContext, k: int = 5) -> list[Exemplar]:
        import numpy as np
        sims = (self.mat @ self.vec.transform([plain(question)]).T).toarray().ravel()
        order = np.argsort(-sims)
        chosen: list[Exemplar] = []
        for i in order:
            e = self.items[i]
            if not all(ctx.has(r) for r in e.requires) or any(a in ctx.tables for a in e.absent):
                continue
            chosen.append(e)
            if len(chosen) >= k:
                break
        return list(reversed(chosen))   # most similar last (closest to the question)


def user_message(question: str, as_of: dt.date, entities_text: str) -> str:
    ents = f"Thực thể nhận diện trong câu hỏi:\n{entities_text}\n" if entities_text else ""
    return f"Hôm nay: {as_of.isoformat()} ({WEEKDAYS[as_of.weekday()]}).\n{ents}CÂU HỎI: {question}"


def build_messages(ctx: BizContext, store: ExemplarStore, question: str, as_of: dt.date, entities_text: str,
                   k: int = 5) -> list[dict]:
    msgs = [{"role": "system", "content": ctx.system}]
    for e in store.select(question, ctx, k):
        msgs.append({"role": "user", "content": e.render_question()})
        msgs.append({"role": "assistant", "content": e.render_answer()})
    msgs.append({"role": "user", "content": user_message(question, as_of, entities_text)})
    return msgs
