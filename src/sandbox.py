"""Read-only DuckDB sandbox per business, with statement checks and a timeout."""
from __future__ import annotations

import datetime as dt
import re
import threading
from typing import Optional

import duckdb
import numpy as np
import pandas as pd

from .canon import Business

_FORBIDDEN = re.compile(
    r"\b(attach|detach|copy|install|load|pragma|export|import|create|drop|insert|update|delete|alter|"
    r"call|checkpoint|vacuum|set|reset|use|read_csv\w*|read_parquet|read_json\w*|glob|read_text|read_blob|"
    r"httpfs|sqlite_scan|postgres_scan)\b", re.I)


class SandboxError(RuntimeError):
    pass


def _strip_literals(sql: str) -> str:
    sql = re.sub(r"'([^']|'')*'", "''", sql)
    sql = re.sub(r"--[^\n]*", " ", sql)
    return re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)


def check_sql(sql: str) -> str:
    s = sql.strip().rstrip(";").strip()
    if not s:
        raise SandboxError("empty SQL")
    bare = _strip_literals(s)
    if ";" in bare:
        raise SandboxError("only one statement is allowed")
    if not re.match(r"^\s*(with|select|from|describe|summarize|\()", bare, re.I):
        raise SandboxError("only SELECT / WITH queries are allowed")
    m = _FORBIDDEN.search(bare)
    if m:
        raise SandboxError(f"forbidden keyword: {m.group(0)}")
    return s


def _prepare(df: pd.DataFrame, raw: bool = False) -> pd.DataFrame:
    df = df.copy()
    for c in df.columns:
        s = df[c]
        if s.dtype != object:
            continue
        vals = s.dropna()
        if vals.empty:
            df[c] = s.astype("string")
            continue
        sample = vals.iloc[:2000]
        if all(isinstance(v, dt.datetime) for v in sample):
            df[c] = pd.to_datetime(s, errors="coerce")
        elif all(isinstance(v, dt.date) for v in sample):
            df[c] = pd.to_datetime(s, errors="coerce")
        elif all(isinstance(v, dt.time) for v in sample):
            df[c] = s.map(lambda v: v.strftime("%H:%M:%S") if isinstance(v, dt.time) else None).astype("string")
        elif all(isinstance(v, (bool, np.bool_)) for v in sample):
            df[c] = s.astype("boolean")
        elif all(isinstance(v, (int, float, np.integer, np.floating)) and not isinstance(v, bool) for v in sample):
            df[c] = pd.to_numeric(s, errors="coerce")
        else:
            df[c] = s.map(lambda v: None if v is None or (isinstance(v, float) and np.isnan(v)) else str(v)).astype("string")
    # date-only timestamps -> DATE
    for c in df.columns:
        if str(df[c].dtype).startswith("datetime64"):
            nn = df[c].dropna()
            if len(nn) and (nn == nn.dt.normalize()).all() and (c.endswith("date") or c in ("expiry", "as_of")):
                df[c] = df[c].dt.date
    return df


class Sandbox:
    def __init__(self, biz: Business, extra_sql: Optional[list[str]] = None, max_rows: int = 2000,
                 raw_other_only: bool = False, raw_kinds: Optional[dict] = None):
        self.biz = biz
        self.max_rows = max_rows
        self.con = duckdb.connect(":memory:")
        self.tables: dict[str, list[str]] = {}
        raw = biz.raw
        if raw_other_only:      # raw copies are only a fallback for tables the mapper could not recognize
            kinds = raw_kinds or biz.raw_kinds
            raw = {k: v for k, v in raw.items() if kinds.get(k) == "other"}
        for name, df in list(biz.tables.items()) + list(raw.items()):
            pdf = _prepare(df, raw=name.startswith("raw_"))
            self.con.register("_tmp_df", pdf)
            self.con.execute(f'CREATE TABLE "{name}" AS SELECT * FROM _tmp_df')
            self.con.unregister("_tmp_df")
            self.tables[name] = list(pdf.columns)
        for stmt in extra_sql or []:
            self.con.execute(stmt)
        self.con.execute("SET enable_external_access = false")
        self.con.execute("SET lock_configuration = true")

    def add_views(self, stmts: list[str]):
        for s in stmts:
            self.con.execute(s)

    def run(self, sql: str, timeout: float = 20.0) -> pd.DataFrame:
        sql = check_sql(sql)
        cur = self.con.cursor()
        timer = threading.Timer(timeout, cur.interrupt)
        timer.start()
        try:
            df = cur.execute(sql).df()
        except duckdb.InterruptException as e:
            raise SandboxError(f"timeout after {timeout}s") from e
        except duckdb.Error as e:
            raise SandboxError(str(e).split("\n")[0][:500]) from e
        finally:
            timer.cancel()
            cur.close()
        if len(df) > self.max_rows:
            df = df.head(self.max_rows)
        return df

    def columns(self, table: str) -> list[str]:
        return self.tables.get(table, [])


def describe_all(sb: "Sandbox") -> dict[str, list[tuple[str, str]]]:
    """table/view -> [(column, type)] for everything in the main schema."""
    rows = sb.con.execute("SELECT table_name, column_name, data_type FROM information_schema.columns "
                          "WHERE table_schema = 'main' ORDER BY table_name, ordinal_position").fetchall()
    out: dict[str, list[tuple[str, str]]] = {}
    for t, c, d in rows:
        out.setdefault(t, []).append((c, d))
    return out
