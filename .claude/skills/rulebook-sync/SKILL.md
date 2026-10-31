---
name: rulebook-sync
description: Check that code honors the rulebook of a given split (train/public_test/private_test), especially when rules differ between splits. Use when a new split or rulebook.md is released.
---
Run the `rulebook-auditor` agent on `<split>/rulebook.md` (with the train rulebook as baseline). Fix only parsing/config in `src/rules.py` / `src/dates.py` / `src/views.py` / prompts so rules are read at runtime; add tests with the new rulebook text as fixture. Also confirm the penalty in the rulebook's scoring section is picked up by `decide.py` (`PA_PENALTY` / auto threshold).
