"""Build configs/vi_vocab.txt: accented Vietnamese words used to validate telex-typo repairs.

Sources: rulebook(s) and question texts of the chosen validation groups (inputs only, no answers).
Default is the `dev` group only so that held-out business types stay unseen during development;
rebuild with --groups dev val_business val_type for the final submission.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.evalsplit import load_splits  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="train/train")
    ap.add_argument("--groups", nargs="*", default=["dev"])
    ap.add_argument("--out", default="configs/vi_vocab.txt")
    a = ap.parse_args()
    sp = load_splits()
    words = set()
    rb = os.path.join(a.split, "rulebook.md")
    texts = [open(rb, encoding="utf-8").read()] if os.path.exists(rb) else []
    for line in open(os.path.join(a.split, "questions.jsonl"), encoding="utf-8"):
        q = json.loads(line)
        if sp.group(q["business_id"]) in a.groups:
            texts.append(q["question"])
    for t in texts:
        for w in re.findall(r"[^\W\d_]+", t.lower()):
            if any(ord(c) > 127 for c in w):
                words.add(w)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write("\n".join(sorted(words)))
    print(len(words), "words ->", a.out)


if __name__ == "__main__":
    main()
