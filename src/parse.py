"""Parsing of dirty cell values: money, numbers, quantities, dates, sheet names."""
from __future__ import annotations

import datetime as dt
import math
import re
from decimal import Decimal
from typing import Any, Optional

from .textnorm import strip_accents

EXCEL_EPOCH = dt.date(1899, 12, 30)
SERIAL_MIN, SERIAL_MAX = 30000, 60000  # ~1982 .. ~2064


def is_blank(x: Any) -> bool:
    if x is None:
        return True
    if isinstance(x, float) and math.isnan(x):
        return True
    if isinstance(x, str) and x.strip().lower() in ("", "nan", "none", "null", "nat"):
        return True
    return False


# ---------------------------------------------------------------- numbers
_TR_RE = re.compile(r"^(-?\d+(?:[.,]\d+)?)\s*(tr|triệu|trieu)\s*(\d+)?$")
_K_RE = re.compile(r"^(-?\d+(?:[.,]\d+)?)\s*(k|nghìn|nghin|ngàn|ngan)$")


def _plain_number(s: str) -> Optional[float]:
    """Parse a numeric string with arbitrary thousand/decimal separators."""
    s = s.strip().replace(" ", "").replace(" ", "")
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1]
    if s.startswith("-"):
        neg, s = True, s[1:]
    elif s.startswith("+"):
        s = s[1:]
    if not s or not re.fullmatch(r"[\d.,]+", s) or not re.search(r"\d", s):
        return None
    has_c, has_d = "," in s, "." in s
    if has_c and has_d:
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        th = "." if dec == "," else ","
        s = s.replace(th, "").replace(dec, ".")
    elif has_c or has_d:
        sep = "," if has_c else "."
        parts = s.split(sep)
        if len(parts) > 2:
            s = s.replace(sep, "")
        else:
            # one separator: thousands if exactly 3 digits follow and the head is 1-3 digits
            if len(parts[1]) == 3 and 1 <= len(parts[0]) <= 3 and parts[0] != "0":
                s = s.replace(sep, "")
            else:
                s = s.replace(sep, ".")
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def parse_number(x: Any) -> Optional[float]:
    """Parse money / numeric cells: '38,000', '55.000đ', '35k', '1tr440', '16,56tr', 1.0."""
    if is_blank(x):
        return None
    if isinstance(x, bool):
        return float(x)
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip().lower()
    s = re.sub(r"(vnđ|vnd|đồng|dong|đ|₫)$", "", s).strip()
    s = s.replace(" ", " ")
    v = _plain_number(s)
    if v is not None:
        return v
    s2 = s.replace(" ", "")
    m = _K_RE.match(s2)
    if m:
        h = m.group(1)
        if h.count(",") + h.count(".") == 1 and len(re.split(r"[.,]", h)[1]) != 3:
            return float(Decimal(h.replace(",", ".")) * 1000)
        base = _plain_number(h)
        return None if base is None else base * 1000
    m = _TR_RE.match(s2)
    if m:
        head = m.group(1)
        tail = m.group(3)
        if tail:  # 1tr440 -> 1,440,000 ; 9tr960 -> 9,960,000 ; 1tr5 -> 1,500,000
            base = _plain_number(head.replace(",", "").replace(".", ""))
            if base is None:
                return None
            sign = -1 if base < 0 else 1
            return sign * float((Decimal(int(abs(base))) + Decimal("0." + tail)) * 1_000_000)
        # a single separator inside 'tr' is always decimal: 16,56tr, 3,255tr, 1.274tr
        if head.count(",") + head.count(".") == 1:
            return float(Decimal(head.replace(",", ".")) * 1_000_000)
        base = _plain_number(head)
        return None if base is None else round(base * 1_000_000, 6)
    return None


_QTY_RE = re.compile(r"^\s*(-?\d+(?:[.,]\d+)?)\s*(.*)$")


def parse_qty(x: Any) -> tuple[Optional[float], Optional[str]]:
    """'2 thùng' -> (2, 'thùng'); '1 bao 25kg' -> (1, 'bao 25kg'); 3 -> (3, None)."""
    if is_blank(x):
        return None, None
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        return float(x), None
    s = str(x).strip()
    v = parse_number(s)
    if v is not None:
        return v, None
    m = _QTY_RE.match(s)
    if not m:
        return None, None
    v = _plain_number(m.group(1))
    unit = m.group(2).strip() or None
    return v, unit


# ---------------------------------------------------------------- dates
_DMY_RE = re.compile(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})(?:[ T]+(\d{1,2}):(\d{2})(?::(\d{2}))?)?$")
_YMD_RE = re.compile(r"^(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})(?:[ T]+(\d{1,2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?)?$")
_THG_RE = re.compile(r"^(\d{1,2})\s*(?:thg|tháng|thang|th)\s*(\d{1,2})[\s,/]*(\d{4})?$", re.I)
_DM_RE = re.compile(r"^(\d{1,2})[/\-.](\d{1,2})$")


def _mk(y: int, m: int, d: int, hh=None, mm=None, ss=None):
    if y < 100:
        y += 2000
    try:
        if hh is not None:
            return dt.datetime(y, m, d, int(hh), int(mm), int(ss or 0))
        return dt.date(y, m, d)
    except ValueError:
        return None


def parse_datetime(x: Any, default_year: Optional[int] = None):
    """Return dt.datetime (if a time is present) or dt.date, else None."""
    if is_blank(x):
        return None
    if isinstance(x, dt.datetime):
        return x
    if isinstance(x, dt.date):
        return x
    if hasattr(x, "to_pydatetime"):
        return x.to_pydatetime()
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        if SERIAL_MIN <= x <= SERIAL_MAX:
            days = int(math.floor(x))
            frac = float(x) - days
            base = EXCEL_EPOCH + dt.timedelta(days=days)
            if frac > 1e-9:
                return dt.datetime.combine(base, dt.time()) + dt.timedelta(seconds=round(frac * 86400))
            return base
        return None
    s = str(x).strip()
    if re.fullmatch(r"\d{5}(\.\d+)?", s):
        return parse_datetime(float(s), default_year)
    m = _DMY_RE.match(s)
    if m:
        d, mo, y, hh, mi, ss = m.groups()
        return _mk(int(y), int(mo), int(d), hh, mi, ss)
    m = _YMD_RE.match(s)
    if m:
        y, mo, d, hh, mi, ss = m.groups()
        return _mk(int(y), int(mo), int(d), hh, mi, ss)
    m = _THG_RE.match(s)
    if m:
        d, mo, y = m.groups()
        y = int(y) if y else default_year
        return _mk(y, int(mo), int(d)) if y else None
    m = _DM_RE.match(s)
    if m and default_year:
        d, mo = m.groups()
        return _mk(default_year, int(mo), int(d))
    return None


def parse_date(x: Any, default_year: Optional[int] = None) -> Optional[dt.date]:
    v = parse_datetime(x, default_year)
    if isinstance(v, dt.datetime):
        return v.date()
    return v


def parse_bool(x: Any) -> Optional[bool]:
    if is_blank(x):
        return None
    if isinstance(x, bool):
        return x
    if isinstance(x, (int, float)):
        return bool(x)
    s = strip_accents(str(x)).strip().lower()
    if s in ("true", "1", "x", "co", "yes", "y", "dung", "ke don", "1.0"):
        return True
    if s in ("false", "0", "khong", "no", "n", "sai", "0.0"):
        return False
    return None


# ---------------------------------------------------------------- sheet names
_SHEET_PATTERNS = [
    re.compile(r"(?:^|[^0-9])(\d{1,2})\s*[._\-/ ]\s*(\d{4})(?:$|[^0-9])"),  # T01_2025, 04.2025, Thang 02 2025
    re.compile(r"(?:^|[^0-9])(\d{4})\s*[._\-/ ]\s*(\d{1,2})(?:$|[^0-9])"),  # 2025-01
]


def sheet_period(name: str) -> tuple[Optional[int], Optional[int]]:
    """Extract (year, month) from a sheet name like 'T01_2025', 'Tháng 01-2025', '04.2025'."""
    s = strip_accents(str(name))
    m = _SHEET_PATTERNS[0].search(s)
    if m:
        mo, y = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12:
            return y, mo
    m = _SHEET_PATTERNS[1].search(s)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12:
            return y, mo
    m = re.search(r"(20\d{2})", s)
    if m:
        return int(m.group(1)), None
    return None, None
