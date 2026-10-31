---
name: compliance-audit
description: Pre-submission compliance gate for the Zalo AI Challenge rules (offline, ≤15B params, no hard-coding, logs, determinism, time). Use before every Docker submission and before the freeze on 11/16.
---
Run the `compliance-auditor` agent, then run `pytest -q` and a determinism check (same sample twice with `temperature 0` → identical `submission.jsonl`). Print a PASS/FAIL table; any FAIL blocks submission. Confirm README "Models" section is up to date.
