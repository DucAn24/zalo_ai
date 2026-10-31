---
name: eval-run
description: Run the local evaluation (Penalized Accuracy) on a train sample/group, compare against the previous run and summarize correct/wrong/abstain by type, category and business. Use after any change to src/, prompts or exemplars.
---
1. `pytest -q` first; stop if failing.
2. Ensure an LLM server is reachable (`LLM_BASE_URL`), or start `python tools/fake_llm_server.py` for plumbing-only checks (say clearly that fake results are not real scores).
3. Run: `python eval.py --split train/train --run --out runs/<short-name> --group <dev|val_business|val_type> --sample <N>` (default dev, 100). Use the same sample/seed when comparing runs.
4. Report: PA, #correct/#wrong/#abstain, by type and category, worst businesses, elapsed per question; delta versus the previous `runs/*` with the same group/sample.
5. Never tune on `val_type`; run it only as a periodic honest check. Hand failures to the `error-analyst` agent (or `/error-analysis`).
