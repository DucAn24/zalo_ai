---
name: error-analysis
description: Turn an eval run's failures into ranked root-cause buckets and general fixes, by delegating to the error-analyst and sql-reviewer agents. Use after /eval-run shows wrong or abstained answers.
---
Spawn `error-analyst` on the run dir (and `sql-reviewer` in parallel if the wrong answers are numeric/ranking). Merge into one report: bucket → count → example ids → general fix → files. Then ask the user which top fix to implement; implement it, add a regression test in `tests/`, and re-run `/eval-run` on the same sample.
