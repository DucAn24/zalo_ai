# DataMate — Zalo AI Challenge 2026 (Vietnamese QA over tabular data)

Offline agent: question (Vietnamese) + as-of date + business files (csv/xlsx/sqlite) + rulebook → typed answer.
Architecture and layout: see `README.md` (pipeline: canon tables → entities → prompt → LLM writes TYPE/PERIODS/SQL → DuckDB sandbox → formatter → decide answer/abstain).

## Scoring (drives every decision)
- Per question: correct +1, wrong −penalty, abstain 0 (penalty from the split's rulebook; train = 1). Answer only if P(correct) ≥ penalty/(1+penalty).
- Type must equal reference type AND value match. No partial credit. Wrong answer to an `unanswerable` question = wrong; abstain on it = 0.
- Matching rules live in `src/matcher.py` (number exact; percent 2dp + sign; string NFC/lowercase/non-alnum→space; date `yyyy-mm-dd` or `yyyy-mm`; list ordered; table rows as set).
- Rankings: criterion in question else rulebook default, desc, ties by code ascending.

## Hard competition constraints (violating = disqualification)
1. Fully offline at inference: no network, no commercial APIs, no downloads. Docker run with networking disabled.
2. All models used at inference: total params ≤ 15B (MoE counts all params), weights public before 2026-10-01. Declare in README "Models".
3. No hard-coding of answers or logic keyed on question ids / business ids / business names. Logic must be general (private test has unseen business types).
4. Never train on or collect answers from public/private test data. `answers.jsonl` of train only.
5. Whole private test < 6h on 2×RTX 5090 incl. model load (we budget `run.time_budget_s`=20400). Data dir is read-only; write only to `/result`, cache dir, `/tmp`.
6. Deterministic enough: |PA(upload) − PA(rerun)| ≤ 0.03 → temperature 0, fixed seed, stable ordering.
7. Must write `/result/submission.jsonl` (flush after each question) and per-question logs in `/result/logs/` (id, final answer, elapsed, SQL/outputs).
8. The **rulebook of each split is read at runtime** (`rules.py`, `dates.py`); never copy training rulebook values into code. Rulebook may differ between splits.

## Working rules
- Generalize: fix root causes in canonicalization / rule parsing / prompts, not per-business patches. Validate on `val_business` and `val_type` groups (`configs/eval_splits.yaml`, eval-only; the pipeline never reads it). Don't tune on `val_type` — keep it as the honest estimate for unseen business types.
- Dates are computed in code (`src/dates.py`), never by the LLM. Literal dates in SQL are rejected.
- Prefer `unanswerable` by code when the data lacks a needed field/period; prefer `abstain` when confidence is low.
- Every change: run `pytest -q`, then an eval on a sample (`/eval-run`) and compare PA vs previous run in `runs/`. Report wrong / abstain / correct counts, not just accuracy.
- Keep `README.md` "Models" section accurate (name, params, license, release date).
- Vietnamese text: always NFC; keep diacritics in answers (string match keeps diacritics). Questions are often unaccented/telex/abbreviated ("sp", "dc", "ko").
- Do not commit data (`train/`, `public_test/`, `private_test/`, `cache/`, `runs/`, `models/` are gitignored).
- Branch: develop on the branch assigned for the session; don't open PRs unless asked.

## Commands
```
pip install -r requirements.txt && pytest -q
python -m src.main --data /data --out /result
python eval.py --split train/train --run --out runs/<name> --group dev --sample 100
python tools/oracle_check.py ...        # validate canonical layer vs reference answers
python tools/fake_llm_server.py         # plumbing test without a GPU
bash scripts/start_vllm.sh              # real LLM server (OpenAI-compatible)
```

## Sub-agents (`.claude/agents/`)
- `data-profiler` — profile one business's raw files + README, report quirks and column roles.
- `error-analyst` — classify failures from an eval run into root-cause buckets, propose general fixes.
- `rulebook-auditor` — check that code/prompts honor every rule of a split's rulebook.md.
- `compliance-auditor` — audit repo for offline / ≤15B / no-hardcode / logging rules before a submission.
- `docker-packager` — build and smoke-test the offline Docker image + predict.sh.
- `sql-reviewer` — review generated SQL logs for semantic bugs (revenue/returns/week/period).

## Skills (`.claude/skills/`)
`/eval-run`, `/error-analysis`, `/add-exemplar`, `/rulebook-sync`, `/profile-business`, `/compliance-audit`, `/build-docker`, plus `grill-me`.

## Timeline
Public test 10/26–11/16 (≤5 submissions/day). Docker due 11/16 23:59 GMT+7. Private test 11/20 09:00 → upload by 11/23 23:59. Freeze code before 11/16; after that only run the frozen image.
