# DataMate — Zalo AI Challenge 2026

Offline agent answering Vietnamese questions over small-business tables (CSV / Excel / SQLite).

> Status: stages (a) and (b) done — data cleaning, canonical tables, dates, formatter, matcher, eval,
> and the LLM → SQL → DuckDB baseline (prompting, retry, abstain threshold, per-question logs).
> Not yet scored with a real model (no GPU locally): run `notebooks/colab_eval.ipynb`. Docker / `predict.sh`: stage (d).

## Pipeline per question
1. `store`/`canon`: business tables cleaned once and cached; `views`: `valid_orders` / `valid_lines`
   (not cancelled, not returned — rulebook §1) on top of the canonical tables.
2. `qnorm`: telex-typo repair; `entities`: product / group / customer / channel names found in the question.
3. `prompts`: system = rulebook (read at runtime) + schema of THIS shop + what the shop does not record;
   few-shot = TF-IDF nearest exemplars from `configs/exemplars.yaml` that fit the shop's tables.
4. `llm` → `protocol`: model writes `TYPE / PERIODS / SQL`; **dates are computed in code** (`dates`) and
   substituted for `{P1:order_date}`; literal dates in SQL are rejected.
5. `sandbox` runs the read-only SQL (timeout); `formatter` coerces the type; errors go back to the model
   (max `sql.max_retries`). Periods fully outside the shop's data range → `unanswerable` by code.
6. `decide`: confidence = vote share of `n_samples` SQL drafts (sample 0 greedy, rest sampled); answer if confidence ≥ threshold
   = max(`penalty / (1 + penalty)` with the penalty read from the split's rulebook §9, `decide.min_confidence`), else `abstain`.
   An `unanswerable` whose reason names a column the data has is retried, and if it persists its confidence is ×0.7.
   `eval.py` prints a calibration table (accuracy and PA per confidence) to choose `min_confidence`.
7. `main`: appends to `submission.jsonl` + `logs/logs.jsonl` after every question (flush).

Run: `python -m src.main --data /data --out /result` (needs an OpenAI-compatible server at `LLM_BASE_URL`).
Eval: `python eval.py --split train/train --run --out runs/exp1 --group dev --sample 100`.
No GPU? `python tools/fake_llm_server.py` serves a few canned templates to test the plumbing.

## Layout
```
src/
  loader.py     read csv/xlsx(all sheets)/sqlite, header detection, footer & title rows, split files
  parse.py      dirty values: money ('1tr440', '35k', '55.000đ'), dates (serials, '1 thg 6 2025', '1/1'), qty ('2 thùng')
  readme.py     optional README parsing (column roles, data end date, unit conversions)
  schema.py     canonical kinds / roles and the generic header vocabulary
  mapping.py    table classification + column roles (README > dictionary > header rules > fuzzy > values),
                cross-table value linking, primary sales table selection
  canon.py      canonical typed tables: orders, lines, products, unit_conv, customers, payments, imports,
                import_lines, stock, ledger, lots, lot_sales, prices, ... + raw_* copies of every file
  store.py      per-business cache (memory + disk, invalidated by data / code changes)
  dates.py      period expressions -> half-open date ranges (rules parsed from rulebook.md at runtime)
  qnorm.py      question normalization (telex typo repair against a Vietnamese vocabulary)
  rules.py      facts parsed from rulebook.md at runtime (non-item rows, date rules, compact prompt text)
  views.py      valid_orders / valid_lines views
  entities.py   entity linking (accent-insensitive, longest match, fuzzy fallback)
  llm.py        OpenAI-compatible client (vLLM / Ollama / llama.cpp; thinking off, /no_think fallback)
  prompts.py    schema description, capability notes, exemplar retrieval, message building
  protocol.py   parse TYPE/PERIODS/SQL, expand period placeholders
  sql_agent.py  draft -> run -> format -> retry; self-consistency voting
  decide.py     answer / abstain by confidence threshold
  main.py       pipeline runner with per-question flush and logs
  sandbox.py    read-only DuckDB with statement checks and timeout
  formatter.py  answer typing / rounding
  matcher.py    official matching rules + Penalized Accuracy
  evalsplit.py  validation groups (evaluation only)
eval.py         scoring with breakdowns (group / type / category / business)
tools/          oracle_check.py (canonical-layer validation), make_vocab_mask.py (strict eval),
                fake_llm_server.py (plumbing tests), build_vocab.py
scripts/        start_vllm.sh
notebooks/      colab_eval.ipynb (T4)
configs/        default.yaml (paths, LLM, thresholds), eval_splits.yaml (evaluation only)
tests/          pytest
```

## Configuration
`configs/default.yaml`, overridable by env: `DATA_DIR`, `RESULT_DIR`, `CACHE_DIR`, `LLM_BASE_URL`,
`LLM_MODEL`, `PA_PENALTY`, `ANSWER_THRESHOLD`, `MIN_CONFIDENCE`, `N_SAMPLES`, `WORKERS`.

## Validation protocol
`configs/eval_splits.yaml` labels train businesses by type **for evaluation only**:
- `dev`: used for design (prompts, few-shot pool, rules, vocabulary);
- `val_business`: unseen businesses of seen types;
- `val_type`: whole unseen business types (VLXD, nhà hàng).

Strict mode for `val_type` removes every column name / file keyword / table kind learned only
from those types (`DATAMATE_VOCAB_MASK=configs/vocab_mask_holdout.json`) and can hide READMEs
(`DATAMATE_IGNORE_README=1`).

## Models
(stage b) — to be declared here: name, parameter count, license, release date.

## Tests
```
pip install -r requirements.txt
pytest -q
```
