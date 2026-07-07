"""limen.providers.base — the LLM boundary.

Everything cognitive in LIMEN funnels through exactly one interface:

    response = await provider.complete(LLMRequest(...))

This choke point is where three cross-cutting concerns live:

  1. Budget metering — a mind that can bankrupt its owner is a bug. Every
     call is charged against a per-day token budget *before* it is made
     (estimated) and reconciled *after* (real usage when available). When
     the budget is gone and `hard_stop` is set, calls raise BudgetExceeded,
     which the introspector converts into a conscious alarm.
  2. Caching — identical requests that are *meant* to be deterministic
     (request.deterministic, or legacy temperature≈0) are content-addressed
     and served from disk. Determinism + thrift.
  3. Accounting — every call increments interoceptive counters (calls,
     tokens, failures, latency), which is how the mind *feels* its own
     metabolic cost.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ..util import estimate_tokens, stable_hash


@dataclass
class LLMRequest:
    system: str
    messages: list[dict[str, str]]          # [{"role": "user"|"assistant", "content": str}]
    max_tokens: int = 400
    temperature: float = 0.7
    purpose: str = "general"                # accounting label: "planner", "oracle", ...
    deterministic: bool = False             # cache-eligible; current-gen models drop
                                            # `temperature`, so intent must be explicit

    def cache_key(self, model: str) -> str:
        blob = json.dumps(
            {
                "m": model,
                "s": self.system,
                "msgs": self.messages,
                "t": round(self.temperature, 3),
                "mt": self.max_tokens,
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        return stable_hash(blob, 24)

    @property
    def estimated_input_tokens(self) -> int:
        return estimate_tokens(self.system) + sum(
            estimate_tokens(m["content"]) for m in self.messages
        )


@dataclass
class LLMResponse:
    text: str
    input_tokens: int
    output_tokens: int
    model: str
    cached: bool = False
    latency_secs: float = 0.0
    stop_reason: str = "end_turn"           # "end_turn" | "max_tokens" | "refusal" | ...

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class BudgetExceeded(RuntimeError):
    """Raised when the daily token budget is exhausted and hard_stop is on."""


@dataclass
class BudgetMeter:
    """Token budget over a rolling 'day' measured in ticks.

    spend() is called pre-flight with an estimate; settle() reconciles with
    real usage afterwards. remaining() can go slightly negative between the
    two — that slack is intentional (never block a call already in flight).
    """

    tokens_per_day: int
    day_ticks: int
    hard_stop: bool = True
    spent: int = 0
    day_index: int = 0

    def on_tick(self, tick: int) -> None:
        day = tick // max(self.day_ticks, 1)
        if day != self.day_index:
            self.day_index = day
            self.spent = 0  # new day, fresh budget

    def remaining(self) -> int:
        return self.tokens_per_day - self.spent

    def fraction_remaining(self) -> float:
        if self.tokens_per_day <= 0:
            return 0.0
        return max(0.0, self.remaining() / self.tokens_per_day)

    def spend(self, estimated: int) -> None:
        if self.hard_stop and self.remaining() <= 0:
            raise BudgetExceeded(
                f"daily token budget exhausted ({self.spent}/{self.tokens_per_day})"
            )
        self.spent += estimated

    def settle(self, estimated: int, actual: int) -> None:
        self.spent += actual - estimated  # replace estimate with truth


@dataclass
class ProviderStats:
    calls: int = 0
    cache_hits: int = 0
    failures: int = 0
    retries: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_total: float = 0.0
    by_purpose: dict[str, int] = field(default_factory=dict)

    def record(self, req: LLMRequest, resp: LLMResponse) -> None:
        self.calls += 1
        if resp.cached:
            self.cache_hits += 1
        self.input_tokens += resp.input_tokens
        self.output_tokens += resp.output_tokens
        self.latency_total += resp.latency_secs
        self.by_purpose[req.purpose] = self.by_purpose.get(req.purpose, 0) + 1


class LLMProvider(Protocol):
    model: str
    stats: ProviderStats
    budget: BudgetMeter

    async def complete(self, request: LLMRequest) -> LLMResponse: ...


class ResponseCache:
    """Tiny disk cache: one JSON file per request hash under data_dir/cache."""

    def __init__(self, directory: Path, enabled: bool = True) -> None:
        self.dir = directory
        self.enabled = enabled
        if enabled:
            self.dir.mkdir(parents=True, exist_ok=True)

    def get(self, key: str) -> LLMResponse | None:
        if not self.enabled:
            return None
        path = self.dir / f"{key}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return LLMResponse(**{**data, "cached": True, "latency_secs": 0.0})

    def put(self, key: str, resp: LLMResponse) -> None:
        if not self.enabled:
            return
        payload = {
            "text": resp.text,
            "input_tokens": resp.input_tokens,
            "output_tokens": resp.output_tokens,
            "model": resp.model,
            "stop_reason": resp.stop_reason,
        }
        (self.dir / f"{key}.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )


class MeteredProvider:
    """Shared plumbing: cache -> budget -> _raw_complete -> settle -> record.

    Subclasses implement `_raw_complete`. Only requests flagged deterministic
    (or legacy temperature <= 0.1) are cached, so sampling diversity survives.

    Per-purpose model routing: `routes` maps a request's `purpose` label to a
    model id, falling back to `self.model`. Routing lives here — in the
    provider-agnostic layer — so every current and future provider (Anthropic,
    OpenRouter, ...) inherits it, and the response cache is keyed by the model
    that actually serves the request.
    """

    model: str = "unknown"

    def __init__(self, budget: BudgetMeter, cache: ResponseCache,
                 routes: dict[str, str] | None = None) -> None:
        self.budget = budget
        self.cache = cache
        self.routes = routes or {}
        self.stats = ProviderStats()

    def model_for(self, purpose: str) -> str:
        """The model that serves requests with this purpose label."""
        return self.routes.get(purpose, self.model)

    async def complete(self, request: LLMRequest) -> LLMResponse:
        cacheable = request.deterministic or request.temperature <= 0.1
        key = request.cache_key(self.model_for(request.purpose)) if cacheable else ""
        if cacheable:
            hit = self.cache.get(key)
            if hit is not None:
                self.stats.record(request, hit)
                return hit

        estimate = request.estimated_input_tokens + request.max_tokens
        self.budget.spend(estimate)
        start = time.monotonic()
        try:
            resp = await self._raw_complete(request)
        except Exception:
            self.stats.failures += 1
            self.budget.settle(estimate, request.estimated_input_tokens)
            raise
        resp.latency_secs = time.monotonic() - start
        self.budget.settle(estimate, resp.total_tokens)
        self.stats.record(request, resp)
        if cacheable:
            self.cache.put(key, resp)
        return resp

    async def _raw_complete(self, request: LLMRequest) -> LLMResponse:
        raise NotImplementedError
