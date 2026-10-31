"""Validate the canonical layer: hand-written logic for a few frequent question templates,
compared with train answers. Development tool only (never used at inference).

usage: python tools/oracle_check.py --split train/train --cache cache/canon [--biz biz_101 ...]
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402

from src.dates import DateResolver, LunarCalendar, parse_date_rules  # noqa: E402
from src.qnorm import QuestionNormalizer, plain  # noqa: E402
from src.evalsplit import load_splits  # noqa: E402
from src.store import BusinessStore  # noqa: E402

PERIODS = [
    (r"thang (\d{1,2})(?:/| nam )(\d{4})", lambda m: f"month:{m.group(2)}-{m.group(1)}"),
    (r"quy (\d)(?:/| nam )(\d{4})", lambda m: f"quarter:{m.group(2)}-{m.group(1)}"),
    (r"(\d+) ngay gan nhat", lambda m: f"last_n_days:{m.group(1)}"),
    (r"\b(hom nay|hnay|bua nay)\b", lambda m: "today"),
    (r"\b(hom qua|hqua|bua qua)\b", lambda m: "yesterday"),
    (r"tuan (truoc|roi|trc)", lambda m: "last_week"),
    (r"tuan nay", lambda m: "this_week"),
    (r"thang nay", lambda m: "this_month"),
    (r"thang (truoc|roi|trc)", lambda m: "last_month"),
    (r"dau nam", lambda m: "this_year"),
]
EXCL = r"nhom|khach|mat hang|hang nao|\bca\b|kenh|zalo|quay|cod|tien mat|chuyen khoan|nhan vien|ke don|hoat chat|size|" \
       r"trung binh|%|phan tram|so voi|so vs|tang|giam|ngay nao|top|cao nhat|nhieu nhat|chiem|ti trong|lai|loi|thuoc|" \
       r"\bsp\b|san pham|mon|ly|lon|chai|goi|cay|bao|thung|hop|vien|kg|dia|phan|vi dien|tro len|it nhat|tu \d|" \
       r"hon|kem|chenh|lan luot|va doanh|nhap|no|tra|ton|kho|huy|giao|online|dien thoai|shopee"


def period_of(p: str):
    found = []
    for pat, f in PERIODS:
        for m in re.finditer(pat, p):
            found.append(f(m))
    return found


FILLER = set("""cho toi minh biet hoi doanh thu dthu tong cong cua hang ban duoc dc bao nhieu bn bnhiu nhiu tien la trong
ha z vay nhi a ta xem giup gium coi check the nao do e oi ve thu mang tat ca toan bo co bill don hoa may so luong
ra hok khong k ko chu hen nhe nha s duoc o tren tai dua lai mot ngay nay qua hom hnay hqua bua tuan truoc roi trc
thang nam tu dau toi het den gan nhat ky""".split())


def _only_filler(p: str) -> bool:
    for pat, _ in PERIODS:
        p = re.sub(pat, " ", p)
    toks = re.findall(r"[a-z]+|\d+", p)
    return all(t in FILLER for t in toks)


def classify(p: str):
    per = period_of(p)
    if len(per) != 1:
        return None, None
    if re.search(r"(ti le|ty le|bao nhieu %|bn %|bnhiu %|may %|phan tram).*huy|huy.*(ti le|ty le|%|phan tram)", p)             and _only_filler(re.sub(r"ti le|ty le|phan tram|%|huy|bi|don|o trang thai", " ", p)):
        return "cancel_rate", per[0]
    if re.search(r"(bao nhieu|may|bn|bnhiu|so) (don|bill|hoa don)", p) and _only_filler(p) and "tien" not in p:
        return "n_orders", per[0]
    if re.search(r"don.*huy|huy.*don", p) and _only_filler(re.sub(r"huy|bi|o trang thai|da", " ", p)):
        return "n_cancel", per[0]
    if re.search(r"doanh thu|dthu|tien", p) and _only_filler(p):
        return "revenue", per[0]
    return None, None


def valid_orders(o):
    return o[~o["status"].isin(["huy", "tra_hang"]) & ~o["has_return"].fillna(False)]


def in_period(df, col, P):
    s = pd.Timestamp(P.start)
    e = pd.Timestamp(P.end)
    return df[(df[col] >= s) & (df[col] < e)]


def compute(kind, P, B):
    o = B.tables.get("orders")
    L = B.tables.get("lines")
    if kind == "revenue":
        if o is not None:
            x = in_period(valid_orders(o), "order_date", P)
            v = x["items_amount"].where(x["items_amount"].notna(), x["goods_amount"]).sum()
        else:
            x = L[~L["status"].isin(["huy", "tra_hang"]) & ~L["is_return_line"]]
            v = in_period(x, "order_date", P)["line_amount"].sum()
        return int(round(v))
    if o is None:
        return None
    if kind == "n_orders":
        return int(len(in_period(valid_orders(o), "order_date", P)))
    if kind == "n_cancel":
        return int((in_period(o, "order_date", P)["status"] == "huy").sum())
    if kind == "cancel_rate":
        x = in_period(o, "order_date", P)
        return round(100 * (x["status"] == "huy").sum() / len(x), 2) if len(x) else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="train/train")
    ap.add_argument("--cache", default="cache/canon")
    ap.add_argument("--biz", nargs="*")
    ap.add_argument("--show", type=int, default=6)
    a = ap.parse_args()
    Q = [json.loads(l) for l in open(os.path.join(a.split, "questions.jsonl"), encoding="utf8")]
    A = {json.loads(l)["id"]: json.loads(l) for l in open(os.path.join(a.split, "answers.jsonl"), encoding="utf8")}
    rb = open(os.path.join(a.split, "rulebook.md"), encoding="utf8").read()
    rules = parse_date_rules(rb)
    cal = LunarCalendar(os.path.join(a.split, "calendar.csv"))
    qn = QuestionNormalizer([rb] + [q["question"] for q in Q])
    store = BusinessStore(os.path.join(a.split, "data"), a.cache)
    splits = load_splits()
    by_group = collections.defaultdict(lambda: [0, 0])
    stats = collections.defaultdict(lambda: [0, 0])
    per_biz = collections.defaultdict(lambda: [0, 0])
    bad = collections.defaultdict(list)
    for q in Q:
        if a.biz and q["business_id"] not in a.biz:
            continue
        p = plain(qn.normalize(q["question"]))
        kind, pexpr = classify(p)
        if not kind:
            continue
        gold = A[q["id"]]
        B = store.get(q["business_id"])
        R = DateResolver(dt.date.fromisoformat(q["as_of_date"]), cal, rules, B.flags.get("data_start"))
        P = R.resolve(pexpr)
        try:
            pred = compute(kind, P, B)
        except Exception as e:  # noqa
            pred = f"ERR {e!r}"
        if gold["type"] not in ("number", "percent", "unanswerable"):
            continue
        if gold["type"] == "unanswerable":
            ok = False
            pred = f"{pred} (gold unanswerable)"
        else:
            ok = pred is not None and not isinstance(pred, str) and abs(float(pred) - float(gold["answer"])) < 1e-6
        stats[kind][0] += ok
        stats[kind][1] += 1
        by_group[splits.group(q["business_id"])][0] += ok
        by_group[splits.group(q["business_id"])][1] += 1
        per_biz[q["business_id"]][0] += ok
        per_biz[q["business_id"]][1] += 1
        if not ok:
            bad[kind].append((q["business_id"], q["as_of_date"], q["question"], pexpr, pred, gold["answer"]))
    for k, (c, n) in stats.items():
        print(f"{k:12s} {c}/{n}")
    print("per group:", {g: f"{c}/{n}" for g, (c, n) in sorted(by_group.items())})
    print("per biz:", {b: f"{c}/{n}" for b, (c, n) in sorted(per_biz.items())})
    for k, lst in bad.items():
        print("=== wrong", k)
        for x in lst[: a.show]:
            print("  ", x)


if __name__ == "__main__":
    main()
