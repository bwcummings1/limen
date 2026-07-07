"""limen.providers — pluggable cortices behind one async interface."""
from __future__ import annotations

from pathlib import Path

from ..config import Config
from .base import (
    BudgetExceeded,
    BudgetMeter,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    ResponseCache,
)
from .mock import MockProvider


def build_provider(config: Config, data_dir: Path) -> LLMProvider:
    budget = BudgetMeter(
        tokens_per_day=config.budget.tokens_per_day,
        day_ticks=config.budget.day_ticks,
        hard_stop=config.budget.hard_stop,
    )
    cache = ResponseCache(data_dir / "cache", enabled=config.provider.cache)
    kind = config.provider.kind.lower()
    if kind == "mock":
        return MockProvider(budget, cache, seed=config.mind.seed or 0)
    if kind == "anthropic":
        from .anthropic import AnthropicProvider  # lazy: needs API key

        return AnthropicProvider(
            budget,
            cache,
            model=config.provider.model,
            timeout=config.provider.timeout_secs,
            max_retries=config.provider.max_retries,
            routes=config.provider.models,
        )
    raise ValueError(f"unknown provider.kind: {config.provider.kind!r}")


__all__ = [
    "LLMProvider",
    "LLMRequest",
    "LLMResponse",
    "BudgetMeter",
    "BudgetExceeded",
    "ResponseCache",
    "build_provider",
]
