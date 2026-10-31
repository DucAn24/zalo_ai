"""Evaluate predictions against answers.jsonl with the official matching rules.

Score an existing submission:
    python eval.py --split train/train --pred runs/exp1/submission.jsonl [--logs runs/exp1/logs]
Run the pipeline first, then score (stage b):
    python eval.py --split train/train --run --out runs/exp1 --sample 100 --group dev

Reports accuracy / wrong / abstain and Penalized Accuracy (configurable penalty), broken down by
validation group (dev / val_business / val_type = unseen business TYPE), answer type, question
category and business. Writes a per-question CSV for error analysis.
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import os
import random
import re
import sys

from src.config import load_config
from src.evalsplit import load_splits
from src.matcher import Score, is_correct
from src.qnorm import plain

CATEGORIES = [  # evaluation-only coarse question categories (keyword based, accent-free)
    ("tet", r"\btet\b"), ("ca", r"\bca (sang|chieu|toi)\b"), ("cong_no", r"\bno\b|cong no|chiu"),
    ("ton_kho", r"\bton\b|con hang|trong kho"), ("nhap_hang", r"\bnhap\b"), ("han_dung", r"han dung|het han|\blo\b"),
    ("gia_ban", r"tang gia|doi gia|len gia|gia ban|gia .* mot"), ("lai", r"\blai\b|\bloi\b"),
    ("huy", r"\bhuy\b"), ("nhom_hang", r"\bnhom\b"), ("thuoc", r"hoat chat|ke don"),
    ("nhan_vien", r"nhan vien|nguoi ban|\bnv\d"), ("kenh_tt", r"\bcod\b|zalo|quay|tien mat|chuyen khoan|vi dien tu|kenh"),
    ("xep_hang", r"chay nhat|top|nhieu nhat|cao nhat|hot nhat|lon nhat"), ("khach", r"khach"),
    ("so_don", r"\bdon\b|\bbill\b"), ("doanh_thu", r"dthu|doanh thu|tien|ban duoc|ban dc"),
]


def category(q: str) -> str:
    p = plain(q)
    for name, pat in CATEGORIES:
        if re.search(pat, p):
            return name
    return "khac"


def load_jsonl(path):
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return out


def select_questions(questions, splits, group=None, biz=None, sample=None, seed=0):
    qs = [q for q in questions if (not group or splits.group(q["business_id"]) in group)
          and (not biz or q["business_id"] in biz)]
    if sample and sample < len(qs):
        rnd = random.Random(seed)
        by_biz = collections.defaultdict(list)
        for q in qs:
            by_biz[q["business_id"]].append(q)
        per = max(1, sample // max(1, len(by_biz)))
        picked = []
        for b in sorted(by_biz):
            lst = by_biz[b][:]
            rnd.shuffle(lst)
            picked += lst[:per]
        qs = picked[:sample]
    return qs


def score(questions, answers, preds, splits, penalty, logs=None, out_csv=None):
    total = Score()
    by = {k: collections.defaultdict(Score) for k in ("group", "type", "category", "business")}
    rows = []
    for q in questions:
        gold = answers.get(q["id"])
        if gold is None:
            continue
        pred = preds.get(q["id"])
        ok = is_correct(pred, gold)
        total.add(ok)
        keys = {"group": splits.group(q["business_id"]), "type": gold["type"], "category": category(q["question"]),
                "business": q["business_id"]}
        for k, v in keys.items():
            by[k][v].add(ok)
        lg = (logs or {}).get(q["id"], {})
        rows.append({"id": q["id"], "business": q["business_id"], "group": keys["group"], "as_of": q["as_of_date"],
                     "category": keys["category"], "question": q["question"], "gold_type": gold["type"],
                     "gold": json.dumps(gold.get("answer"), ensure_ascii=False),
                     "pred_type": (pred or {}).get("type"), "pred": json.dumps((pred or {}).get("answer"), ensure_ascii=False),
                     "result": "abstain" if ok is None else ("ok" if ok else "wrong"),
                     "sql": lg.get("sql", ""), "error": lg.get("error", ""), "elapsed": lg.get("elapsed_s", "")})
    print(f"TOTAL   {total.fmt(penalty)}")
    for k in ("group", "type", "category", "business"):
        print(f"--- by {k}")
        for v, s in sorted(by[k].items(), key=lambda kv: (-kv[1].n, kv[0])):
            print(f"  {v:18s} {s.fmt(penalty)}")
    if out_csv:
        with open(out_csv, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["id"])
            w.writeheader()
            w.writerows(rows)
        print("per-question results ->", out_csv)
    return total, by


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="train/train", help="split folder with questions.jsonl and answers.jsonl")
    ap.add_argument("--pred", help="submission.jsonl to score")
    ap.add_argument("--logs", help="folder with per-question logs (logs.jsonl) to join into the CSV")
    ap.add_argument("--run", action="store_true", help="run the pipeline before scoring")
    ap.add_argument("--out", default="runs/latest", help="output folder for --run")
    ap.add_argument("--group", nargs="*", help="dev val_business val_type")
    ap.add_argument("--biz", nargs="*")
    ap.add_argument("--sample", type=int, help="balanced subset size (per business)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--penalty", type=float, help="override PA penalty (default from config)")
    a = ap.parse_args()

    cfg = load_config()
    penalty = a.penalty if a.penalty is not None else float(cfg["decide"]["penalty"])
    splits = load_splits()
    questions = load_jsonl(os.path.join(a.split, "questions.jsonl"))
    answers = {x["id"]: x for x in load_jsonl(os.path.join(a.split, "answers.jsonl"))}
    qs = select_questions(questions, splits, a.group, a.biz, a.sample, a.seed)

    pred_path, logs_dir = a.pred, a.logs
    if a.run:
        from src.main import run_pipeline  # stage (b)
        os.makedirs(a.out, exist_ok=True)
        run_pipeline(a.split, a.out, questions=qs, cfg=cfg)
        pred_path, logs_dir = os.path.join(a.out, "submission.jsonl"), os.path.join(a.out, "logs")
    if not pred_path:
        sys.exit("give --pred or --run")
    preds = {p["id"]: p for p in load_jsonl(pred_path) if "id" in p}
    logs = {}
    if logs_dir and os.path.exists(os.path.join(logs_dir, "logs.jsonl")):
        logs = {x["id"]: x for x in load_jsonl(os.path.join(logs_dir, "logs.jsonl")) if "id" in x}
    out_csv = os.path.join(os.path.dirname(pred_path) or ".", "eval_details.csv")
    score(qs, answers, preds, splits, penalty, logs, out_csv)


if __name__ == "__main__":
    main()
