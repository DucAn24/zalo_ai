"""Question -> SQL -> answer. One sample = parse the LLM draft, resolve periods in code, run the SQL in the
read-only sandbox, format to the answer type; failures are fed back to the LLM (bounded retries).
Several samples (self-consistency) are voted on by the caller's settings."""
from __future__ import annotations

import collections
import datetime as dt
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

import pandas as pd

from .dates import DateResolver, Period
from .entities import entities_prompt
from .formatter import FormatError, format_answer
from .llm import LLMClient, LLMError
from .prompts import BizContext, ExemplarStore, build_messages
from .protocol import Draft, ProtocolError, dates_in_text, parse_response, resolve_periods, substitute
from .rules import Rules
from .sandbox import Sandbox, SandboxError

log = logging.getLogger(__name__)

_PLACEHOLDER_COL_RE = re.compile(r"\{(P\d+):([A-Za-z_][\w.]*)\}")
_PLACEHOLDER_ANY_RE = re.compile(r"\{(P\d+)[:.]")
EXEMPT_COLS = {"expiry", "due_date"}     # columns whose dates are not tied to the sales history window


@dataclass
class Sample:
    answer: Optional[dict] = None          # formatted answer dict, or None when every attempt failed
    key: str = ""                          # canonical string used for voting
    attempts: list[dict] = field(default_factory=list)
    ok_first_try: bool = False
    forced_unanswerable: bool = False      # decided by code (period outside the data)


@dataclass
class AgentResult:
    answer: dict
    confidence: float
    samples: list[Sample]
    entities: str = ""
    question_norm: str = ""
    sql: str = ""
    periods: dict[str, str] = field(default_factory=dict)
    error: str = ""


def _canon(ans: dict) -> str:
    return json.dumps(ans, ensure_ascii=False, sort_keys=True)


def _unanswerable(reason: str) -> dict:
    return {"type": "unanswerable", "reason": reason}


class SQLAgent:
    def __init__(self, cfg: dict, llm: LLMClient, exemplars: ExemplarStore, rules: Rules):
        self.cfg = cfg
        self.llm = llm
        self.exemplars = exemplars
        self.rules = rules
        self.max_retries = int(cfg["sql"]["max_retries"])
        self.timeout = float(cfg["sql"]["timeout_s"])
        self.n_samples = int(cfg["decide"].get("n_samples", 1))
        self.k_ex = int(cfg.get("prompt", {}).get("k_exemplars", 5))
        self.sample_temp = float(cfg["decide"].get("sample_temperature", 0.6))
        self.retry_conf = float(cfg["decide"].get("retry_confidence", 0.7))
        self.retry_temp = float(cfg["decide"].get("retry_temperature", 0.5))

    # ------------------------------------------------------------------ one draft
    def _execute(self, text: str, ctx: BizContext, sb: Sandbox, resolver: DateResolver,
                 allowed_dates: Optional[set] = None) -> tuple[Optional[dict], dict]:
        """Returns (answer or None, trace). Raises nothing: errors go to trace['error']."""
        trace: dict[str, Any] = {"raw": text}
        try:
            d: Draft = parse_response(text)
            trace.update(type=d.type, periods=d.periods, sql=d.sql, decimals=d.decimals)
            if d.type == "unanswerable":
                return _unanswerable(d.reason or "dữ liệu không đủ"), trace
            periods = resolve_periods(d.periods, resolver)
            bad = self._outside_data(d.sql, periods, ctx)
            if bad:
                trace["forced"] = bad
                return _unanswerable(bad), trace
            sql = substitute(d.sql, periods, self.rules.date, (allowed_dates or set()) | {resolver.today})
            trace["sql_final"] = sql
            df = sb.run(sql, self.timeout)
            trace["rows"] = len(df)
            trace["result_preview"] = df.head(5).to_dict("records") if len(df) else []
            ans = self._format(df, d)
            return ans, trace
        except (ProtocolError, SandboxError, FormatError) as e:
            trace["error"] = str(e)
            return None, trace

    def _format(self, df: pd.DataFrame, d: Draft) -> dict:
        t = d.type
        if t in ("number", "percent", "string", "date", "boolean"):
            if len(df) == 0:
                raise FormatError("truy vấn không trả về dòng nào (hãy dùng COALESCE(SUM(...), 0) nếu kết quả hợp lệ là 0)")
            if df.shape[1] == 1 and len(df) > 1 and df.iloc[:, 0].nunique(dropna=True) == 1:
                df = df.iloc[:1]                      # the same value repeated (e.g. one price on several lines)
            if df.shape[1] == 1 and len(df) > 1:
                raise FormatError(f"kết quả có {len(df)} dòng nhưng TYPE {t} cần đúng 1 giá trị: hãy gộp lại bằng "
                                  "COUNT/SUM/MAX/mode hoặc bọc truy vấn trong SELECT COUNT(*) FROM (...). "
                                  "Chỉ dùng TYPE list khi câu hỏi hỏi một danh sách đối tượng")
            if df.shape != (1, 1):
                raise FormatError(f"kết quả có {df.shape[0]} dòng × {df.shape[1]} cột nhưng TYPE {t} cần đúng 1 giá trị. "
                                  "Nhiều số theo thứ tự câu hỏi → TYPE: list (một dòng, mỗi số một cột)")
            v = df.iat[0, 0]
            if v is None or (isinstance(v, float) and pd.isna(v)) or v is pd.NaT:
                raise FormatError("kết quả là NULL (không có dòng nào khớp điều kiện; kiểm tra lại điều kiện lọc/tên thực thể)")
            return format_answer(v if len(df) == 1 and df.shape[1] == 1 else df, t, decimals=d.decimals)
        if t == "list":
            if df.shape[0] == 1 and df.shape[1] > 1:
                return format_answer(df.iloc[0].tolist(), "list")
            return format_answer(df.iloc[:, 0].tolist() if df.shape[1] else [], "list")
        if t == "table":
            if len(df) == 0:
                raise FormatError("bảng kết quả rỗng")
            return format_answer(df, "table", columns=d.columns if len(d.columns) == df.shape[1] else None)
        raise FormatError(f"TYPE không hỗ trợ: {t}")

    @staticmethod
    def _outside_data(sql: str, periods: dict[str, Period], ctx: BizContext) -> str:
        if ctx.data_start is None or ctx.data_end is None:
            return ""
        cols: dict[str, set[str]] = collections.defaultdict(set)
        for name, col in _PLACEHOLDER_COL_RE.findall(sql):
            cols[name].add(col.split(".")[-1])
        used = set(_PLACEHOLDER_ANY_RE.findall(sql))
        for name in sorted(used):
            p = periods.get(name)
            if p is None:
                continue
            if cols.get(name) and cols[name] <= EXEMPT_COLS:
                continue
            if p.end <= ctx.data_start or p.start > ctx.data_end:
                return (f"Kỳ {p.start}..{p.last_day} nằm hoàn toàn ngoài khoảng ngày có dữ liệu "
                        f"({ctx.data_start}..{ctx.data_end}).")
        return ""

    # ------------------------------------------------------------------ retries
    def _run_chain(self, messages: list[dict], first_text: str, ctx, sb, resolver, allowed_dates=None) -> Sample:
        s = Sample()
        text = first_text
        msgs = list(messages)
        for attempt in range(self.max_retries + 1):
            ans, trace = self._execute(text, ctx, sb, resolver, allowed_dates)
            trace["attempt"] = attempt
            s.attempts.append(trace)
            if ans is not None:
                s.answer, s.key = ans, _canon(ans)
                s.ok_first_try = attempt == 0
                s.forced_unanswerable = "forced" in trace
                return s
            if attempt == self.max_retries:
                break
            err = trace["error"]
            fix = (f"Lỗi: {err}\nHãy sửa và trả lời lại đúng định dạng (TYPE/PERIODS/SQL), "
                   f"chỉ dùng bảng/cột có trong danh sách.")
            if re.search(r"UNION", trace.get("sql", ""), re.I) and re.search(r"not found", err, re.I):
                fix += ("
Gợi ý: UNION ALL xếp các giá trị thành nhiều DÒNG của cùng một cột, nên không tham chiếu được tên cột "
                        "của nhánh khác. Để so sánh nhiều kỳ hãy đặt mỗi kỳ là một subquery trong FROM: "
                        "FROM (SELECT SUM(...) AS s FROM ... WHERE {P1:cột_ngày}) a, (SELECT ... {P2:cột_ngày}) b, ... "
                        "rồi so a.s, b.s, c.s.")
            if re.search(r"not found|does not exist|không trả về dòng|NULL", err, re.I):
                fix += ("\nNếu thông tin câu hỏi cần KHÔNG được dữ liệu ghi (xem mục 'Lưu ý' và danh sách bảng/cột), "
                        "đừng bịa cột/bảng: trả TYPE: unanswerable kèm REASON.")
            msgs = msgs + [{"role": "assistant", "content": text}, {"role": "user", "content": fix}]
            try:
                text = self.llm.chat(msgs, n=1, temperature=0.0 if attempt == 0 else self.retry_temp)[0]
            except LLMError as e:
                s.attempts.append({"error": f"LLM: {e}", "attempt": attempt + 1})
                break
        return s

    # ------------------------------------------------------------------ public
    def answer(self, question_norm: str, as_of: dt.date, ctx: BizContext, sb: Sandbox, resolver: DateResolver) -> AgentResult:
        ents = ctx.entity_index.find(question_norm)
        ents_text = entities_prompt(ents)
        msgs = build_messages(ctx, self.exemplars, question_norm, as_of, ents_text, self.k_ex)
        n = max(1, self.n_samples)
        try:
            texts = self.llm.chat(msgs, n=n, temperature=0.0 if n == 1 else self.sample_temp)
        except LLMError as e:
            return AgentResult({"type": "abstain"}, 0.0, [], ents_text, question_norm, error=f"LLM: {e}")
        allowed = dates_in_text(question_norm)
        samples = [self._run_chain(msgs, t, ctx, sb, resolver, allowed) for t in texts]
        votes = collections.Counter(s.key for s in samples if s.answer is not None)
        if not votes:
            last = samples[0].attempts[-1].get("error", "") if samples and samples[0].attempts else "no output"
            return AgentResult({"type": "abstain"}, 0.0, samples, ents_text, question_norm, error=last)
        best_key, cnt = max(votes.items(), key=lambda kv: (kv[1], -min(i for i, s in enumerate(samples) if s.key == kv[0])))
        winner = next(s for s in samples if s.key == best_key)
        conf = cnt / n
        if n == 1 and not winner.ok_first_try:
            conf = self.retry_conf
        last = winner.attempts[-1]
        return AgentResult(winner.answer, conf, samples, ents_text, question_norm,
                           sql=last.get("sql_final") or last.get("sql", ""), periods=last.get("periods", {}))
