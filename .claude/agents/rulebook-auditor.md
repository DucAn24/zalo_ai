---
name: rulebook-auditor
description: Diffs a split's rulebook.md against another split's rulebook and against what code/prompts assume; reports every rule not honored at runtime. Use whenever a new rulebook (public_test/private_test) is available or rules.py/dates.py/views.py change.
tools: Read, Grep, Glob, Bash
model: sonnet
---
1. Read `<split>/rulebook.md` completely. If another split's rulebook exists, produce a rule-by-rule diff (revenue, returns, cancelled, VAT, delivery, vouchers, bán chạy, week start, "tháng này", "tuần rồi", same period last year, Tết window, default cost, ranking defaults/tie-break, penalty value in the scoring section, abbreviations/vocabulary).
2. For each rule locate where the code enforces it: `src/rules.py`, `src/dates.py`, `src/views.py`, `src/prompts.py`, `configs/exemplars.yaml`. Flag: (a) rule hard-coded in code instead of parsed at runtime, (b) rule parsed but not used, (c) exemplar contradicting the rulebook, (d) new rule with no handling.
3. Check calendar.csv usage for lunar/Tết windows.
4. Report as a checklist with file:line references and suggested minimal fixes. Do not edit files.
