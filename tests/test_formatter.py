import datetime as dt

import numpy as np
import pandas as pd
import pytest

from src.formatter import FormatError, fmt_number, fmt_percent, format_answer, round_half_up


def test_number_integral_and_money():
    assert format_answer(6.0, "number")["answer"] == 6
    assert isinstance(format_answer(6.0, "number")["answer"], int)
    assert format_answer(np.int64(48250000), "number")["answer"] == 48250000
    assert format_answer(72709.5, "number", integer=True)["answer"] == 72710   # half up
    assert format_answer(18.567, "number")["answer"] == 18.57
    assert format_answer(pd.DataFrame({"x": [1234.0]}), "number")["answer"] == 1234


def test_percent_sign_and_rounding():
    assert format_answer(-12.4549, "percent")["answer"] == -12.45
    assert fmt_percent(2.005) == 2.01
    assert fmt_percent(7.0) == 7
    assert round_half_up(0.125, 2) == 0.13


def test_date_and_month():
    assert format_answer(dt.date(2025, 5, 10), "date")["answer"] == "2025-05-10"
    assert format_answer(pd.Timestamp("2025-05-10"), "date")["answer"] == "2025-05-10"
    assert format_answer("2025-05", "date", month=True)["answer"] == "2025-05"
    assert format_answer(dt.date(2025, 5, 1), "date", month=True)["answer"] == "2025-05"


def test_boolean():
    assert format_answer(np.bool_(True), "boolean")["answer"] is True
    assert format_answer(0, "boolean")["answer"] is False
    with pytest.raises(FormatError):
        format_answer("maybe", "boolean")


def test_string_and_list_and_table():
    assert format_answer([" Sting dâu 330ml "], "string")["answer"] == "Sting dâu 330ml"
    assert format_answer(pd.DataFrame({"n": ["A", "B"]}), "list")["answer"] == ["A", "B"]
    assert format_answer([8.0, 8.0], "list")["answer"] == [8, 8]
    t = format_answer(pd.DataFrame({"khach_hang": ["Lan"], "so_tien_no": [3200000.0]}), "table")["answer"]
    assert t == {"columns": ["khach_hang", "so_tien_no"], "rows": [["Lan", 3200000]]}


def test_errors():
    with pytest.raises(FormatError):
        format_answer(pd.DataFrame({"x": []}), "number")
    with pytest.raises(FormatError):
        format_answer(pd.DataFrame({"x": [1, 2]}), "number")
    with pytest.raises(FormatError):
        fmt_number(float("nan"))
    with pytest.raises(FormatError):
        fmt_number(True)


def test_unanswerable():
    a = format_answer("kỳ ngoài dữ liệu", "unanswerable")
    assert a == {"type": "unanswerable", "reason": "kỳ ngoài dữ liệu"}
