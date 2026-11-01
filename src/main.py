"""Pipeline entry point: read a split folder, answer every question, write submission.jsonl and logs.

Usage:  python -m src.main [--data /data] [--out /result] [--limit N]
Every answer is appended to submission.jsonl and flushed immediately, so a timeout keeps finished work.
"""
from __future__ import annotations

import argparse
import collections
import concurrent.futures as cf
import datetime as dt
import json
import logging
import os
import sys
import threading
import time
import traceback
from typing import Optional

from .config import answer_threshold, load_config
from .decide import decide
from .dates import DateResolver, LunarCalendar
from .llm import LLMClient
from .prompts import BizContext, ExemplarStore, build_context
from .qnorm import QuestionNormalizer
from .rules import Rules, parse_rules
from .sandbox import Sandbox
from .sql_agent import SQLAgent
from .store import BusinessStore
from .views import build_views

log = logging.getLogger("datamate")


def find_split_dir(root: str) -> str:
    """The test folder may be /data itself or a sub-folder holding questions.jsonl (depth <= 2)."""
    if not os.path.isdir(root):
        raise FileNotFoundError(f"data folder not found: {root} (upload/unzip the split there, or pass --data)")
    if os.path.exists(os.path.join(root, "questions.jsonl")):
        return root
    for d1 in sorted(os.listdir(root)):
        p1 = os.path.join(root, d1)
        if os.path.isdir(p1):
            if os.path.exists(os.path.join(p1, "questions.jsonl")):
                return p1
            for d2 in sorted(os.listdir(p1)):
                p2 = os.path.join(p1, d2)
                if os.path.isdir(p2) and os.path.exists(os.path.join(p2, "questions.jsonl")):
                    return p2
    raise FileNotFoundError(f"questions.jsonl not found under {root}")


def _read_vocab() -> list[str]:
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "configs", "vi_vocab.txt")
    return open(p, encoding="utf-8").read().split() if os.path.exists(p) else []


class BizRuntime:
    def __init__(self, ctx: BizContext, sandbox: Sandbox, data_start, data_end):
        self.ctx, self.sandbox, self.data_start, self.data_end = ctx, sandbox, data_start, data_end


class Runtime:
    def __init__(self, split_dir: str, cfg: dict, llm: Optional[LLMClient] = None, max_biz: int = 6):
        self.split_dir = split_dir
        self.cfg = cfg
        rb = os.path.join(split_dir, "rulebook.md")
        self.rules: Rules = parse_rules(open(rb, encoding="utf-8").read() if os.path.exists(rb) else "")
        cal = os.path.join(split_dir, "calendar.csv")
        self.cal = LunarCalendar(cal if os.path.exists(cal) else None)
        data_dir = os.path.join(split_dir, "data")
        if not os.path.isdir(data_dir):
            data_dir = split_dir
        self.store = BusinessStore(data_dir, cfg["paths"]["cache_dir"])
        self.exemplars = ExemplarStore()
        self.llm = llm or LLMClient.from_config(cfg)
        self.agent = SQLAgent(cfg, self.llm, self.exemplars, self.rules)
        self.qn = QuestionNormalizer(_read_vocab())
        self.qn.add_vocab([self.rules.text])
        self.threshold = answer_threshold(cfg, self.rules.penalty_hint)
        self._biz: "collections.OrderedDict[str, BizRuntime]" = collections.OrderedDict()
        self._locks: dict[str, threading.Lock] = collections.defaultdict(threading.Lock)
        self._glock = threading.Lock()
        self._failed: dict[str, Exception] = {}      # business build failures are remembered (no rebuild per question)
        self.max_biz = max_biz

    def biz(self, biz_id: str) -> BizRuntime:
        with self._glock:
            if biz_id in self._biz:
                self._biz.move_to_end(biz_id)
                return self._biz[biz_id]
            lock = self._locks[biz_id]
        with lock:
            with self._glock:
                if biz_id in self._biz:
                    return self._biz[biz_id]
            if biz_id in self._failed:
                raise self._failed[biz_id]
            try:
                return self._build_biz(biz_id)
            except Exception as e:
                log.error("building business %s failed: %s\n%s", biz_id, e, traceback.format_exc())
                self._failed[biz_id] = e
                raise

    def _build_biz(self, biz_id: str) -> BizRuntime:
        t0 = time.time()
        B = self.store.get(biz_id)
        sb = Sandbox(B, raw_other_only=True, raw_kinds=B.raw_kinds)
        sb.add_views(build_views(B, self.rules.non_item_names))
        ctx = build_context(B, sb, self.rules)
        prod = B.tables.get("products")
        if prod is not None:
            self.qn.add_vocab(prod["product_name"].dropna().tolist())
        br = BizRuntime(ctx, sb, B.flags.get("data_start"), B.flags.get("data_end"))
        try:   # prime the server's prefix cache with this business's system prompt
            self.llm.chat([{"role": "system", "content": ctx.system}, {"role": "user", "content": "OK?"}],
                          max_tokens=1)
        except Exception as e:
            log.warning("warm-up failed for %s: %s", biz_id, e)
        log.info("business %s ready in %.1fs", biz_id, time.time() - t0)
        with self._glock:
            self._biz[biz_id] = br
            while len(self._biz) > self.max_biz:
                self._biz.popitem(last=False)
        return br

    def process(self, q: dict) -> tuple[dict, dict]:
        t0 = time.time()
        sub: dict = {"id": q["id"], "type": "abstain"}
        lg: dict = {"id": q["id"], "business_id": q["business_id"], "question": q["question"],
                    "as_of_date": q["as_of_date"]}
        try:
            br = self.biz(q["business_id"])
            as_of = dt.date.fromisoformat(q["as_of_date"])
            qn = self.qn.normalize(q["question"])
            resolver = DateResolver(as_of, self.cal, self.rules.date, br.data_start)
            res = self.agent.answer(qn, as_of, br.ctx, br.sandbox, resolver)
            final = decide(res, self.threshold)
            sub = {"id": q["id"], **final}
            lg.update(question_norm=qn, answer=final, proposed=res.answer, confidence=res.confidence,
                      sql=res.sql, periods=res.periods, entities=res.entities, error=res.error,
                      attempts=[[{k: v for k, v in a.items() if k != "raw"} | {"raw": a.get("raw", "")[:1500]}
                                 for a in s.attempts] for s in res.samples])
        except Exception as e:  # never lose a question because of a bug
            lg.update(error=f"{type(e).__name__}: {e}", trace=traceback.format_exc()[-1500:], answer=sub)
            log.error("question %s failed: %s", q["id"], e)
        lg["elapsed_s"] = round(time.time() - t0, 3)
        return sub, lg


def run_pipeline(split_dir: str, out_dir: str, questions: Optional[list[dict]] = None, cfg: Optional[dict] = None,
                 llm: Optional[LLMClient] = None, limit: Optional[int] = None) -> dict:
    cfg = cfg or load_config()
    os.makedirs(os.path.join(out_dir, "logs"), exist_ok=True)
    sub_path = os.path.join(out_dir, "submission.jsonl")
    log_path = os.path.join(out_dir, "logs", "logs.jsonl")
    if questions is None:
        with open(os.path.join(split_dir, "questions.jsonl"), encoding="utf-8") as f:
            questions = [json.loads(x) for x in f if x.strip()]
    if limit:
        questions = questions[:limit]
    rt = Runtime(split_dir, cfg, llm)
    if not rt.llm.wait_ready(float(cfg.get("llm", {}).get("startup_wait_s", 600))):
        raise RuntimeError(f"LLM server not reachable at {rt.llm.base_url}")
    kept: list[tuple[str, str]] = []                            # (submission line, log line) already done and healthy
    if os.path.exists(sub_path) and os.path.exists(log_path) and cfg.get("run", {}).get("resume", False):
        with open(sub_path, encoding="utf-8") as f1, open(log_path, encoding="utf-8") as f2:
            for a, b in zip(f1, f2):
                try:
                    sid, lgd = json.loads(a)["id"], json.loads(b)
                except json.JSONDecodeError:
                    continue
                if lgd.get("id") == sid and "trace" not in lgd:   # entries with a crash trace are redone
                    kept.append((a if a.endswith("\n") else a + "\n", b if b.endswith("\n") else b + "\n"))
    done = {json.loads(a)["id"] for a, _ in kept}
    todo = [q for q in questions if q["id"] not in done]
    todo.sort(key=lambda q: (q["business_id"],))            # keep one business hot at a time
    log.info("resume: %d already done, %d to run", len(done), len(todo))
    lock = threading.Lock()
    budget = float(cfg["run"]["time_budget_s"])
    t_start = time.time()
    counts = collections.Counter()

    def work(q):
        if time.time() - t_start > budget:
            return None
        sub, lg = rt.process(q)
        with lock:
            fs.write(json.dumps(sub, ensure_ascii=False) + "\n"); fs.flush()
            fl.write(json.dumps(lg, ensure_ascii=False, default=str) + "\n"); fl.flush()
            counts[sub["type"]] += 1
            n = sum(counts.values())
            if n % 25 == 0:
                log.info("%d/%d done (%.0fs) %s", n, len(todo), time.time() - t_start, dict(counts))
        return sub

    with open(sub_path, "w", encoding="utf-8") as fs, open(log_path, "w", encoding="utf-8") as fl:
        for a, b in kept:
            fs.write(a)
            fl.write(b)
        fs.flush(); fl.flush()
        with cf.ThreadPoolExecutor(max_workers=int(cfg["run"]["workers"])) as ex:
            list(ex.map(work, todo))
    summary = {"questions": len(todo), "skipped_by_budget": len(todo) - sum(counts.values()),
               "seconds": round(time.time() - t_start, 1), "types": dict(counts),
               "llm_calls": rt.llm.stats.calls, "prompt_tokens": rt.llm.stats.prompt_tokens,
               "completion_tokens": rt.llm.stats.completion_tokens, "threshold": rt.threshold}
    with open(os.path.join(out_dir, "logs", "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)
    log.info("finished: %s", summary)
    return summary


def main(argv: Optional[list[str]] = None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", help="folder with the test split (default: $DATA_DIR)")
    ap.add_argument("--out", help="output folder (default: $RESULT_DIR)")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--biz", nargs="*", help="only these business ids")
    ap.add_argument("--config")
    a = ap.parse_args(argv)
    cfg = load_config(a.config)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr)
    root = a.data or cfg["paths"]["data_dir"]
    out = a.out or cfg["paths"]["result_dir"]
    split = find_split_dir(root)
    log.info("split=%s out=%s model=%s url=%s", split, out, cfg["llm"]["model"], cfg["llm"]["base_url"])
    qs = None
    if a.biz:
        with open(os.path.join(split, "questions.jsonl"), encoding="utf-8") as f:
            qs = [q for q in (json.loads(x) for x in f if x.strip()) if q["business_id"] in a.biz]
    run_pipeline(split, out, questions=qs, cfg=cfg, limit=a.limit)


if __name__ == "__main__":
    main()
