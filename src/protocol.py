"""LLM output protocol: parse the tagged answer and expand period placeholders in the SQL.

Expected model output:
    TYPE: number|percent|string|date|boolean|list|table|unanswerable
    PERIODS: P1 = month:2025-10 ; P2 = prev(P1)
    DECIMALS: 0                (optional, number only)
    COLUMNS: khach_hang, so_tien_no   (table only)
    REASON: ...                (unanswerable only)
    SQL:
    SELECT ... WHERE {P1:order_date}
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .dates import DateRules, DateResolver, Period, PeriodError, shift_clause

VALID_TYPES = {"number", "percent", "string", "date", "boolean", "list", "table", "unanswerable"}
_KEYS = ("TYPE", "PERIODS", "DECIMALS", "COLUMNS", "REASON", "SQL")
_KEY_RE = re.compile(r"^\s*(TYPE|PERIODS|DECIMALS|COLUMNS|REASON|SQL)\s*:\s*(.*)$", re.I)
_PERIOD_RE = re.compile(r"\b(P\d+)\s*=\s*([^;\n]+)")
_FENCE_RE = re.compile(r"```(?:sql|SQL)?\s*\n?(.*?)```", re.S)


class ProtocolError(ValueError):
    pass


@dataclass
class Draft:
    type: Optional[str] = None
    periods: dict[str, str] = field(default_factory=dict)
    decimals: Optional[int] = None
    columns: list[str] = field(default_factory=list)
    reason: str = ""
    sql: str = ""
    raw: str = ""


def parse_response(text: str) -> Draft:
    d = Draft(raw=text)
    cur, buf = None, {k: [] for k in _KEYS}
    for line in text.splitlines():
        m = _KEY_RE.match(line)
        if m and (cur != "SQL" or m.group(1).upper() in ("TYPE", "PERIODS")):
            cur = m.group(1).upper()
            buf[cur].append(m.group(2))
            continue
        if cur:
            buf[cur].append(line)
    t = " ".join(buf["TYPE"]).strip().lower()
    t = re.split(r"[\s,;|/]", t)[0] if t else ""
    d.type = t if t in VALID_TYPES else None
    for m in _PERIOD_RE.finditer("\n".join(buf["PERIODS"])):
        d.periods[m.group(1)] = m.group(2).strip().strip("`'\"")
    dec = " ".join(buf["DECIMALS"]).strip()
    if re.fullmatch(r"\d", dec):
        d.decimals = int(dec)
    d.columns = [c.strip() for c in " ".join(buf["COLUMNS"]).replace(";", ",").split(",") if c.strip()]
    d.reason = " ".join(x.strip() for x in buf["REASON"]).strip()
    sql = "\n".join(buf["SQL"]).strip()
    fence = _FENCE_RE.search(sql) or (_FENCE_RE.search(text) if not sql else None)
    if fence:
        sql = fence.group(1).strip()
    d.sql = sql.strip().rstrip(";").strip()
    if d.type is None:
        raise ProtocolError("thiếu hoặc sai dòng TYPE (number|percent|string|date|boolean|list|table|unanswerable)")
    if d.type != "unanswerable" and not d.sql:
        raise ProtocolError("thiếu phần SQL")
    return d


def resolve_periods(periods: dict[str, str], resolver: DateResolver) -> dict[str, Period]:
    """Resolve P-expressions in order; later ones may reference earlier ones (prev(P1))."""
    exprs: dict[str, str] = {}
    out: dict[str, Period] = {}
    for name in sorted(periods, key=lambda s: int(s[1:])):
        e = periods[name]
        for ref in sorted(exprs, key=lambda s: -len(s)):
            e = re.sub(rf"\b{ref}\b", exprs[ref], e)
        exprs[name] = e
        try:
            out[name] = resolver.resolve(e)
        except (PeriodError, ValueError, KeyError) as ex:
            raise ProtocolError(f"kỳ {name} = '{periods[name]}' không hợp lệ: {ex}")
    return out


_COND_RE = re.compile(r"\{(P\d+):([A-Za-z_][\w.]*)\}")
_LIT_RE = re.compile(r"\{(P\d+)\.(start|end|last|days)\}")
_SHIFT_RE = re.compile(r"\{SHIFT:(\w+):([A-Za-z_][\w.]*)\}")
_DATE_LITERAL_RE = re.compile(r"'\d{4}-\d{2}-\d{2}'|\bDATE\s*'|\bINTERVAL\b|current_date|today\(\)|\bnow\(\)", re.I)


def substitute(sql: str, periods: dict[str, Period], rules: DateRules) -> str:
    if _DATE_LITERAL_RE.search(sql):
        raise ProtocolError("không được viết ngày trực tiếp hoặc dùng current_date/INTERVAL; khai báo PERIODS và dùng "
                            "{P1:cột_ngày}, {P1.start}, {P1.end}, {P1.last}")

    def need(name: str) -> Period:
        if name not in periods:
            raise ProtocolError(f"SQL dùng {{{name}}} nhưng PERIODS chưa khai báo {name}")
        return periods[name]

    def cond(m):
        return need(m.group(1)).sql(m.group(2))

    def lit(m):
        p = need(m.group(1))
        a = m.group(2)
        if a == "days":
            return str(p.days)
        d = {"start": p.start, "end": p.end, "last": p.last_day}[a]
        return f"DATE '{d.isoformat()}'"

    def shift(m):
        if m.group(1) not in rules.shifts:
            raise ProtocolError(f"ca '{m.group(1)}' không có trong rulebook (có: {', '.join(rules.shifts)})")
        return shift_clause(m.group(2), m.group(1), rules)

    out = _COND_RE.sub(cond, sql)
    out = _LIT_RE.sub(lit, out)
    out = _SHIFT_RE.sub(shift, out)
    left = re.findall(r"\{[^{}]{1,40}\}", out)
    if left:
        raise ProtocolError(f"placeholder không hợp lệ trong SQL: {left[0]}")
    return out
