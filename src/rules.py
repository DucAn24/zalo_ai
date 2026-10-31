"""Facts extracted from the split's rulebook.md at runtime (never hard-coded per business type)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .dates import DateRules, parse_date_rules


@dataclass
class Rules:
    text: str = ""
    non_item_names: list[str] = field(default_factory=list)   # product rows that are not "mặt hàng"
    penalty_hint: float | None = None                          # penalty for a wrong answer stated in §9
    date: DateRules = field(default_factory=DateRules)
    prompt_text: str = ""                                      # compact version used in the LLM prompt


def compact_rulebook(text: str) -> str:
    """Same content, fewer tokens: no bold markers, no table rules/pipes."""
    out = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            if out and out[-1] != "":
                out.append("")
            continue
        if re.fullmatch(r"\|?[\s:|-]+\|?", s):
            continue
        if s.startswith("|") and s.endswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if cells and cells[0] in ("Luật", "Cách nói", "Cách ghi", "Từ", "Cách ghi trong file", "type") and len(out) and out[-1].startswith("#"):
                continue
            s = "- " + cells[0] + (": " + " | ".join(c for c in cells[1:] if c) if len(cells) > 1 else "")
        out.append(s.replace("**", ""))
    return "\n".join(out)


# "Dòng **Phí phục vụ** không phải mặt hàng"  /  "**Phí ship** không tính là mặt hàng"
_BOLD_RE = re.compile(r"\*\*([^*\n]{2,60})\*\*")
_NOT_ITEM_RE = re.compile(
    r"^[^|.;]{0,40}?không\s+(?:phải|tính\s+là|là)\s+(?:một\s+)?(?:mặt hàng|món|sản phẩm|hàng)\b", re.I)
_PENALTY_RE = re.compile(r"sai\s*\*{0,2}\s*[−\-–]\s*(\d+(?:[.,]\d+)?)", re.I)


def parse_rules(rulebook_text: str, max_chars: int = 30000) -> Rules:
    t = rulebook_text or ""
    r = Rules(text=t[:max_chars], date=parse_date_rules(t), prompt_text=compact_rulebook(t[:max_chars]))
    seen = set()
    for line in t.splitlines():
        for m in _BOLD_RE.finditer(line):          # finditer pairs the ** markers left to right
            if _NOT_ITEM_RE.match(line[m.end():m.end() + 60]):
                n = m.group(1).strip()
                if n.lower() not in seen:
                    seen.add(n.lower())
                    r.non_item_names.append(n)
    m = _PENALTY_RE.search(t)
    if m:
        r.penalty_hint = float(m.group(1).replace(",", "."))
    return r
