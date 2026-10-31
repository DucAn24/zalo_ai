import datetime as dt
import os

import pytest

from src.dates import DateResolver, DateRules, LunarCalendar, parse_date_rules, shift_clause

D = dt.date
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAL = os.path.join(ROOT, "train", "train", "calendar.csv")
RULEBOOK = os.path.join(ROOT, "train", "train", "rulebook.md")


def R(today, **kw):
    cal = LunarCalendar(CAL) if os.path.exists(CAL) else LunarCalendar()
    return DateResolver(today, cal, DateRules(**kw), data_start=D(2025, 1, 1))


def rng(p):
    return p.start, p.end


def test_day_and_yesterday():
    r = R(D(2026, 3, 1))
    assert rng(r.resolve("today")) == (D(2026, 3, 1), D(2026, 3, 2))
    assert rng(r.resolve("yesterday")) == (D(2026, 2, 28), D(2026, 3, 1))


def test_weeks_monday_start():
    r = R(D(2026, 9, 17))  # Thursday
    assert rng(r.resolve("this_week")) == (D(2026, 9, 14), D(2026, 9, 18))
    assert rng(r.resolve("last_week")) == (D(2026, 9, 7), D(2026, 9, 14))
    r = R(D(2026, 9, 14))  # Monday
    assert rng(r.resolve("last_week")) == (D(2026, 9, 7), D(2026, 9, 14))
    r = R(D(2026, 9, 13))  # Sunday
    assert rng(r.resolve("this_week")) == (D(2026, 9, 7), D(2026, 9, 14))


def test_week_start_parameter():
    r = R(D(2026, 9, 17), week_start=6)  # Sunday start
    assert r.resolve("this_week").start == D(2026, 9, 13)


def test_this_month_until_today_and_prev_same_days():
    r = R(D(2026, 3, 31))
    assert rng(r.resolve("this_month")) == (D(2026, 3, 1), D(2026, 4, 1))
    # previous month has no 31st -> until end of February
    assert rng(r.resolve("prev(this_month)")) == (D(2026, 2, 1), D(2026, 3, 1))
    r = R(D(2026, 3, 15))
    assert rng(r.resolve("prev(this_month)")) == (D(2026, 2, 1), D(2026, 2, 16))
    assert rng(r.resolve("last_month")) == (D(2026, 2, 1), D(2026, 3, 1))


def test_month_without_year():
    r = R(D(2026, 5, 10))
    assert r.resolve("month:5").start == D(2026, 5, 1)    # current month -> this year
    assert r.resolve("month:11").start == D(2025, 11, 1)  # after today -> previous year
    assert rng(r.resolve("month:2025-2")) == (D(2025, 2, 1), D(2025, 3, 1))


def test_quarters_years_ndays_range():
    r = R(D(2026, 5, 10))
    assert rng(r.resolve("quarter:2025-Q3")) == (D(2025, 7, 1), D(2025, 10, 1))
    assert rng(r.resolve("quarter:4")) == (D(2025, 10, 1), D(2026, 1, 1))
    assert rng(r.resolve("prev(quarter:2025-1)")) == (D(2024, 10, 1), D(2025, 1, 1))
    assert rng(r.resolve("this_year")) == (D(2026, 1, 1), D(2026, 5, 11))
    assert rng(r.resolve("last_n_days:7")) == (D(2026, 5, 4), D(2026, 5, 11))
    assert rng(r.resolve("range:2026-01-05..2026-01-10")) == (D(2026, 1, 5), D(2026, 1, 11))
    assert rng(r.resolve("until:2026-05-10")) == (D(2025, 1, 1), D(2026, 5, 11))


def test_prev_and_yoy():
    r = R(D(2026, 5, 10))
    assert rng(r.resolve("prev(month:2026-1)")) == (D(2025, 12, 1), D(2026, 1, 1))
    assert rng(r.resolve("yoy(month:2026-2)")) == (D(2025, 2, 1), D(2025, 3, 1))
    assert rng(r.resolve("yoy(this_month)")) == (D(2025, 5, 1), D(2025, 5, 11))
    assert rng(r.resolve("prev(last_n_days:7)")) == (D(2026, 4, 27), D(2026, 5, 4))
    assert rng(r.resolve("prev(yesterday)")) == (D(2026, 5, 8), D(2026, 5, 9))


@pytest.mark.skipif(not os.path.exists(CAL), reason="calendar.csv not available")
def test_tet_window_from_lunar_calendar():
    r = R(D(2026, 6, 1))
    t = r.resolve("tet:2026")
    # Tet 2026 (Binh Ngo): lunar 1/1 = 2026-02-17 -> 23 Chap = 2026-02-10, mung 10 = 2026-02-26
    assert t.start == D(2026, 2, 10)
    assert t.end == D(2026, 2, 27)
    pre = r.resolve("prev(tet:2026)")
    assert pre.end == t.start and pre.days == t.days


@pytest.mark.skipif(not os.path.exists(RULEBOOK), reason="rulebook not available")
def test_rulebook_parsing_train():
    rules = parse_date_rules(open(RULEBOOK, encoding="utf-8").read())
    assert rules.week_start == 0
    assert rules.tet_start == (12, 23) and rules.tet_end == (1, 10)
    assert rules.shifts["ca_sang"] == ("06:00", "13:59")


def test_rulebook_parsing_variants():
    txt = "| Tuần | bắt đầu **Chủ nhật**. |\n| Tết | từ ngày dương của **25 tháng Chạp** đến **hết** ngày dương của **mùng 5 tháng Giêng** |\nca sáng 07:00–12:59"
    rules = parse_date_rules(txt)
    assert rules.week_start == 6
    assert rules.tet_start == (12, 25) and rules.tet_end == (1, 5)
    assert rules.shifts["ca_sang"] == ("07:00", "12:59")


def test_sql_and_shift_clause():
    r = R(D(2026, 5, 10))
    assert r.resolve("month:2026-4").sql("order_date") == \
        "(order_date >= DATE '2026-04-01' AND order_date < DATE '2026-05-01')"
    c = shift_clause("order_ts", "ca_chieu", DateRules())
    assert "840" in c and "1319" in c


def test_bad_expression():
    with pytest.raises(ValueError):
        R(D(2026, 1, 1)).resolve("next_century")


def test_price_effect_and_expiry_windows():
    r = R(D(2026, 5, 20))
    a = r.resolve("days_from:2026-01-30,14")
    b = r.resolve("days_before:2026-01-30,14")
    assert (a.start, a.end) == (D(2026, 1, 30), D(2026, 2, 13))
    assert (b.start, b.end) == (D(2026, 1, 16), D(2026, 1, 30))
    c = r.resolve("ahead:90")   # today .. today+90 inclusive
    assert (c.start, c.end) == (D(2026, 5, 20), D(2026, 8, 19))


def test_prev_of_partial_week_is_the_whole_previous_week():
    r = R(D(2025, 5, 20))                         # Tuesday
    assert rng(r.resolve("prev(this_week)")) == (D(2025, 5, 12), D(2025, 5, 19))
    assert rng(r.resolve("last_week")) == (D(2025, 5, 12), D(2025, 5, 19))
    assert rng(r.resolve("prev(last_week)")) == (D(2025, 5, 5), D(2025, 5, 12))
