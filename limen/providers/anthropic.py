"""limen.providers.anthropic — real cortex via the Anthropic Messages API.

Uses only the stdlib (urllib) so LIMEN keeps its zero-dependency guarantee.
API reference: https://docs.claude.com/en/api/overview

Auth: set the ANTHROPIC_API_KEY environment variable. Model, max_tokens and
temperature come from [provider] in limen.toml (default model:
"claude-opus-4-8" — change it there, never here). A [provider.models] table
routes purposes to different models (cheap forks, expensive consolidation);
routing itself lives in MeteredProvider so future providers inherit it.

The request payload adapts to the configured model, because the Messages
API surface differs across generations:

  * Opus 4.7/4.8, Sonnet 5, Fable 5 — sampling params were removed; sending
    `temperature` returns a 400, so it is omitted.
  * Sonnet 5 — omitting `thinking` runs *adaptive thinking by default*, and
    thinking tokens count against max_tokens; with LIMEN's small per-call
    budgets that silently yields empty text. We disable it explicitly.
  * Everything else (Sonnet 4.6, Haiku 4.5, Opus 4.6 and older) — the
    legacy payload with `temperature` is sent unchanged.

Blocking urllib calls are pushed onto a thread via asyncio.to_thread so the
cognitive cycle's parallel specialist fan-out stays genuinely concurrent.
Retries: exponential backoff with jitter on 429/5xx/timeouts, honoring a
`retry-after` header when the API sends one.
"""
from __future__ import annotations

import asyncio
import json
import os
import random
import urllib.error
import urllib.request

from .base import LLMRequest, LLMResponse, MeteredProvider

_API_URL = "https://api.anthropic.com/v1/messages"
_API_VERSION = "2023-06-01"
_RETRYABLE = {408, 409, 429, 500, 502, 503, 504, 529}

# Model generations whose request surface differs (prefix match on model id).
_NO_SAMPLING_PREFIXES = (
    "claude-opus-4-7",
    "claude-opus-4-8",
    "claude-sonnet-5",
    "claude-fable-5",
    "claude-mythos-5",
)
# Adaptive thinking runs by default when `thinking` is omitted; disable it so
# a 400-token max_tokens buys visible text, not empty thinking blocks.
# (Fable 5 is NOT here: its thinking is always-on and disabling it is a 400.)
_THINKING_OFF_PREFIXES = ("claude-sonnet-5",)


def _retry_after_secs(value: str | None) -> float | None:
    """Parse a numeric retry-after header; date-form values are ignored."""
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


class AnthropicProvider(MeteredProvider):
    def __init__(
        self,
        budget,
        cache,
        model: str = "claude-opus-4-8",
        timeout: float = 60.0,
        max_retries: int = 4,
        api_key: str | None = None,
        routes: dict[str, str] | None = None,   # purpose -> model overrides
    ) -> None:
        super().__init__(budget, cache, routes=routes)
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not self.api_key:
            raise RuntimeError(
                "AnthropicProvider requires ANTHROPIC_API_KEY in the environment "
                "(or provider.kind = \"mock\" in limen.toml to run offline)."
            )

    def _payload(self, request: LLMRequest) -> dict:
        """Model-aware request body (see module docstring for the rules).
        The capability checks follow the *routed* model — with per-purpose
        routing, one mind may span model generations in a single tick."""
        model = self.model_for(request.purpose)
        payload = {
            "model": model,
            "max_tokens": request.max_tokens,
            "system": request.system,
            "messages": request.messages,
        }
        if not model.startswith(_NO_SAMPLING_PREFIXES):
            payload["temperature"] = request.temperature
        if model.startswith(_THINKING_OFF_PREFIXES):
            payload["thinking"] = {"type": "disabled"}
        return payload

    async def _raw_complete(self, request: LLMRequest) -> LLMResponse:
        body = json.dumps(self._payload(request)).encode("utf-8")

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            retry_after: float | None = None
            try:
                raw = await asyncio.to_thread(self._post, body)
                return self._parse(raw)
            except urllib.error.HTTPError as e:
                last_error = e
                if e.code not in _RETRYABLE or attempt == self.max_retries:
                    raise RuntimeError(
                        f"Anthropic API error {e.code}: {e.read()[:300]!r}"
                    ) from e
                retry_after = _retry_after_secs(e.headers.get("retry-after"))
            except (urllib.error.URLError, TimeoutError) as e:
                last_error = e
                if attempt == self.max_retries:
                    raise RuntimeError(f"Anthropic API unreachable: {e}") from e
            self.stats.retries += 1
            delay = min(20.0, (2 ** attempt) + random.random())
            if retry_after is not None:
                delay = max(delay, min(retry_after, 60.0))
            await asyncio.sleep(delay)
        raise RuntimeError(f"Anthropic API failed: {last_error}")  # unreachable

    def _post(self, body: bytes) -> dict:
        req = urllib.request.Request(
            _API_URL,
            data=body,
            method="POST",
            headers={
                "content-type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": _API_VERSION,
            },
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _parse(self, data: dict) -> LLMResponse:
        text = "".join(
            block.get("text", "")
            for block in data.get("content", [])
            if block.get("type") == "text"
        )
        usage = data.get("usage", {})
        return LLMResponse(
            text=text,
            input_tokens=int(usage.get("input_tokens", 0)),
            output_tokens=int(usage.get("output_tokens", 0)),
            model=data.get("model", self.model),
            stop_reason=data.get("stop_reason") or "end_turn",
        )
