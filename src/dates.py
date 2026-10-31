"""Deterministic date-period resolution.

The LLM never computes dates. It writes period expressions such as
`last_week`, `month:2025-10`, `prev(this_month)`, `tet:2026`; this module turns
them into half-open [start, end) date ranges using `as_of_date`, the lunar
calendar and rule parameters parsed from the split's rulebook.
"""
from __future__ import annotations

import calendar as _cal
import csv
import datetime as dt
import re
from dataclasses import dataclass, field, replace
from typing import Optional

D = dt.date


@dataclass
class DateRules:
    week_start: int = 0                      # 0 = Monday
    mtd_compare_same_days: bool = True       # 'tháng này' vs previous month: same day numbers
    tet_start: tuple[int, int] = (12, 23)    # lunar (month, day) of the previous lunar year
    tet_end: tuple[int, int] = (1, 10)       # lunar (month, day), inclusive
    shifts: dict[str, tuple[str, str]] = field(default_factory=lambda: {
        "ca_sang": ("06:00", "13:59"), "ca_chieu": ("14:00", "21:59")})
    month_no_year: str = "not_after_today"   # 'tháng M' without year -> this year unless it starts after today
    sources: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Period:
    start: D
    end: D          # exclusive
    kind: str       # day | week | month | mtd | quarter | qtd | year | ytd | ndays | range | until | tet | pre_tet
    label: str = ""
    n: int = 0

    @property
    def last_day(self) -> D:
        return self.end - dt.timedelta(days=1)

    @property
    def days(self) -> int:
        return (self.end - self.start).days

    def sql(self, col: str) -> str:
        return f"({col} >= DATE '{self.start.isoformat()}' AND {col} < DATE '{self.end.isoformat()}')"


# ---------------------------------------------------------------- calendar
class LunarCalendar:
    def __init__(self, path: Optional[str] = None):
        self.solar_to_lunar: dict[D, tuple[int, int, int, bool]] = {}
        self.lunar_to_solar: dict[tuple[int, int, int, bool], D] = {}
        self.holidays: dict[D, str] = {}
        if path:
            self.load(path)

    def load(self, path: str):
        with open(path, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                d = D.fromisoformat(r["date"].strip())
                leap = str(r.get("lunar_leap", "")).strip().lower() in ("true", "1", "yes")
                key = (int(r["lunar_year"]), int(r["lunar_month"]), int(r["lunar_day"]), leap)
                self.solar_to_lunar[d] = key
                self.lunar_to_solar.setdefault(key, d)
                if r.get("holiday"):
                    self.holidays[d] = r["holiday"].strip()

    def solar(self, lunar_year: int, month: int, day: int) -> D:
        key = (lunar_year, month, day, False)
        if key in self.lunar_to_solar:
            return self.lunar_to_solar[key]
        # month of 29 days asked for day 30 -> last available day
        for dd in range(day, 0, -1):
            k = (lunar_year, month, dd, False)
            if k in self.lunar_to_solar:
                return self.lunar_to_solar[k]
        raise KeyError(f"lunar date {lunar_year}-{month}-{day} not in calendar")


# ---------------------------------------------------------------- rulebook parsing
_WEEKDAYS = {"thu hai": 0, "thu ba": 1, "thu tu": 2, "thu nam": 3, "thu sau": 4, "thu bay": 5, "chu nhat": 6}
_LUNAR_MONTHS = {"gieng": 1, "gieng ": 1, "chap": 12, "mot": 11}


def _strip(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.replace("đ", "d").replace("Đ", "D").lower()


def parse_date_rules(rulebook: str) -> DateRules:
    """Extract date parameters from the rulebook text; keep defaults where not found."""
    r = DateRules()
    if not rulebook:
        return r
    t = _strip(rulebook).replace("*", "")
    m = re.search(r"tuan\s*\|\s*bat dau\s+(thu hai|thu ba|thu tu|thu nam|thu sau|thu bay|chu nhat)", t)
    if m:
        r.week_start = _WEEKDAYS[m.group(1)]
        r.sources["week_start"] = m.group(0)
    m = re.search(r"tu ngay duong cua\s+(\d{1,2})\s+thang\s+(chap|gieng|\d{1,2})", t)
    if m:
        mon = _LUNAR_MONTHS.get(m.group(2)) or int(m.group(2))
        r.tet_start = (mon, int(m.group(1)))
        r.sources["tet_start"] = m.group(0)
    m = re.search(r"den\s+het\s+ngay duong cua\s+(?:mung\s+)?(\d{1,2})\s+thang\s+(gieng|chap|\d{1,2})", t)
    if m:
        mon = _LUNAR_MONTHS.get(m.group(2)) or int(m.group(2))
        r.tet_end = (mon, int(m.group(1)))
        r.sources["tet_end"] = m.group(0)
    for key, name in (("ca_sang", "ca sang"), ("ca_chieu", "ca chieu"), ("ca_toi", "ca toi")):
        m = re.search(name + r"\s+(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})", t)
        if m:
            r.shifts[key] = (m.group(1), m.group(2))
            r.sources[key] = m.group(0)
    if re.search(r"thang nay\s*\|[^|\n]*cung so ngay", t):
        r.mtd_compare_same_days = True
        r.sources["mtd"] = "cung so ngay"
    return r


# ---------------------------------------------------------------- helpers
def _month_bounds(y: int, m: int) -> tuple[D, D]:
    start = D(y, m, 1)
    end = D(y + 1, 1, 1) if m == 12 else D(y, m + 1, 1)
    return start, end


def _add_months(y: int, m: int, k: int) -> tuple[int, int]:
    idx = y * 12 + (m - 1) + k
    return idx // 12, idx % 12 + 1


def _shift_year(d: D, k: int) -> D:
    try:
        return d.replace(year=d.year + k)
    except ValueError:  # Feb 29
        return d.replace(year=d.year + k, day=28)


def _week_start(d: D, ws: int) -> D:
    return d - dt.timedelta(days=(d.weekday() - ws) % 7)


# ---------------------------------------------------------------- resolution
class PeriodError(ValueError):
    pass


class DateResolver:
    def __init__(self, as_of: D, cal: Optional[LunarCalendar] = None, rules: Optional[DateRules] = None,
                 data_start: Optional[D] = None):
        self.today = as_of
        self.cal = cal or LunarCalendar()
        self.rules = rules or DateRules()
        self.data_start = data_start or D(2000, 1, 1)

    # -- atoms
    def day(self, d: D, label="") -> Period:
        return Period(d, d + dt.timedelta(days=1), "day", label or d.isoformat())

    def month(self, y: int, m: int) -> Period:
        s, e = _month_bounds(y, m)
        return Period(s, e, "month", f"{y}-{m:02d}")

    def month_no_year(self, m: int) -> Period:
        y = self.today.year
        if D(y, m, 1) > self.today:
            y -= 1
        return self.month(y, m)

    def quarter(self, y: int, q: int) -> Period:
        s = D(y, 3 * (q - 1) + 1, 1)
        e = _month_bounds(*_add_months(y, 3 * (q - 1) + 1, 2))[1]
        return Period(s, e, "quarter", f"{y}-Q{q}")

    def quarter_no_year(self, q: int) -> Period:
        y = self.today.year
        if D(y, 3 * (q - 1) + 1, 1) > self.today:
            y -= 1
        return self.quarter(y, q)

    def year(self, y: int) -> Period:
        return Period(D(y, 1, 1), D(y + 1, 1, 1), "year", str(y))

    def tet(self, y: int) -> Period:
        sm, sd = self.rules.tet_start
        em, ed = self.rules.tet_end
        start = self.cal.solar(y - 1 if sm >= 11 else y, sm, sd)
        end = self.cal.solar(y, em, ed) + dt.timedelta(days=1)
        return Period(start, end, "tet", f"tet-{y}")

    def pre_tet(self, y: int) -> Period:
        t = self.tet(y)
        n = t.days
        return Period(t.start - dt.timedelta(days=n), t.start, "pre_tet", f"pre-tet-{y}", n)

    # -- relative
    def this_week(self) -> Period:
        s = _week_start(self.today, self.rules.week_start)
        return Period(s, self.today + dt.timedelta(days=1), "wtd", "this_week")

    def last_week(self) -> Period:
        s = _week_start(self.today, self.rules.week_start) - dt.timedelta(days=7)
        return Period(s, s + dt.timedelta(days=7), "week", "last_week")

    def this_month(self) -> Period:
        return Period(self.today.replace(day=1), self.today + dt.timedelta(days=1), "mtd", "this_month")

    def last_month(self) -> Period:
        y, m = _add_months(self.today.year, self.today.month, -1)
        return self.month(y, m)

    def last_month_same_days(self) -> Period:
        y, m = _add_months(self.today.year, self.today.month, -1)
        s, e = _month_bounds(y, m)
        last = min(self.today.day, (e - s).days)
        return Period(s, D(y, m, last) + dt.timedelta(days=1), "mtd", "last_month_same_days")

    def this_quarter(self) -> Period:
        q = (self.today.month - 1) // 3 + 1
        return Period(D(self.today.year, 3 * (q - 1) + 1, 1), self.today + dt.timedelta(days=1), "qtd", "this_quarter")

    def last_quarter(self) -> Period:
        q = (self.today.month - 1) // 3 + 1
        y, q = (self.today.year, q - 1) if q > 1 else (self.today.year - 1, 4)
        return self.quarter(y, q)

    def ytd(self) -> Period:
        return Period(D(self.today.year, 1, 1), self.today + dt.timedelta(days=1), "ytd", "this_year")

    def last_n_days(self, n: int) -> Period:
        e = self.today + dt.timedelta(days=1)
        return Period(e - dt.timedelta(days=n), e, "ndays", f"last_{n}_days", n)

    def until(self, d: D) -> Period:
        return Period(self.data_start, d + dt.timedelta(days=1), "until", f"until-{d.isoformat()}")

    def days_from(self, d: D, n: int) -> Period:
        """N days starting at d, d included."""
        return Period(d, d + dt.timedelta(days=n), "ndays", f"{n}_days_from_{d}", n)

    def days_before(self, d: D, n: int) -> Period:
        """The N days right before d (d excluded)."""
        return Period(d - dt.timedelta(days=n), d, "ndays", f"{n}_days_before_{d}", n)

    def ahead(self, n: int) -> Period:
        """From today through the end of day today+n (e.g. 'hết hạn trong N ngày tới')."""
        return Period(self.today, self.today + dt.timedelta(days=n + 1), "range", f"ahead_{n}", n + 1)

    def range(self, a: D, b: D) -> Period:
        if b < a:
            a, b = b, a
        return Period(a, b + dt.timedelta(days=1), "range", f"{a}..{b}", (b - a).days + 1)

    # -- modifiers
    def prev(self, p: Period) -> Period:
        k = p.kind
        if k == "day":
            return self.day(p.start - dt.timedelta(days=1))
        if k in ("week", "wtd"):
            s = p.start - dt.timedelta(days=7)
            return Period(s, s + dt.timedelta(days=p.days if k == "wtd" else 7), k, "prev_" + p.label)
        if k == "month":
            return self.month(*_add_months(p.start.year, p.start.month, -1))
        if k == "mtd":
            y, m = _add_months(p.start.year, p.start.month, -1)
            s, e = _month_bounds(y, m)
            if self.rules.mtd_compare_same_days:
                last = min(p.last_day.day, (e - s).days)
                return Period(s, D(y, m, last) + dt.timedelta(days=1), "mtd", "prev_" + p.label)
            return Period(s, e, "month", "prev_" + p.label)
        if k == "quarter":
            q = (p.start.month - 1) // 3 + 1
            return self.quarter(p.start.year - (q == 1), 4 if q == 1 else q - 1)
        if k == "qtd":
            y, m = _add_months(p.start.year, p.start.month, -3)
            s = D(y, m, 1)
            return Period(s, s + (p.end - p.start), "qtd", "prev_" + p.label)
        if k in ("year", "ytd"):
            return Period(_shift_year(p.start, -1), _shift_year(p.end, -1), k, "prev_" + p.label)
        if k == "tet":
            return self.pre_tet(int(p.label.split("-")[-1]))
        n = p.days
        return Period(p.start - dt.timedelta(days=n), p.start, k, "prev_" + p.label, n)

    def yoy(self, p: Period) -> Period:
        if p.kind == "month":
            return self.month(p.start.year - 1, p.start.month)
        if p.kind == "quarter":
            return self.quarter(p.start.year - 1, (p.start.month - 1) // 3 + 1)
        if p.kind == "tet":
            return self.tet(int(p.label.split("-")[-1]) - 1)
        return Period(_shift_year(p.start, -1), _shift_year(p.end, -1), p.kind, "yoy_" + p.label, p.n)

    # -- expression parser
    _ATOM = re.compile(r"^(\w+)(?::(.+))?$")

    def resolve(self, expr: str) -> Period:
        e = expr.strip().strip("{}[]").strip()
        m = re.match(r"^(prev|yoy|truoc|cung_ky)\((.+)\)$", e)
        if m:
            inner = self.resolve(m.group(2))
            return self.prev(inner) if m.group(1) in ("prev", "truoc") else self.yoy(inner)
        m = self._ATOM.match(e)
        if not m:
            raise PeriodError(f"bad period expression: {expr!r}")
        name, arg = m.group(1).lower(), (m.group(2) or "").strip()
        t = self.today
        simple = {
            "today": lambda: self.day(t, "today"), "hom_nay": lambda: self.day(t, "today"),
            "yesterday": lambda: self.day(t - dt.timedelta(days=1), "yesterday"),
            "hom_qua": lambda: self.day(t - dt.timedelta(days=1), "yesterday"),
            "this_week": self.this_week, "tuan_nay": self.this_week,
            "last_week": self.last_week, "tuan_truoc": self.last_week, "tuan_roi": self.last_week,
            "this_month": self.this_month, "thang_nay": self.this_month,
            "last_month": self.last_month, "thang_truoc": self.last_month,
            "last_month_same_days": self.last_month_same_days,
            "this_quarter": self.this_quarter, "last_quarter": self.last_quarter,
            "this_year": self.ytd, "ytd": self.ytd, "nam_nay": self.ytd,
            "last_year": lambda: self.year(t.year - 1),
            "until_today": lambda: self.until(t),
        }
        if name in simple and not arg:
            return simple[name]()
        if name == "day":
            return self.day(D.fromisoformat(arg))
        if name == "month":
            if re.fullmatch(r"\d{4}-\d{1,2}", arg):
                y, mo = map(int, arg.split("-"))
                return self.month(y, mo)
            return self.month_no_year(int(arg))
        if name == "quarter":
            mq = re.fullmatch(r"(\d{4})-?Q?(\d)", arg, re.I)
            if mq:
                return self.quarter(int(mq.group(1)), int(mq.group(2)))
            return self.quarter_no_year(int(arg.strip("Qq")))
        if name == "year":
            return self.year(int(arg))
        if name in ("last_n_days", "n_days"):
            return self.last_n_days(int(arg))
        if name in ("days_from", "days_before"):
            ds, n = [x.strip() for x in arg.split(",")][:2]
            return (self.days_from if name == "days_from" else self.days_before)(D.fromisoformat(ds), int(n))
        if name == "ahead":
            return self.ahead(int(arg))
        if name == "range":
            a, b = [x.strip() for x in re.split(r"\.\.|,|/", arg) if x.strip()][:2]
            return self.range(D.fromisoformat(a), D.fromisoformat(b))
        if name == "until":
            return self.until(D.fromisoformat(arg) if arg else t)
        if name == "tet":
            return self.tet(int(arg) if arg else t.year)
        if name == "pre_tet":
            return self.pre_tet(int(arg) if arg else t.year)
        if name == "week_of":
            d = D.fromisoformat(arg)
            s = _week_start(d, self.rules.week_start)
            return Period(s, s + dt.timedelta(days=7), "week", f"week-{s}")
        raise PeriodError(f"unknown period: {expr!r}")


def shift_clause(col: str, shift: str, rules: DateRules) -> str:
    """SQL condition on a TIMESTAMP column for a named shift like 'ca_sang'."""
    a, b = rules.shifts[shift]
    ha, ma = map(int, a.split(":"))
    hb, mb = map(int, b.split(":"))
    lo = ha * 60 + ma
    hi = hb * 60 + mb
    expr = f"(hour({col}) * 60 + minute({col}))"
    return f"({expr} >= {lo} AND {expr} <= {hi})"
