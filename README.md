# DataMate — Zalo AI Challenge 2026

Offline agent answering Vietnamese questions over small-business tables (CSV / Excel / SQLite).

> Status: stage (a) done — data loading & cleaning, canonical tables, date resolution, formatter,
> matcher, evaluation. LLM → SQL comes in stage (b); Docker / `predict.sh` in stage (d).

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
  sandbox.py    read-only DuckDB with statement checks and timeout
  formatter.py  answer typing / rounding
  matcher.py    official matching rules + Penalized Accuracy
  evalsplit.py  validation groups (evaluation only)
eval.py         scoring with breakdowns (group / type / category / business)
tools/          oracle_check.py (canonical-layer validation), make_vocab_mask.py (strict eval)
configs/        default.yaml (paths, LLM, thresholds), eval_splits.yaml (evaluation only)
tests/          pytest
```

## Configuration
`configs/default.yaml`, overridable by env: `DATA_DIR`, `RESULT_DIR`, `CACHE_DIR`, `LLM_BASE_URL`,
`LLM_MODEL`, `PA_PENALTY`, `ANSWER_THRESHOLD`, `N_SAMPLES`, `WORKERS`.

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
