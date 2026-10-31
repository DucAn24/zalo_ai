"""Configuration: configs/default.yaml (or CONFIG=path) + environment overrides."""
from __future__ import annotations

import os
from typing import Any

import yaml

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ENV_MAP = {
    "DATA_DIR": ("paths", "data_dir"),
    "RESULT_DIR": ("paths", "result_dir"),
    "CACHE_DIR": ("paths", "cache_dir"),
    "LLM_BASE_URL": ("llm", "base_url"),
    "BASE_URL": ("llm", "base_url"),
    "LLM_MODEL": ("llm", "model"),
    "MODEL": ("llm", "model"),
    "LLM_API_KEY": ("llm", "api_key"),
    "LLM_MAX_TOKENS": ("llm", "max_tokens"),
    "DISABLE_THINKING": ("llm", "disable_thinking"),
    "PA_PENALTY": ("decide", "penalty"),
    "ANSWER_THRESHOLD": ("decide", "answer_threshold"),
    "N_SAMPLES": ("decide", "n_samples"),
    "WORKERS": ("run", "workers"),
    "TIME_BUDGET_S": ("run", "time_budget_s"),
}


def _coerce(old: Any, new: str) -> Any:
    if isinstance(old, bool):
        return new.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(old, int) and not isinstance(old, bool):
        try:
            return int(new)
        except ValueError:
            return new
    if isinstance(old, float):
        try:
            return float(new)
        except ValueError:
            return new
    return new


def load_config(path: str | None = None, overrides: dict | None = None) -> dict:
    path = path or os.environ.get("CONFIG") or os.path.join(_ROOT, "configs", "default.yaml")
    cfg = yaml.safe_load(open(path, encoding="utf-8")) or {}
    for env, (sec, key) in ENV_MAP.items():
        if env in os.environ:
            cfg.setdefault(sec, {})
            cfg[sec][key] = _coerce(cfg[sec].get(key), os.environ[env])
    for k, v in (overrides or {}).items():
        sec, key = k.split(".", 1)
        cfg.setdefault(sec, {})[key] = v
    return cfg


def answer_threshold(cfg: dict) -> float:
    d = cfg.get("decide", {})
    t = d.get("answer_threshold", "auto")
    if t in (None, "auto"):
        p = float(d.get("penalty", 1.0))
        return p / (1.0 + p)
    return float(t)
