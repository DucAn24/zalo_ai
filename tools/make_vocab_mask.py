"""Compute the vocabulary seen ONLY in held-out business types (for strict evaluation).

usage: python tools/make_vocab_mask.py --data train/train/data --out configs/vocab_mask_holdout.json
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.evalsplit import load_splits  # noqa: E402
from src.loader import load_business  # noqa: E402
from src.mapping import _kind_by_name, data_columns, map_table  # noqa: E402
from src.readme import parse_readme  # noqa: E402
from src.schema import KIND_NAME_KEYWORDS, ROLE_NAMES  # noqa: E402
from src.textnorm import col_norm  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="train/train/data")
    ap.add_argument("--out", default="configs/vocab_mask_holdout.json")
    a = ap.parse_args()
    sp = load_splits()
    names_by = collections.defaultdict(set)     # name -> {group}
    kinds_by = collections.defaultdict(set)
    tnames_by = collections.defaultdict(set)    # normalized table name -> groups
    for b in sorted(os.listdir(a.data)):
        g = "design" if sp.group(b) == "dev" else "holdout"
        raws, readme = load_business(os.path.join(a.data, b))
        info = parse_readme(readme)
        for r in raws:
            tm = map_table(r, info)
            kinds_by[tm.kind].add(g)
            for key in (r.name, r.file.rsplit(".", 1)[0]):
                tnames_by[col_norm(key).replace(" ", "")].add(g)
            for c in data_columns(r):
                names_by[col_norm(c)].add(g)
        print(b, g, flush=True)
    dict_names = {n for k in ROLE_NAMES.values() for lst in k.values() for n in lst}
    names = sorted(n for n in dict_names if names_by.get(n) == {"holdout"})
    kinds = sorted(k for k, gs in kinds_by.items() if gs == {"holdout"})
    keywords = []
    for kind, kws in KIND_NAME_KEYWORDS:
        for kw in kws:
            hits = set()
            for t, gs in tnames_by.items():
                if kw in t:
                    hits |= gs
            if hits == {"holdout"}:
                keywords.append(kw)
    mask = {"names": names, "kinds": kinds, "keywords": sorted(keywords)}
    json.dump(mask, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(mask, ensure_ascii=False))


if __name__ == "__main__":
    main()
