"""Entity linking: find product / group / customer / employee / channel / ingredient names in a
question (accent-insensitive, longest match first, fuzzy fallback) so the LLM can copy exact values."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from .canon import Business
from .textnorm import key_norm, remove_phone

_BOUND = r"(?<![a-z0-9]){}(?![a-z0-9])"


@dataclass
class Entity:
    kind: str                 # product | group | customer | employee | channel | ingredient | supplier | payment
    value: str                # exact value as stored in the canonical tables
    column: str               # where to filter on it
    extra: str = ""           # e.g. product code
    score: float = 100.0
    fuzzy: bool = False


@dataclass
class _Cand:
    key: str
    kind: str
    value: str
    column: str
    extra: str = ""
    min_fuzzy: float = 101.0   # 101 = exact only


@dataclass
class EntityIndex:
    cands: list[_Cand] = field(default_factory=list)

    @staticmethod
    def build(biz: Business) -> "EntityIndex":
        idx = EntityIndex()
        seen = set()

        def add(key, kind, value, column, extra="", min_fuzzy=101.0):
            if not key or not value or len(key) < 2:
                return
            k = (key, kind, value)
            if k in seen:
                return
            seen.add(k)
            idx.cands.append(_Cand(key, kind, value, column, extra, min_fuzzy))

        t = biz.tables
        p = t.get("products")
        if p is not None:
            for r in p.to_dict("records"):
                name, pid = r.get("product_name"), r.get("product_id")
                if not name:
                    continue
                add(key_norm(name), "product", name, "product_name", pid or "", 92.0)
                if pid:
                    add(key_norm(pid), "product", name, "product_name", pid)
                for al in str(r.get("aliases") or "").split(" | "):
                    add(key_norm(al), "product", name, "product_name", pid or "", 92.0)
                gn = r.get("group_name")
                if gn:
                    add(key_norm(gn), "group", gn, "group_name", "", 94.0)
                ai = r.get("active_ingredient")
                if ai:
                    add(key_norm(ai), "ingredient", ai, "active_ingredient", "", 94.0)
        o = t.get("orders")
        if o is not None:
            if "customer_display" in o:
                for name, cid in o[["customer_display", "customer_id"]].drop_duplicates().itertuples(index=False):
                    if name:
                        add(key_norm(name), "customer", name, "customer_display", cid or "", 93.0)
                    if cid:
                        add(key_norm(cid), "customer", name or cid, "customer_display", cid)
            for col, kind in (("channel", "channel"), ("payment_method_raw", "payment")):
                if col in o:
                    for v in o[col].dropna().unique():
                        add(key_norm(str(v)), kind, str(v), "channel" if kind == "channel" else "payment_method")
            if "employee_id" in o:
                for v in o["employee_id"].dropna().unique():
                    add(key_norm(str(v)), "employee", str(v), "employee_id")
        c = t.get("customers")
        if c is not None:
            for r in c.to_dict("records"):
                nm = r.get("customer_name_clean") or r.get("customer_name")
                if nm:
                    add(key_norm(remove_phone(nm)), "customer", nm if not r.get("customer_id") else nm,
                        "customer_display", r.get("customer_id") or "", 93.0)
        e = t.get("employees")
        if e is not None:
            for r in e.to_dict("records"):
                if r.get("employee_name") and r.get("employee_id"):
                    add(key_norm(r["employee_name"]), "employee", r["employee_id"], "employee_id", r["employee_name"], 94.0)
        s = t.get("suppliers")
        if s is not None:
            for r in s.to_dict("records"):
                if r.get("supplier_name"):
                    add(key_norm(r["supplier_name"]), "supplier", r["supplier_name"], "supplier_name", r.get("supplier_id") or "")
        idx.cands.sort(key=lambda c: -len(c.key))
        return idx

    def find(self, question: str, max_fuzzy: int = 4) -> list[Entity]:
        q = " " + key_norm(question) + " "
        covered = [False] * len(q)
        out: list[Entity] = []
        for c in self.cands:
            for m in re.finditer(_BOUND.format(re.escape(c.key)), q):
                a, b = m.span()
                if any(covered[a:b]):
                    continue
                for i in range(a, b):
                    covered[i] = True
                out.append(Entity(c.kind, c.value, c.column, c.extra))
                break
        # fuzzy fallback on the part of the question not covered by exact matches
        rest = "".join(ch if not covered[i] else " " for i, ch in enumerate(q)).strip()
        fuzzy = []
        if len(rest) >= 6:
            have = {(e.kind, e.value) for e in out}
            for c in self.cands:
                if c.min_fuzzy > 100 or len(c.key) < 6 or (c.kind, c.value) in have:
                    continue
                if len(c.key.split()) < (2 if c.kind == "customer" else 1):
                    continue
                sc = fuzz.partial_ratio(c.key, rest)
                if sc >= c.min_fuzzy:
                    fuzzy.append((sc, c))
            fuzzy.sort(key=lambda x: -x[0])
            used = set()
            for sc, c in fuzzy:
                if (c.kind, c.value) in used or len(used) >= max_fuzzy:
                    continue
                used.add((c.kind, c.value))
                out.append(Entity(c.kind, c.value, c.column, c.extra, sc, True))
        return out


def entities_prompt(ents: list[Entity]) -> str:
    if not ents:
        return ""
    names = {"product": "mặt hàng", "group": "nhóm hàng", "customer": "khách hàng", "employee": "nhân viên",
             "channel": "kênh bán", "ingredient": "hoạt chất", "supplier": "nhà cung cấp", "payment": "hình thức thanh toán"}
    lines = []
    for e in ents:
        extra = f" (mã {e.extra})" if e.extra and e.kind in ("product", "customer", "supplier") else ""
        mark = " [gần đúng]" if e.fuzzy else ""
        lines.append(f"- {names.get(e.kind, e.kind)}: '{e.value}'{extra} → cột {e.column}{mark}")
    return "\n".join(lines)
