"""Decide between answering and abstaining.

PA (Penalized Accuracy): correct +1, wrong -penalty, abstain 0 (penalty from config; train rulebook says 1).
Answering has positive expected value only if P(correct) > penalty / (1 + penalty); that is the default
threshold (`decide.answer_threshold: auto`). The confidence comes from self-consistency (fraction of samples
agreeing) and, with a single sample, from whether the first attempt already worked.
"""
from __future__ import annotations

from .sql_agent import AgentResult


def decide(result: AgentResult, threshold: float) -> dict:
    ans = result.answer
    if not ans or ans.get("type") == "abstain":
        return {"type": "abstain"}
    if result.confidence + 1e-9 < threshold:
        return {"type": "abstain"}
    return ans
