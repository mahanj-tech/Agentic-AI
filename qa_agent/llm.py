"""Single gateway for every model call.

* structured outputs (pydantic schema in, validated object out)
* exact cost accounting from the API's own `usage` numbers, per model and per stage
* a content-addressed disk cache, so re-running an unchanged plan costs $0
* a hard budget: once MAX_USD is reached, calls raise BudgetExceeded and the
  caller degrades gracefully (e.g. marks a check UNVERIFIED instead of guessing)
"""
from __future__ import annotations

import base64
import hashlib
import json
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Type, TypeVar

from pydantic import BaseModel

from .config import cfg

T = TypeVar("T", bound=BaseModel)


class BudgetExceeded(RuntimeError):
    pass


class LLMUnavailable(RuntimeError):
    pass


class CostLedger:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.by_model: dict = defaultdict(lambda: {"calls": 0, "cached_calls": 0, "input": 0, "cached_input": 0, "output": 0})
        self.by_stage: dict = defaultdict(lambda: {"calls": 0, "cached_calls": 0, "usd": 0.0})
        self.pricing = cfg.pricing()
        self.started = time.time()

    def usd(self, model: str, inp: int, cached: int, out: int) -> float | None:
        p = self.pricing.get(model)
        if not p:
            return None
        return ((inp - cached) * p["input"] + cached * p.get("cached_input", p["input"]) + out * p["output"]) / 1e6

    def record(self, stage: str, model: str, inp: int, cached: int, out: int, from_cache: bool) -> None:
        with self.lock:
            m = self.by_model[model]
            s = self.by_stage[stage]
            m["calls"] += 1
            s["calls"] += 1
            if from_cache:
                m["cached_calls"] += 1
                s["cached_calls"] += 1
                return
            m["input"] += inp
            m["cached_input"] += cached
            m["output"] += out
            s["usd"] += self.usd(model, inp, cached, out) or 0.0

    @property
    def total_usd(self) -> float:
        return sum(self.usd(k, v["input"], v["cached_input"], v["output"]) or 0.0 for k, v in self.by_model.items())

    def summary(self) -> dict:
        models = {}
        for k, v in self.by_model.items():
            cost = self.usd(k, v["input"], v["cached_input"], v["output"])
            models[k] = {**v, "usd": round(cost, 5) if cost is not None else None, "priced": cost is not None,
                         "rate": self.pricing.get(k)}
        return {
            "total_usd": round(self.total_usd, 5),
            "budget_usd": cfg.max_usd,
            "models": models,
            "stages": {k: {**v, "usd": round(v["usd"], 5)} for k, v in self.by_stage.items()},
            "total_calls": sum(v["calls"] for v in self.by_model.values()),
            "cache_hits": sum(v["cached_calls"] for v in self.by_model.values()),
        }


ledger = CostLedger()
_client = None


def _get_client():
    global _client
    if _client is None:
        try:
            from openai import OpenAI
        except ImportError as e:  # pragma: no cover
            raise LLMUnavailable("openai package not installed") from e
        import os

        if not os.getenv("OPENAI_API_KEY"):
            raise LLMUnavailable("OPENAI_API_KEY is not set")
        _client = OpenAI(base_url=cfg.base_url) if cfg.base_url else OpenAI()
    return _client


def image_part(path: str | Path, detail: str = "low") -> dict:
    data = base64.b64encode(Path(path).read_bytes()).decode()
    mime = "image/jpeg" if str(path).lower().endswith((".jpg", ".jpeg")) else "image/png"
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}", "detail": detail}}


def structured(stage: str, model: str, system: str, user: str | list, schema: Type[T],
               temperature: float = 0.0) -> T:
    """Call `model` and return an instance of `schema`. Cached by exact input."""
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    key = hashlib.sha256(json.dumps([model, messages, schema.model_json_schema()], sort_keys=True).encode()).hexdigest()
    cache_file = Path(cfg.cache_dir) / "llm" / f"{key}.json"

    if cfg.use_cache and cache_file.exists():
        ledger.record(stage, model, 0, 0, 0, from_cache=True)
        return schema.model_validate_json(cache_file.read_text())

    if ledger.total_usd >= cfg.max_usd:
        raise BudgetExceeded(f"LLM budget of ${cfg.max_usd:.2f} reached")

    client = _get_client()
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            resp = client.beta.chat.completions.parse(
                model=model, messages=messages, response_format=schema, temperature=temperature)
            break
        except Exception as e:  # rate limits / transient errors
            last_err = e
            time.sleep(2 ** attempt)
    else:
        raise LLMUnavailable(f"{model} call failed: {last_err}")

    u = resp.usage
    cached = getattr(getattr(u, "prompt_tokens_details", None), "cached_tokens", 0) or 0
    ledger.record(stage, model, u.prompt_tokens, cached, u.completion_tokens, from_cache=False)

    parsed = resp.choices[0].message.parsed
    if parsed is None:
        raise LLMUnavailable(f"{model} refused or returned no parseable output")
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(parsed.model_dump_json())
    return parsed
