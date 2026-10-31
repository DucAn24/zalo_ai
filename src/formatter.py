"""Coerce raw computed values into the exact answer format of each type."""
from __future__ import annotations

import datetime as dt
import math
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional

import numpy as np
import pandas as pd


class FormatError(ValueError):
    pass


def round_half_up(x: float, ndigits: int = 0) -> float:
    q = Decimal(1).scaleb(-ndigits)
    return float(Decimal(repr(float(x))).quantize(q, rounding=ROUND_HALF_UP))


def to_python(x: Any) -> Any:
    if isinstance(x, np.generic):
        return x.item()
    if isinstance(x, pd.Timestamp):
        return x.to_pydatetime()
    if isinstance(x, Decimal):
        return float(x)
    return x


def to_float(x: Any) -> float:
    x = to_python(x)
    if isinstance(x, bool):
        raise FormatError("boolean is not a number")
    if isinstance(x, (int, float)):
        if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
            raise FormatError("NaN/inf")
        return float(x)
    if isinstance(x, str):
        from .parse import parse_number
        v = parse_number(x.replace("%", ""))
        if v is None:
            raise FormatError(f"not a number: {x!r}")
        return v
    raise FormatError(f"not a number: {x!r}")


def fmt_number(x: Any, integer: Optional[bool] = None, ndigits: int = 2) -> int | float:
    """integer=True: money / counts (round half up to int); None: int if integral else 2 decimals."""
    v = to_float(x)
    if integer is True or (integer is None and abs(v - round(v)) < 1e-9):
        return int(round_half_up(v, 0))
    r = round_half_up(v, ndigits)
    return int(r) if r == int(r) else r


def fmt_percent(x: Any, ndigits: int = 2) -> int | float:
    r = round_half_up(to_float(x), ndigits)
    return int(r) if r == int(r) else r


def fmt_date(x: Any, month: bool = False) -> str:
    x = to_python(x)
    if isinstance(x, str):
        from .parse import parse_date
        s = x.strip()
        if month and len(s) == 7 and s[4] == "-":
            return s
        d = parse_date(s)
        if d is None:
            raise FormatError(f"not a date: {x!r}")
        x = d
    if isinstance(x, dt.datetime):
        x = x.date()
    if not isinstance(x, dt.date):
        raise FormatError(f"not a date: {x!r}")
    return x.strftime("%Y-%m") if month else x.isoformat()


def fmt_bool(x: Any) -> bool:
    x = to_python(x)
    if isinstance(x, bool):
        return x
    if isinstance(x, (int, float)) and x in (0, 1):
        return bool(x)
    if isinstance(x, str):
        s = x.strip().lower()
        if s in ("true", "1", "yes", "có", "co", "đúng", "dung"):
            return True
        if s in ("false", "0", "no", "không", "khong", "sai"):
            return False
    raise FormatError(f"not a boolean: {x!r}")


def fmt_scalar(x: Any) -> Any:
    x = to_python(x)
    if x is None:
        return None
    if isinstance(x, bool):
        return x
    if isinstance(x, (int, float)):
        return fmt_number(x)
    if isinstance(x, (dt.date, dt.datetime)):
        return fmt_date(x)
    return str(x).strip()


def fmt_string(x: Any) -> str:
    x = to_python(x)
    if x is None:
        raise FormatError("empty string answer")
    if isinstance(x, (list, tuple)):
        if len(x) != 1:
            raise FormatError("string answer from a list")
        x = x[0]
    s = str(x).strip()
    if not s:
        raise FormatError("empty string answer")
    return s


def fmt_list(x: Any, integer: Optional[bool] = None) -> list:
    x = to_python(x)
    if isinstance(x, pd.DataFrame):
        x = x.iloc[:, 0].tolist() if x.shape[1] == 1 else x.iloc[0].tolist()
    if isinstance(x, (pd.Series, np.ndarray, tuple)):
        x = list(x)
    if not isinstance(x, list):
        x = [x]
    out = []
    for v in x:
        v = to_python(v)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out.append(fmt_number(v, integer))
        else:
            out.append(fmt_scalar(v))
    return out


def fmt_table(x: Any, columns: Optional[list[str]] = None, integer_cols: Optional[set] = None) -> dict:
    if isinstance(x, dict) and "columns" in x and "rows" in x:
        cols, rows = list(x["columns"]), [list(r) for r in x["rows"]]
    elif isinstance(x, pd.DataFrame):
        cols, rows = [str(c) for c in x.columns], x.values.tolist()
    else:
        raise FormatError("table answer needs a DataFrame or {columns, rows}")
    if columns:
        if len(columns) != len(cols):
            raise FormatError("column count mismatch")
        cols = list(columns)
    integer_cols = integer_cols or set()
    out_rows = []
    for r in rows:
        row = []
        for j, v in enumerate(r):
            v = to_python(v)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                row.append(fmt_number(v, True if cols[j] in integer_cols else None))
            else:
                row.append(fmt_scalar(v))
        out_rows.append(row)
    return {"columns": cols, "rows": out_rows}


def format_answer(value: Any, atype: str, *, integer: Optional[bool] = None, month: bool = False,
                  columns: Optional[list[str]] = None) -> dict:
    """Return {'type', 'answer'} or raise FormatError."""
    if atype == "number":
        return {"type": "number", "answer": fmt_number(_scalar(value), integer)}
    if atype == "percent":
        return {"type": "percent", "answer": fmt_percent(_scalar(value))}
    if atype == "date":
        return {"type": "date", "answer": fmt_date(_scalar(value), month)}
    if atype == "boolean":
        return {"type": "boolean", "answer": fmt_bool(_scalar(value))}
    if atype == "string":
        return {"type": "string", "answer": fmt_string(_scalar(value))}
    if atype == "list":
        return {"type": "list", "answer": fmt_list(value, integer)}
    if atype == "table":
        return {"type": "table", "answer": fmt_table(value, columns)}
    if atype == "unanswerable":
        return {"type": "unanswerable", "reason": str(value) if value else "dữ liệu không đủ"}
    raise FormatError(f"unknown type {atype}")


def _scalar(value: Any) -> Any:
    """First cell of a 1x1 result (DataFrame / list / Series) or the value itself."""
    if isinstance(value, pd.DataFrame):
        if value.shape[0] == 0:
            raise FormatError("empty result")
        if value.shape[0] != 1 or value.shape[1] != 1:
            raise FormatError(f"expected a single value, got shape {value.shape}")
        return value.iat[0, 0]
    if isinstance(value, (pd.Series, list, tuple, np.ndarray)):
        if len(value) != 1:
            raise FormatError(f"expected a single value, got {len(value)}")
        return list(value)[0]
    return value
