"""Validation groups (evaluation only): dev / val_business / val_type."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import yaml


@dataclass
class EvalSplits:
    biz_type: dict[str, str] = field(default_factory=dict)
    holdout_types: set[str] = field(default_factory=set)
    holdout_businesses: set[str] = field(default_factory=set)

    def group(self, biz: str) -> str:
        t = self.biz_type.get(biz, "unknown")
        if t in self.holdout_types:
            return "val_type"        # unseen business type
        if biz in self.holdout_businesses:
            return "val_business"    # seen type, unseen business
        return "dev"

    def design_businesses(self, all_biz) -> list[str]:
        return [b for b in all_biz if self.group(b) == "dev"]


def load_splits(path: str | None = None) -> EvalSplits:
    path = path or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "configs", "eval_splits.yaml")
    if not os.path.exists(path):
        return EvalSplits()
    cfg = yaml.safe_load(open(path, encoding="utf-8")) or {}
    bt = {b: t for t, lst in (cfg.get("business_types") or {}).items() for b in lst}
    return EvalSplits(bt, set(cfg.get("holdout_types") or []), set(cfg.get("holdout_businesses") or []))
