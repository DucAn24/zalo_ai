"""Parse a business README.md (may be sparse or missing)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .parse import parse_date, parse_number
from .textnorm import nfc


@dataclass
class ReadmeInfo:
    text: str = ""
    data_end: Optional[object] = None                    # dt.date
    columns: dict[tuple[str, str], dict[str, str]] = field(default_factory=dict)  # (file, sheet) -> {col: desc}
    conversions: list[dict] = field(default_factory=list)  # {product_name, unit, factor, base_unit}
    conventions: list[str] = field(default_factory=list)
    description: str = ""


_SECTION_RE = re.compile(r"^##\s+Cột trong\s+`([^`]+)`(?:\s*,\s*sheet\s+`([^`]+)`)?", re.I)
_COL_RE = re.compile(r"^-\s+\*\*(.+?)\*\*\s*:\s*(.+)$")
_CONV_RE = re.compile(r"^\s*-\s+(.+):\s*1\s+(.+?)\s*=\s*([\d.,]+)\s+(.+?)\s*$")
_END_RE = re.compile(r"có đến hết\s+(\d{1,2}/\d{1,2}/\d{4})", re.I)


def parse_readme(text: str) -> ReadmeInfo:
    info = ReadmeInfo(text=nfc(text or ""))
    if not text:
        return info
    lines = info.text.splitlines()
    m = _END_RE.search(info.text)
    if m:
        info.data_end = parse_date(m.group(1))
    cur = None
    section = ""
    desc_lines = []
    for ln in lines:
        if ln.startswith("## "):
            section = ln[3:].strip().lower()
            ms = _SECTION_RE.match(ln)
            cur = (ms.group(1).strip(), (ms.group(2) or "").strip()) if ms else None
            if cur is not None:
                info.columns.setdefault(cur, {})
            continue
        if ln.startswith("# "):
            continue
        if not section and ln.strip():
            desc_lines.append(ln.strip())
        mc = _CONV_RE.match(ln)
        if mc and ln.startswith((" ", "\t")):
            f = parse_number(mc.group(3))
            if f:
                info.conversions.append({"product_name": mc.group(1).strip(), "unit": mc.group(2).strip(),
                                         "factor": f, "base_unit": mc.group(4).strip()})
            continue
        if cur is not None:
            mm = _COL_RE.match(ln.strip())
            if mm:
                info.columns[cur][mm.group(1).strip()] = mm.group(2).strip()
                continue
        if section.startswith("quy ước") and ln.strip().startswith("- "):
            info.conventions.append(ln.strip()[2:])
    info.description = " ".join(desc_lines)
    return info
