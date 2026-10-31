---
name: profile-business
description: Profile a business folder (files, README, columns, dirty values, canonical mapping) via the data-profiler agent. Use when a business fails canonicalization or a new business type appears.
---
Argument: path to `<split>/data/<business_id>`. Delegate to `data-profiler`. Then compare against `python tools/oracle_check.py` output for that business if train answers exist. Propose general fixes in `src/parse.py`, `src/mapping.py`, `src/schema.py` (add vocabulary, not business-specific branches), with a unit test using a minimal synthetic fixture.
