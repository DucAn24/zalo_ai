"""Minimal OpenAI-compatible chat client (vLLM / Ollama / llama.cpp). Standard library only."""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)

_THINK_RE = re.compile(r"<think>.*?</think>", re.S)


class LLMError(RuntimeError):
    pass


@dataclass
class LLMStats:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    seconds: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, usage: dict, dt: float):
        with self.lock:
            self.calls += 1
            self.prompt_tokens += int(usage.get("prompt_tokens", 0) or 0)
            self.completion_tokens += int(usage.get("completion_tokens", 0) or 0)
            self.seconds += dt


class LLMClient:
    def __init__(self, base_url: str, model: str, api_key: str = "EMPTY", temperature: float = 0.0, seed: int = 42,
                 max_tokens: int = 1024, disable_thinking: bool = True, timeout: float = 120.0, retries: int = 3):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.temperature = temperature
        self.seed = seed
        self.max_tokens = max_tokens
        self.disable_thinking = disable_thinking
        self.timeout = timeout
        self.retries = retries
        self.stats = LLMStats()
        self._template_kwargs_ok = True      # flips to False if the server rejects chat_template_kwargs

    @classmethod
    def from_config(cls, cfg: dict) -> "LLMClient":
        c = cfg["llm"]
        return cls(c["base_url"], c["model"], c.get("api_key", "EMPTY"), float(c.get("temperature", 0.0)),
                   int(c.get("seed", 42)), int(c.get("max_tokens", 1024)), bool(c.get("disable_thinking", True)),
                   float(c.get("request_timeout", 120)))

    # ------------------------------------------------------------------ http
    def _post(self, path: str, body: dict) -> dict:
        req = urllib.request.Request(
            self.base_url + path, data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def wait_ready(self, timeout: float = 600.0) -> bool:
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                req = urllib.request.Request(self.base_url + "/models", headers={"Authorization": f"Bearer {self.api_key}"})
                with urllib.request.urlopen(req, timeout=10) as r:
                    if r.status == 200:
                        return True
            except Exception:
                time.sleep(3)
        return False

    # ------------------------------------------------------------------ chat
    def chat(self, messages: list[dict], n: int = 1, temperature: Optional[float] = None,
             max_tokens: Optional[int] = None, seed: Optional[int] = None, stop: Optional[list[str]] = None) -> list[str]:
        msgs = [dict(m) for m in messages]
        use_kwargs = self.disable_thinking and self._template_kwargs_ok
        if self.disable_thinking and not use_kwargs:
            msgs = self._add_no_think(msgs)
        last_err: Exception | None = None
        for attempt in range(self.retries + 1):
            body = {"model": self.model, "messages": msgs, "n": n,
                    "temperature": self.temperature if temperature is None else temperature,
                    "max_tokens": max_tokens or self.max_tokens, "seed": self.seed if seed is None else seed}
            if stop:
                body["stop"] = stop
            if use_kwargs:
                body["chat_template_kwargs"] = {"enable_thinking": False}
            t0 = time.time()
            try:
                resp = self._post("/chat/completions", body)
                self.stats.add(resp.get("usage", {}), time.time() - t0)
                outs = [(c.get("message") or {}).get("content") or "" for c in resp.get("choices", [])]
                return [_THINK_RE.sub("", o).strip() for o in outs]
            except urllib.error.HTTPError as e:
                detail = ""
                try:
                    detail = e.read().decode("utf-8", "replace")[:500]
                except Exception:
                    pass
                if e.code == 400 and use_kwargs and ("chat_template" in detail or "unknown" in detail.lower()
                                                     or "extra" in detail.lower() or "unexpected" in detail.lower()):
                    log.warning("server rejected chat_template_kwargs; falling back to /no_think")
                    self._template_kwargs_ok = False
                    use_kwargs = False
                    msgs = self._add_no_think(msgs)
                    continue
                last_err = LLMError(f"HTTP {e.code}: {detail}")
                if e.code < 500 and e.code != 429:
                    break
            except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as e:
                last_err = e
            time.sleep(min(2 ** attempt, 10))
        raise LLMError(f"LLM request failed: {last_err}")

    @staticmethod
    def _add_no_think(msgs: list[dict]) -> list[dict]:
        for m in reversed(msgs):
            if m["role"] == "user":
                if "/no_think" not in m["content"]:
                    m["content"] = m["content"] + "\n/no_think"
                break
        return msgs
