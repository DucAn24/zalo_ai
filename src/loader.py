"""Read every raw file of a business into clean-ish rectangular tables.

Handles: csv / xlsx (all sheets) / sqlite, title + filter rows above the header,
two-level headers, footer total rows, month-per-sheet files, files split into
_1/_2/_2026 parts, mojibake file names.
"""
from __future__ import annotations

import csv
import io
import os
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Optional

import pandas as pd

from .parse import is_blank, parse_datetime, parse_number, sheet_period
from .textnorm import col_norm, fix_mojibake, nfc

_ID_RE = re.compile(r"^[A-Z]{1,5}\d{3,}$")
_FOOTER_RE = re.compile(r"^(tong|cong|ghi chu|total|sum|tong cong)\b")


@dataclass
class RawTable:
    biz: str
    file: str                 # fixed (un-mojibaked) file name
    sheet: str                # sheet / sqlite table name ('' for csv)
    name: str                 # logical table name (after merging parts)
    df: pd.DataFrame
    meta_lines: list[str] = field(default_factory=list)  # title / filter lines above header
    parts: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return f"{self.file}" + (f"[{self.sheet}]" if self.sheet else "")


# ---------------------------------------------------------------- header detection
def _is_valuelike(x: Any) -> bool:
    if not isinstance(x, str):
        return True
    s = x.strip()
    if _ID_RE.match(s):
        return True
    if parse_number(s) is not None:
        return True
    if parse_datetime(s) is not None:
        return True
    return False


def _clean_cell(x: Any) -> Any:
    if isinstance(x, str):
        x = nfc(x).strip()
        return "" if x == "" else x
    if x is None:
        return ""
    return x


def find_header(rows: list[list[Any]], scan: int = 12) -> int:
    best, best_ne = None, -1
    for i, r in enumerate(rows[:scan]):
        ne = [x for x in r if not is_blank(x)]
        if len(ne) < 2:
            continue
        sc = sum(1 for x in ne if not _is_valuelike(x))
        if sc >= 2 and sc >= 0.8 * len(ne) and len(ne) > best_ne:
            best, best_ne = i, len(ne)
    return 0 if best is None else best


def rows_to_df(rows: list[list[Any]]) -> tuple[pd.DataFrame, list[str]]:
    rows = [[_clean_cell(x) for x in r] for r in rows]
    if not rows:
        return pd.DataFrame(), []
    h = find_header(rows)
    meta = [" ".join(str(x) for x in r if not is_blank(x)) for r in rows[:h]]
    meta = [m for m in meta if m]
    header = rows[h]
    width = max(len(header), max((len(r) for r in rows[h + 1:]), default=0))
    cols, seen = [], {}
    for i in range(width):
        c = str(header[i]).strip() if i < len(header) and not is_blank(header[i]) else f"col_{i}"
        if c in seen:
            seen[c] += 1
            c = f"{c}_{seen[c]}"
        else:
            seen[c] = 0
        cols.append(c)
    data = []
    for r in rows[h + 1:]:
        r = list(r) + [""] * (width - len(r))
        ne = [x for x in r if not is_blank(x)]
        if not ne:
            continue
        if len(ne) <= max(2, width // 2):
            first_txt = next((x for x in ne if isinstance(x, str)), "")
            if _FOOTER_RE.match(col_norm(first_txt)):
                continue
        data.append(r[:width])
    df = pd.DataFrame(data, columns=cols, dtype=object)
    # drop fully empty unnamed columns
    for c in list(df.columns):
        if c.startswith("col_") and df[c].map(is_blank).all():
            df = df.drop(columns=c)
    return df, meta


# ---------------------------------------------------------------- readers
def _read_csv_rows(path: str) -> list[list[Any]]:
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "cp1258", "cp1252"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    sample = text[:5000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delim = dialect.delimiter
    except csv.Error:
        delim = ","
    return [list(r) for r in csv.reader(io.StringIO(text), delimiter=delim)]


def _read_xlsx_sheets(path: str) -> list[tuple[str, list[list[Any]]]]:
    try:
        import python_calamine as pc

        wb = pc.CalamineWorkbook.from_path(path)
        out = []
        for s in wb.sheet_names:
            rows = wb.get_sheet_by_name(s).to_python(skip_empty_area=False)
            out.append((s, [list(r) for r in rows]))
        return out
    except ImportError:  # pragma: no cover - fallback
        import openpyxl

        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        return [(s, [list(r) for r in wb[s].iter_rows(values_only=True)]) for s in wb.sheetnames]


def _read_sqlite(path: str) -> list[tuple[str, pd.DataFrame]]:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        names = [r[0] for r in con.execute("select name from sqlite_master where type='table'")]
        return [(t, pd.read_sql(f'select * from "{t}"', con).astype(object)) for t in names]
    finally:
        con.close()


# ---------------------------------------------------------------- business loader
_PART_RE = re.compile(r"(?:[_\- ](?:\d{1,2}|(?:19|20)\d{2}))$")


def logical_name(stem: str) -> str:
    s = stem
    while True:
        s2 = _PART_RE.sub("", s)
        if s2 == s or not s2:
            return s
        s = s2


def _int_or_none(v):
    return int(v) if v is not None else None


def load_business(biz_dir: str) -> tuple[list[RawTable], str]:
    """Return (tables, readme_text)."""
    biz = os.path.basename(os.path.normpath(biz_dir))
    readme = ""
    pieces: list[RawTable] = []
    for fname in sorted(os.listdir(biz_dir)):
        path = os.path.join(biz_dir, fname)
        if not os.path.isfile(path):
            continue
        fixed = fix_mojibake(fname)
        stem, ext = os.path.splitext(fixed)
        ext = ext.lower()
        if ext in (".md", ".txt") and "readme" in fixed.lower():
            readme = open(path, encoding="utf-8", errors="replace").read()
            continue
        if ext in (".csv", ".tsv"):
            df, meta = rows_to_df(_read_csv_rows(path))
            df["_sheet_year"], df["_sheet_month"] = None, None
            pieces.append(RawTable(biz, fixed, "", logical_name(stem), df, meta, [fixed]))
        elif ext in (".xlsx", ".xlsm", ".xls"):
            sheets = _read_xlsx_sheets(path)
            periodic = [s for s, _ in sheets if sheet_period(s)[1] is not None]
            for s, rows in sheets:
                df, meta = rows_to_df(rows)
                if df.empty:
                    continue
                y, mo = sheet_period(s)
                df["_sheet_year"], df["_sheet_month"] = _int_or_none(y), _int_or_none(mo)
                if len(sheets) == 1 or (periodic and s in periodic):
                    lname = logical_name(stem)
                else:
                    lname = s
                pieces.append(RawTable(biz, fixed, s, lname, df, meta, [f"{fixed}[{s}]"]))
        elif ext in (".sqlite", ".db", ".sqlite3"):
            for t, df in _read_sqlite(path):
                df = df.copy()
                df["_sheet_year"], df["_sheet_month"] = None, None
                pieces.append(RawTable(biz, fixed, t, t, df, [], [f"{fixed}[{t}]"]))
    return merge_parts(pieces), readme


def merge_parts(pieces: list[RawTable]) -> list[RawTable]:
    groups: dict[tuple[str, frozenset], list[RawTable]] = {}
    order = []
    for p in pieces:
        key = (p.name, frozenset(c for c in p.df.columns))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(p)
    out, used = [], {}
    for key in order:
        g = groups[key]
        first = g[0]
        cols = list(first.df.columns)
        df = pd.concat([x.df[cols] for x in g], ignore_index=True) if len(g) > 1 else first.df
        name = first.name
        if name in used:
            used[name] += 1
            name = f"{name}_{used[name]}"
        else:
            used[name] = 0
        meta = []
        for x in g:
            for m in x.meta_lines:
                if m not in meta:
                    meta.append(m)
        out.append(RawTable(first.biz, first.file, first.sheet, name, df, meta, [pp for x in g for pp in x.parts]))
    return out
