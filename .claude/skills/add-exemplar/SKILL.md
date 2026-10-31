---
name: add-exemplar
description: Add a few-shot exemplar to configs/exemplars.yaml from a TRAIN question with a verified SQL. Use when a question family keeps failing for the LLM.
---
Rules: exemplars come ONLY from train data (never public/private test). Keep them generic (placeholders for periods `{P1:col}`, canonical table names), never keyed to one business id.
1. Read `configs/exemplars.yaml` for the format and existing coverage (avoid duplicates; cover: ranking, comparison, growth %, share %, debt/unpaid, expiring stock, Tết window, unanswerable).
2. Write question (vary: accented, unaccented, telex, abbreviations), required tables, TYPE, PERIODS, SQL.
3. Validate: execute SQL on the source business via the sandbox and compare to the train reference with `src/matcher.py`.
4. Add to yaml, run `pytest -q`, then `/eval-run` to check no regression.
