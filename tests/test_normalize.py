import datetime as dt

from src.parse import parse_date, parse_datetime, parse_number, parse_qty, sheet_period
from src.qnorm import QuestionNormalizer, telex_decode
from src.schema import match_payment, match_status
from src.textnorm import answer_norm, col_norm, fix_mojibake, key_norm, remove_phone


def test_money_formats():
    cases = {"38,000": 38000, "45,000.0000": 45000, "55.000đ": 55000, "35k": 35000, "26078k": 26078000,
             "1tr440": 1440000, "9tr960": 9960000, "16,56tr": 16560000, "1,274tr": 1274000, "1.274tr": 1274000,
             "11.856.000đ": 11856000, "-53.500đ": -53500, "1,200,000": 1200000, "0.124": 0.124, "18.6": 18.6,
             "1tr5": 1500000, "1,5k": 1500, 45000.0: 45000, "": None, "abc": None}
    for s, v in cases.items():
        assert parse_number(s) == v, s


def test_qty_with_unit():
    assert parse_qty("2 thùng") == (2.0, "thùng")
    assert parse_qty("1 bao 25kg") == (1.0, "bao 25kg")
    assert parse_qty("10 m") == (10.0, "m")
    assert parse_qty(3) == (3.0, None)


def test_dates():
    assert parse_date("01/02/2025") == dt.date(2025, 2, 1)
    assert parse_date("1 thg 6 2025") == dt.date(2025, 6, 1)
    assert parse_date(45658) == dt.date(2025, 1, 1)
    assert parse_date("45658") == dt.date(2025, 1, 1)
    assert parse_date("1/1", default_year=2026) == dt.date(2026, 1, 1)
    assert parse_date("2025-01-01 06:03:04") == dt.date(2025, 1, 1)
    assert parse_datetime("2025-01-01 06:03:04") == dt.datetime(2025, 1, 1, 6, 3, 4)


def test_sheet_names():
    assert sheet_period("T01_2025") == (2025, 1)
    assert sheet_period("04.2025") == (2025, 4)
    assert sheet_period("Thang 02 2025") == (2025, 2)
    assert sheet_period("Tháng 01-2025") == (2025, 1)
    assert sheet_period("T02-2026") == (2026, 2)
    assert sheet_period("Sheet1") == (None, None)


def test_text_norms():
    assert answer_norm("Sữa  TH-true MILK (180ml)") == "sữa th true milk 180ml"
    assert key_norm("Lưu Hà An") == key_norm("LUU HA AN")
    assert remove_phone("Đào Dương Giang - 0912 365 003") == "Đào Dương Giang"
    assert remove_phone("Hồ Minh Dương (0933201672)") == "Hồ Minh Dương"
    assert col_norm("Nhóm hàng(3 Cấp)") == "nhom hang 3 cap"
    assert col_norm("SLQuyDoi") == "sl quy doi"
    assert col_norm("MaHoaDon") == "ma hoa don"
    assert fix_mojibake("Danh sĂ¡ch hĂ ng hĂ³a.xlsx") == "Danh sách hàng hóa.xlsx"


def test_status_and_payment():
    for s, v in {"đã lấy": "hoan_thanh", "Đang vận chuyển": "dang_giao", "Đã hủy đơn": "huy", "cancelled": "huy",
                 "Không giao được": "huy", "Đổi trả": "tra_hang", "hàng trả về": "tra_hang", "Hoàn trả": "tra_hang",
                 "ok": "hoan_thanh", "Thành công": "hoan_thanh"}.items():
        from src.textnorm import strip_accents
        assert match_status(strip_accents(s).lower()) == v, s
    assert match_payment("chuyen khoan") == "chuyen_khoan"
    assert match_payment("cod") == "cod"
    assert match_payment("tien mat") == "tien_mat"


def test_telex():
    assert telex_decode("dduwowcj") == "được"
    assert telex_decode("toongr") == "tổng"
    assert telex_decode("thangs") == "tháng"
    qn = QuestionNormalizer(["được tổng tháng"])
    assert qn.normalize("toongr dthu thangs nay") == "tổng dthu tháng nay"
    assert qn.normalize("Acemuc Kids plus") == "Acemuc Kids plus"   # not in vocab -> untouched
