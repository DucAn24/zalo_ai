"""Answer matching following the competition spec, and the Penalized Accuracy score."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Optional

from .textnorm import answer_norm

ANSWER_TYPES = {"number", "percent", "string", "date", "boolean", "list", "table", "unanswerable"}
_DATE_RE = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")


def _is_num(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and not (isinstance(x, float) and math.isnan(x))


def num_eq(a: Any, b: Any) -> bool:
    return _is_num(a) and _is_num(b) and math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-6)


def _alias_list(alias: Any) -> list[str]:
    if alias is None:
        return []
    if isinstance(alias, str):
        return [alias]
    out = []
    for a in alias:
        if isinstance(a, (list, tuple)):
            out.extend(str(x) for x in a)
        elif a is not None:
            out.append(str(a))
    return out


def str_eq(pred: Any, gold: Any, alias: Any = None) -> bool:
    if not isinstance(pred, str) or gold is None:
        return False
    p = answer_norm(pred)
    return p == answer_norm(str(gold)) or any(p == answer_norm(a) for a in _alias_list(alias))


def value_eq(pred: Any, gold: Any, alias: Any = None) -> bool:
    if _is_num(gold):
        return num_eq(pred, gold)
    if isinstance(gold, bool):
        return isinstance(pred, bool) and pred == gold
    if isinstance(gold, str):
        return str_eq(pred, gold, alias)
    if gold is None:
        return pred is None
    return pred == gold


def _table_eq(pred: Any, gold: dict, alias: Any) -> bool:
    if not isinstance(pred, dict) or not isinstance(pred.get("columns"), list) or not isinstance(pred.get("rows"), list):
        return False
    gc, gr = gold["columns"], gold["rows"]
    pc, pr = pred["columns"], pred["rows"]
    if len(pc) != len(gc) or len(pr) != len(gr):
        return False
    if any(not isinstance(r, list) or len(r) != len(pc) for r in pr):
        return False
    gn = [answer_norm(str(c)) for c in gc]
    pn = [answer_norm(str(c)) for c in pc]
    if sorted(gn) == sorted(pn) and len(set(gn)) == len(gn):
        order = [pn.index(c) for c in gn]          # compare columns by name
    else:
        order = list(range(len(gc)))               # fall back to position
    rows = [[r[i] for i in order] for r in pr]
    alias = alias or []
    used = [False] * len(rows)
    for gi, g in enumerate(gr):
        row_alias = alias[gi] if gi < len(alias) else None
        hit = False
        for pi, p in enumerate(rows):
            if used[pi]:
                continue
            if all(value_eq(p[j], g[j], row_alias if j == 0 else None) for j in range(len(g))):
                used[pi] = hit = True
                break
        if not hit:
            return False
    return True


def is_correct(pred: Optional[dict], gold: dict) -> Optional[bool]:
    """True / False, or None for abstain (missing or type 'abstain')."""
    if pred is None or pred.get("type") in (None, "abstain"):
        return None
    pt, gt = pred.get("type"), gold.get("type")
    if pt != gt:
        return False
    if gt == "unanswerable":
        return True
    p, g, alias = pred.get("answer"), gold.get("answer"), gold.get("alias")
    if gt in ("number", "percent"):
        return num_eq(p, g)
    if gt == "date":
        return isinstance(p, str) and bool(_DATE_RE.match(p)) and p == g
    if gt == "boolean":
        return isinstance(p, bool) and p == g
    if gt == "string":
        return str_eq(p, g, alias)
    if gt == "list":
        if not isinstance(p, list) or len(p) != len(g):
            return False
        alias = alias or []
        return all(value_eq(p[i], g[i], alias[i] if i < len(alias) else None) for i in range(len(g)))
    if gt == "table":
        return _table_eq(p, g, alias)
    return False


@dataclass
class Score:
    n: int = 0
    correct: int = 0
    wrong: int = 0
    abstain: int = 0

    def add(self, ok: Optional[bool]):
        self.n += 1
        if ok is None:
            self.abstain += 1
        elif ok:
            self.correct += 1
        else:
            self.wrong += 1

    def pa(self, penalty: float = 1.0) -> float:
        return (self.correct - penalty * self.wrong) / self.n if self.n else 0.0

    def fmt(self, penalty: float = 1.0) -> str:
        if not self.n:
            return "n=0"
        return (f"n={self.n:4d} acc={self.correct / self.n:6.1%} wrong={self.wrong / self.n:6.1%} "
                f"abst={self.abstain / self.n:6.1%} PA={self.pa(penalty):+.3f}")
