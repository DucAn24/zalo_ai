"""Canonical table kinds, column roles and the dictionaries used to map raw columns.

All names are matched after `textnorm.col_norm` (accents stripped, lowercase,
camelCase split, punctuation -> space). Dictionaries were assembled from the
column names / README role phrases of the train split; unknown columns fall back
to value heuristics and stay available as raw columns.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------- table kinds
# kind -> keywords in the normalized logical table name (spaces removed)
KIND_NAME_KEYWORDS: list[tuple[str, list[str]]] = [
    ("lot_sales", ["chitiethoadonlo", "hoadonchitietlo", "donhanglo", "bantheolo", "chitietdonlo", "donlo"]),
    ("lots", ["lohang", "danhsachlo"]),
    ("deliveries", ["giaohang", "phieugiao"]),
    ("debt_terms", ["congno", "hanno", "hanthanhtoan"]),
    ("expenses", ["chiphi"]),
    ("returns", ["trahang", "phieutra"]),
    ("ledger", ["thekho"]),
    ("stock", ["tonkho"]),
    ("prices", ["banggia", "lichsugia"]),
    ("drugs", ["thuoc"]),
    ("conv", ["quydoi", "donvitinh", "donvisp"]),
    ("customers", ["khachhang"]),
    ("employees", ["nhanvien"]),
    ("suppliers", ["nhacungcap"]),
    ("branches", ["chinhanh"]),
    ("payments", ["thanhtoan", "phieuthu", "soquy"]),
    ("tables", ["phongban"]),
    ("import_lines", ["chitietnhap", "nhaphangchitiet", "nhapchitiet", "chitietphieunhap"]),
    ("imports", ["nhaphang", "phieunhap", "donnhap", "nhap"]),
    ("lines", ["chitiet", "sobanhang", "banhang", "dulieuban"]),
    ("products", ["sanpham", "hanghoa", "danhmuc", "mathang"]),
    ("orders", ["hoadon", "donhang", "dsdon"]),
]

KINDS = [k for k, _ in KIND_NAME_KEYWORDS] + ["other"]

# ---------------------------------------------------------------- role name dictionaries
# For each kind: role -> list of normalized column names (exact) ; regex fallbacks below.
_ORDER_ID = ["ma hoa don", "ma don", "ma don hang", "ma gd", "ma bill", "so phieu", "ma phieu", "ma giao dich",
             "so ct", "ma chung tu", "order id", "so hd", "so hoa don", "ma hd", "so don", "id don", "ma order"]
_PRODUCT_ID = ["ma hang", "id sp", "ma hh", "ma sku", "sku", "ma san pham", "ma hang hoa", "ma mat hang", "ma hang ban",
               "ma san pham ban", "ma sp", "ma mon", "ma thuoc", "ma vat tu"]
_PRODUCT_NAME = ["ten hang", "noi dung", "ten san pham", "hang", "hang hoa", "ten hang hoa", "mat hang", "san pham",
                 "ten sp", "hang ban", "chi tiet hang", "product", "ten mat hang", "ten mon", "mon", "ten thuoc",
                 "ten goi", "ten"]
_UNIT = ["don vi tinh", "don vi", "unit", "dvt", "dv tinh", "d vi", "dv", "don vi ban"]
_QTY = ["so luong", "sl", "sluong", "so luong san pham", "sl ban", "so luong hang", "so luong ban", "slg", "s l",
        "soluong", "qty", "so luong mua"]
_QTY_BASE = ["quy ra dv le", "so luong quy doi", "sl quy doi", "so luong le", "sl le", "sl co ban", "sl quy ra le",
             "so luong dvt co ban", "so luong co ban", "sl quy doi le"]
_UNIT_PRICE = ["don gia", "gia ban", "gia san pham", "gia le", "don gia ban", "gia", "gia ban le", "gia 1 dv",
               "price", "gia don vi", "don gia d", "gia niem yet", "gia 1 don vi"]
_LINE_AMOUNT = ["thanh tien", "tong tien", "tri gia", "t tien", "tong", "amount", "thanh tien d", "tien",
                "tien ban", "thanh tien sau giam"]
_DATE = ["ngay thang", "ngay dat hang", "ngay giao dich", "ngay", "ngay ban", "ngay mua", "ngay lap", "thoi gian",
         "ngaylap", "ngay dat", "ngay hoa don", "ngay ban hang"]
_STATUS = ["ket qua", "trang thai don hang", "status", "trang thai", "trang thai xu ly", "ghi chu tt", "trang thai don",
           "xu ly", "tinh trang", "tinh trang don", "tinh trang don hang"]
_CUSTOMER_NAME = ["doi tac", "ten khach hang", "khach", "ten kh", "ten khach", "khach hang", "khach hang ten",
                  "ben mua", "nguoi mua", "kh"]
_CUSTOMER_ID = ["ma kh", "so kh", "ma kh mua", "customer id", "ma khach mua", "ma khach hang", "ma khach", "ma kh le si",
                "ma khach le si", "id khach"]

ROLE_NAMES: dict[str, dict[str, list[str]]] = {
    "lines": {
        "order_id": _ORDER_ID,
        "line_no": ["stt", "thu tu", "no", "tt dong", "so thu tu", "dong"],
        "product_id": _PRODUCT_ID,
        "product_name": _PRODUCT_NAME,
        "unit": _UNIT,
        "qty": _QTY,
        "qty_base": _QTY_BASE,
        "unit_price": _UNIT_PRICE,
        "line_discount": ["giam gia", "khuyen mai", "chiet khau", "ck", "giam"],
        "line_amount": _LINE_AMOUNT,
        "cost_unit": ["gia von", "gia von luc ban", "gia von ban"],
        "order_date": _DATE,
        "order_time": ["gio", "gio ban", "gio dat", "thoi diem"],
        "status": _STATUS,
        "customer_name": _CUSTOMER_NAME,
        "customer_id": _CUSTOMER_ID,
        "note": ["ghi chu", "dien giai"],
    },
    "orders": {
        "order_id": _ORDER_ID,
        "order_date": _DATE,
        "order_ts": ["thoi gian tao", "gio tao don", "thoi gian lap", "ngay gio lap", "thoi diem tao"],
        "customer_id": _CUSTOMER_ID,
        "customer_name": _CUSTOMER_NAME,
        "goods_amount": ["tong tien hang", "tien hang", "tien hang truoc giam", "tong tien hang hoa"],
        "order_discount": ["giam gia", "ck", "chiet khau", "giam gia don", "khuyen mai"],
        "shipping_fee": ["phi van chuyen", "phi giao", "phi giao hang", "phi ship"],
        "vat": ["thue gtgt", "vat", "thue"],
        "total_payable": ["tong sau giam gia", "tongtien", "tong tien", "tong bill", "tong don", "phai thu",
                          "tong thanh toan", "tong cong", "khach can tra", "khach phai tra"],
        "paid_amount": ["khach da tra", "da tra", "khach tra", "da thu", "thanh toan", "khach da thanh toan"],
        "debt_amount": ["con no", "chua tra", "con lai", "du no", "con phai thu", "no"],
        "payment_method": ["phuong thuc thanh toan", "phuong thuc tt", "tra bang", "hinh thuc thanh toan", "pttt", "httt"],
        "status": _STATUS,
        "channel": ["kenh ban", "ban qua", "loai ban", "nguon don", "kenh ban hang", "kenh"],
        "employee_id": ["nguoi ban", "ma nv ban", "ma nhan vien", "nhan vien", "ma nv"],
        "note": ["ghi chu", "dien giai"],
        "shift_id": ["ma ca lam", "ca lam", "ma ca"],
        "promo_code": ["ma khuyen mai"],
        "branch_id": ["ma chi nhanh"],
        "einvoice_status": ["trang thai hddt"],
    },
    "products": {
        "product_id": _PRODUCT_ID,
        "product_name": _PRODUCT_NAME,
        "group_name": ["nhom hang 3 cap", "nhom hang", "nhom hang hoa", "loai san pham", "danh muc", "phan loai",
                       "nhom", "nhom san pham", "nganh hang"],
        "base_unit": ["dvt", "don vi", "don vi tinh", "don vi co ban", "don vi co so", "dv co ban"],
        "price": ["gia ban", "gia", "gia niem yet", "gia hien tai", "gia ban le"],
        "cost": ["gia von", "gia von hien tai", "gia von hang"],
    },
    "conv": {
        "product_id": _PRODUCT_ID,
        "product_name": ["ten san pham", "ten mon", "hang", "ten hang", "san pham", "ten hang hoa"],
        "unit": ["don vi quy doi", "dv nhap", "dv lon", "dvt", "don vi", "don vi tinh", "don vi lon"],
        "factor": ["ti le quy doi", "ty le quy doi", "he so", "he so qd", "quy doi", "bang", "he so quy doi"],
        "base_unit": ["don vi co ban", "don vi goc", "dv nho", "dv goc", "dv co ban"],
        "unit_price": ["gia ban", "gia ban theo don vi quy doi", "gia don vi"],
    },
    "customers": {
        "customer_id": ["ma khach hang", "ma kh", "ma khach", "customer id", "ma kh le si", "ma khach le si"],
        "customer_name": ["ten khach hang", "khach le si", "khach hang ten", "ten kh", "kh", "ten goi", "ten",
                          "khach hang", "ho ten"],
        "phone": ["dien thoai", "phone", "di dong", "so dien thoai", "sdt"],
        "customer_group": ["nhom", "nhom khach hang", "hang", "loai khach hang", "nhom khach", "hang thanh vien"],
        "address": ["dia chi", "addr", "dia chi lien he"],
        "gender": ["gioi tinh", "nam nu"],
        "birthday": ["ngay sinh", "sinh nhat"],
    },
    "payments": {
        "payment_id": ["ma phieu", "ma phieu thu", "phieu thu", "ma gd", "so phieu thu"],
        "order_id": ["ma hoa don", "so hd", "so ct", "ma bill", "ma giao dich", "ma don", "ma don hang"],
        "pay_ts": ["thoi gian", "thoi gian thu", "ngay thu", "thoi diem", "ngay gio thu"],
        "pay_method": ["phuong thuc thanh toan", "phuong thuc", "pttt", "httt", "hinh thuc"],
        "pay_amount": ["gia tri", "tien", "so tien thu", "so tien"],
        "note": ["dien giai", "ghi chu"],
    },
    "imports": {
        "import_id": ["ma nhap hang", "ma don nhap", "ma phieu nhap", "so phieu"],
        "import_date": ["thoi gian", "ngay nhap", "ngay nhap kho"],
        "supplier_id": ["ma ncc", "ma nha cung cap"],
        "supplier_name": ["nha cung cap", "ten ncc"],
        "import_total": ["can tra ncc", "tong gia tri nhap", "tong tien"],
        "import_status": ["trang thai", "tinh trang"],
        "note": ["ghi chu", "dien giai"],
        "branch_id": ["ma chi nhanh"],
    },
    "import_lines": {
        "import_id": ["ma nhap hang", "ma don nhap", "ma phieu nhap", "so phieu"],
        "line_no": ["stt", "so thu tu"],
        "product_id": _PRODUCT_ID,
        "product_name": ["ten mat hang", "product", "ten hang", "ten san pham", "san pham", "hang"],
        "unit": ["dvt", "dvt nhap", "don vi tinh", "don vi"],
        "qty": ["so luong", "sl nhap", "sl"],
        "qty_base": ["so luong nhap", "sl nhap quy doi", "so luong dvt co ban"],
        "unit_cost": ["don gia", "gia nhap", "don gia nhap"],
        "line_amount": ["thanh tien"],
        "lot": ["lo", "ma lo", "so lo"],
        "expiry": ["han su dung", "hsd"],
        "supplier_name": ["nha cung cap"],
        "supplier_id": ["ma ncc", "ma nha cung cap"],
        "import_date": ["ngay nhap", "thoi gian"],
        "note": ["ghi chu", "noi dung", "mo ta"],
    },
    "stock": {
        "product_id": _PRODUCT_ID,
        "product_name": ["ten hang", "hang hoa", "product", "ten san pham", "san pham"],
        "base_unit": ["dvt", "don vi tinh", "don vi"],
        "stock_qty": ["ton cuoi ky", "ton cuoi", "ton thuc", "ton kho", "ton"],
    },
    "lots": {
        "import_id": ["ma nhap hang", "ma phieu nhap", "ma don nhap"],
        "product_id": _PRODUCT_ID,
        "lot": ["lo", "ma lo", "so lo"],
        "expiry": ["han su dung", "hsd"],
        "qty_base": ["so luong dvt co ban", "sl nhap dvt co ban", "sl nhap quy doi", "so luong nhap"],
        "unit_cost_base": ["don gia nhap"],
    },
    "lot_sales": {
        "order_id": _ORDER_ID,
        "line_no": ["stt", "no", "so thu tu", "tt dong"],
        "lot": ["lo", "ma lo", "so lo"],
        "qty_base": ["so luong dvt co ban", "so luong", "sl quy ra le", "sl quy doi"],
        "return_qty_base": ["so luong tra dvt co ban", "so luong tra", "sl tra dvt co ban", "sl tra quy doi", "sl tra"],
    },
    "prices": {
        "product_id": ["ma san pham", "ma hang", "ma hang hoa", "ma sp"],
        "product_name": ["ten hang", "san pham", "ten san pham", "hang"],
        "effective_date": ["ngay ap dung"],
        "new_price": ["gia moi", "gia ban le", "gia ban"],
        "old_price": ["gia cu"],
    },
    "deliveries": {
        "delivery_date": ["ngay giao hang", "ngay cho", "ngay giao"],
        "order_id": _ORDER_ID,
        "delivery_no": ["lan giao", "luot giao", "dot giao"],
        "product_name": ["ten hang hoa", "ten hang", "san pham"],
        "base_unit": ["don vi tinh", "dv goc", "dvt"],
        "qty_base": ["so luong giao", "sl thuc giao"],
        "plate": ["bien so xe"],
        "driver": ["nguoi giao hang", "nguoi cho", "tai xe"],
    },
    "debt_terms": {
        "order_id": _ORDER_ID,
        "credit_days": ["so ngay duoc no", "han no ngay", "so ngay no"],
        "due_date": ["han thanh toan", "han tra"],
    },
    "expenses": {
        "expense_date": ["ngay chi", "ngay"],
        "category": ["muc", "khoan muc", "loai chi"],
        "amount": ["so tien", "tien", "so tien chi"],
        "note": ["ghi chu"],
    },
    "drugs": {
        "product_id": _PRODUCT_ID,
        "active_ingredient": ["hoat chat", "thanh phan chinh", "thanh phan"],
        "is_rx": ["thuoc ke don", "ke don", "ban theo don"],
    },
    "returns": {
        "return_id": ["ma phieu tra"],
        "order_id": _ORDER_ID,
        "return_ts": ["ngay gio tra", "thoi gian tra", "ngay tra"],
        "reason": ["nguyen nhan", "ly do"],
        "refund_amount": ["tien hoan tra", "so tien hoan"],
        "refund_method": ["cach hoan tien"],
    },
    "ledger": {
        "txn_id": ["ma giao dich kho"],
        "product_id": _PRODUCT_ID,
        "ts": ["ngay gio phat sinh"],
        "txn_type": ["loai giao dich"],
        "qty_base": ["sl quy doi"],
        "doc_type": ["kieu chung tu"],
        "doc_id": ["ma chung tu"],
        "balance": ["ton cuoi"],
        "branch_id": ["ma chi nhanh"],
    },
    "employees": {
        "employee_id": ["ma nhan vien", "ma nv"],
        "employee_name": ["ten goi", "ten nhan vien", "ho ten", "ten"],
        "role": ["chuc vu"],
        "start_date": ["ngay nhan viec"],
        "end_date": ["ngay thoi viec"],
    },
    "suppliers": {
        "supplier_id": ["ma nha cung cap", "ma ncc"],
        "supplier_name": ["ten goi", "ten nha cung cap", "ten ncc", "ten"],
        "phone": ["so dien thoai", "dien thoai"],
        "address": ["dia chi lien he", "dia chi"],
    },
    "tables": {
        "order_id": _ORDER_ID,
        "table_name": ["phong ban", "ban", "so ban"],
        "area": ["khu vuc"],
        "guests": ["so khach"],
    },
    "branches": {},
    "other": {},
}

# README role phrase (normalized) -> role ; checked by regex search, first match wins
DESC_ROLES: list[tuple[str, str]] = [
    (r"cot trong", "_empty"),
    (r"^ma don", "order_id"),
    (r"^ma hang|^ma san pham", "product_id"),
    (r"^ma khach", "customer_id"),
    (r"^ma phieu nhap", "import_id"),
    (r"^ma phieu thu", "payment_id"),
    (r"^ma nha cung cap", "supplier_id"),
    (r"^ma nhan vien", "employee_id"),
    (r"^ten hang|^ten mon|^ten san pham", "product_name"),
    (r"^ten khach", "customer_name"),
    (r"^ten$", "_name"),
    (r"^so luong ban lay tu lo", "qty_base"),
    (r"^so luong khach tra lai", "return_qty_base"),
    (r"^so luong nhap .*co ban", "qty_base"),
    (r"^so luong da doi ra don vi co ban", "qty_base"),
    (r"^so luong nhap", "qty"),
    (r"^so luong", "qty"),
    (r"^so thu tu dong", "line_no"),
    (r"^so ngay duoc no", "credit_days"),
    (r"^so dien thoai", "phone"),
    (r"^so lo", "lot"),
    (r"^so khach", "guests"),
    (r"^so tien", "pay_amount"),
    (r"^don vi lon", "unit"),
    (r"^don vi nhap", "unit"),
    (r"^don vi co ban", "base_unit"),
    (r"^don vi tinh", "unit"),
    (r"^don gia", "unit_price"),
    (r"^he so", "factor"),
    (r"^trang thai don", "status"),
    (r"^trang thai phieu nhap", "import_status"),
    (r"^ngay ban", "order_date"),
    (r"^ngay nhap", "import_date"),
    (r"^ngay giao", "delivery_date"),
    (r"^ngay bat dau ap dung", "effective_date"),
    (r"^ngay tao", "_created"),
    (r"^thoi diem dat don", "order_ts"),
    (r"^thoi diem thu", "pay_ts"),
    (r"^gio dat don", "order_time"),
    (r"^gia ban ap dung", "new_price"),
    (r"^gia truoc lan doi", "old_price"),
    (r"^gia nhap mot don vi", "unit_cost"),
    (r"^gia ban hien tai", "price"),
    (r"^gia von", "cost"),
    (r"^giam gia", "discount"),
    (r"^tien nhap cua ca dong", "line_amount"),
    (r"^tong tien phieu nhap", "import_total"),
    (r"^thanh tien sau giam", "line_amount"),
    (r"^tong tien hang|^tien hang", "goods_amount"),
    (r"^tong tien don|^so khach phai tra", "total_payable"),
    (r"^da thanh toan", "paid_amount"),
    (r"^so khach con no|^con no", "debt_amount"),
    (r"^hinh thuc thanh toan", "payment_method"),
    (r"^kenh ban", "channel"),
    (r"^nhom hang", "group_name"),
    (r"^nhom khach", "customer_group"),
    (r"^dia chi", "address"),
    (r"^han su dung", "expiry"),
    (r"^han thanh toan", "due_date"),
    (r"^tai xe", "driver"),
    (r"^bien so", "plate"),
    (r"^dot giao", "delivery_no"),
    (r"^hoat chat", "active_ingredient"),
    (r"^thuoc ke don", "is_rx"),
    (r"^ton kho", "stock_qty"),
    (r"^nha cung cap", "supplier_name"),
    (r"^ghi chu", "note"),
    (r"^ban$", "table_name"),
    (r"^khu vuc", "area"),
    (r"^ma nhan vien ban", "employee_id"),
]

# role aliases when a desc-role does not exist under a kind's role set
DESC_ROLE_ALIASES = {
    ("conv", "factor"): "factor",
    ("lines", "discount"): "line_discount",
    ("orders", "discount"): "order_discount",
    ("products", "base_unit"): "base_unit",
    ("import_lines", "unit_price"): "unit_cost",
    ("import_lines", "line_amount"): "line_amount",
    ("lines", "price"): "unit_price",
    ("stock", "base_unit"): "base_unit",
    ("deliveries", "base_unit"): "base_unit",
    ("deliveries", "qty_base"): "qty_base",
    ("prices", "product_name"): "product_name",
    ("expenses", "pay_amount"): "amount",
    ("lines", "cost"): "cost_unit",
    ("payments", "payment_method"): "pay_method",
    ("lots", "import_id"): "import_id",
    ("conv", "unit_price"): "unit_price",
}

ID_PREFIX_ROLE = {  # dominant code prefix of a column's values -> role (strong signal)
    "ORD": "order_id", "HD": "order_id", "SP": "product_id", "KH": "customer_id", "PN": "import_id",
    "NCC": "supplier_id", "PAY": "payment_id", "PT": "payment_id", "NV": "employee_id", "TH": "return_id",
    "MV": "txn_id",
}

WALKIN_NAMES = {"khach le", "kl", "le", "khach vang lai", "vang lai", "khach", "khachle", "k l", "-", "khach le "}

# status normalization: checked in order on accent-stripped lowercase text
STATUS_RULES: list[tuple[str, str]] = [
    (r"\bhuy\b|cancel|khong giao duoc|that bai|fail|tu choi|bom hang", "huy"),
    (r"tra hang|tra lai|hoan hang|hoan tra|doi tra|return|refund|tra ve", "tra_hang"),
    (r"^dang|\bdang giao|\bdang van|cho giao|cho lay|^cho$|shipping|van chuyen|pending|processing|in transit", "dang_giao"),
    (r"hoan thanh|xong|da lay|completed|complete|thanh cong|^ok$|da giao|done|success|da thanh toan|hoan tat|delivered|paid|da ban", "hoan_thanh"),
]

PAYMENT_RULES: list[tuple[str, str]] = [
    (r"\bcod\b|thu ho|giao hang thu tien", "cod"),
    (r"tien mat|^cash$|^tm$", "tien_mat"),
    (r"chuyen khoan|transfer|^ck$|bank|ngan hang", "chuyen_khoan"),
    (r"vi dien tu|ewallet|e wallet|momo|zalopay|zalo pay|vnpay|shopeepay|^vi$", "vi_dien_tu"),
    (r"ghi no|^debt$|cong no|no$|tra sau|mua chiu", "ghi_no"),
    (r"the|card|pos|visa", "the"),
]


def norm_name_set(names):
    return {n for n in names}


def match_status(text: str) -> str | None:
    for pat, val in STATUS_RULES:
        if re.search(pat, text):
            return val
    return None


def match_payment(text: str) -> str | None:
    for pat, val in PAYMENT_RULES:
        if re.search(pat, text):
            return val
    return None


# ---------------------------------------------------------------- strict-eval vocabulary mask
def apply_vocab_mask(mask: dict) -> None:
    """Remove column names / file keywords / whole kinds learned only from held-out business types.

    Used for honest evaluation on 'unseen business type' groups: those tables then fall back to
    raw tables + value heuristics, as a really new business type would.
    """
    names = set(mask.get("names", []))
    keywords = set(mask.get("keywords", []))
    kinds = set(mask.get("kinds", []))
    for kind in list(ROLE_NAMES):
        if kind in kinds:
            ROLE_NAMES[kind] = {}
            continue
        for role, lst in ROLE_NAMES[kind].items():
            ROLE_NAMES[kind][role] = [n for n in lst if n not in names]
    for i, (kind, kws) in enumerate(KIND_NAME_KEYWORDS):
        KIND_NAME_KEYWORDS[i] = (kind, [] if kind in kinds else [k for k in kws if k not in keywords])


def _load_mask_from_env() -> None:
    import json
    import os
    p = os.environ.get("DATAMATE_VOCAB_MASK")
    if p and os.path.exists(p):
        apply_vocab_mask(json.load(open(p, encoding="utf-8")))


_load_mask_from_env()
