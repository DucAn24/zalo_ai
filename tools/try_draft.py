"""Run a hand-written draft (TYPE/PERIODS/SQL) through the real pipeline code without an LLM.
Used to verify exemplars against train answers (dev group only).

    python tools/try_draft.py --biz biz_109 --as-of 2026-08-05 --draft draft.txt
or import: `verify(biz, as_of, draft_text, gold)`.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import load_config  # noqa: E402
from src.dates import DateResolver  # noqa: E402
from src.main import Runtime  # noqa: E402
from src.matcher import is_correct  # noqa: E402

_RT: dict[str, Runtime] = {}


def runtime(split: str = "train/train") -> Runtime:
    if split not in _RT:
        cfg = load_config()
        from src.llm import LLMClient
        _RT[split] = Runtime(split, cfg, llm=LLMClient("http://127.0.0.1:1/v1", "none"))
    return _RT[split]


def run_draft(biz: str, as_of: str, draft: str, split: str = "train/train"):
    rt = runtime(split)
    br = rt.biz_no_llm(biz) if hasattr(rt, "biz_no_llm") else _biz(rt, biz)
    resolver = DateResolver(dt.date.fromisoformat(as_of), rt.cal, rt.rules.date, br.data_start)
    ans, trace = rt.agent._execute(draft, br.ctx, br.sandbox, resolver)
    return ans, trace


def _biz(rt: Runtime, biz: str):
    # same as Runtime.biz but without the LLM warm-up call
    from src.main import BizRuntime
    from src.prompts import build_context
    from src.sandbox import Sandbox
    from src.views import build_views
    if biz in rt._biz:
        return rt._biz[biz]
    B = rt.store.get(biz)
    sb = Sandbox(B, raw_other_only=True, raw_kinds=B.raw_kinds)
    sb.add_views(build_views(B, rt.rules.non_item_names))
    ctx = build_context(B, sb, rt.rules)
    br = BizRuntime(ctx, sb, B.flags.get("data_start"), B.flags.get("data_end"))
    rt._biz[biz] = br
    return br


def verify(biz: str, as_of: str, draft: str, gold: dict, split: str = "train/train"):
    ans, trace = run_draft(biz, as_of, draft, split)
    ok = is_correct(ans, gold) if ans else None
    return ok, ans, trace


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--biz", required=True)
    ap.add_argument("--as-of", required=True)
    ap.add_argument("--draft", required=True)
    a = ap.parse_args()
    ans, trace = run_draft(a.biz, a.as_of, open(a.draft, encoding="utf-8").read())
    print(json.dumps({"answer": ans, "error": trace.get("error"), "sql": trace.get("sql_final")}, ensure_ascii=False, indent=1))
