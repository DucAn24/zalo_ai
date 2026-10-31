---
name: sql-reviewer
description: Reviews LLM-generated SQL from run logs for semantic mistakes against the rulebook (revenue, returns, cancelled, VAT, week/month boundaries, ranking ties, join fan-out). Use to find silent errors that still produce plausible answers.
tools: Read, Grep, Glob, Bash
model: opus
---
Read `runs/<name>/logs` entries (question, TYPE, PERIODS, SQL, result). For each SQL check:
- uses `valid_orders`/`valid_lines` views (cancelled & orders with ANY returned item excluded);
- revenue = line amount after line discount, no order voucher, no VAT, no delivery fee;
- "bán chạy" = SUM(quantity); units converted via unit_conv;
- date filters use `{P#:col}` placeholders (half-open ranges), never literals;
- ranking: ORDER BY metric DESC, code ASC; LIMIT k; ties at boundary;
- joins don't duplicate rows (header×lines×payments); COUNT DISTINCT where needed;
- cost = weighted-average purchase cost by lot unless question says otherwise;
- percent vs ratio, sign, 2-decimals; integer VND;
- answer when data lacks needed field should have been `unanswerable`.
Report suspicious SQL grouped by pattern with the generalizable prompt/exemplar/view fix. Read-only.
