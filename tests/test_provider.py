"""Provider-boundary tests: model-aware payload shapes, per-purpose model
routing, the deterministic cache flag, retry-after parsing, and stop_reason
plumbing. All offline."""
import asyncio
import tempfile
import textwrap
import unittest
from pathlib import Path

from limen.config import Config
from limen.providers.anthropic import AnthropicProvider, _retry_after_secs
from limen.providers.base import (
    BudgetMeter,
    LLMRequest,
    LLMResponse,
    MeteredProvider,
    ResponseCache,
)


def _provider(model: str, routes: dict[str, str] | None = None) -> AnthropicProvider:
    return AnthropicProvider(
        BudgetMeter(tokens_per_day=10 ** 6, day_ticks=10),
        ResponseCache(Path(tempfile.mkdtemp()), enabled=False),
        model=model,
        api_key="test-key-never-used",
        routes=routes,
    )


def _request(**kw) -> LLMRequest:
    return LLMRequest(
        system="s", messages=[{"role": "user", "content": "hi"}], **kw
    )


class TestPayloadShapes(unittest.TestCase):
    """The Messages API surface differs by model generation; the payload
    builder must adapt or current-gen models 400 on every call."""

    def test_legacy_models_keep_temperature(self):
        for model in ("claude-sonnet-4-6", "claude-haiku-4-5", "claude-opus-4-6"):
            p = _provider(model)._payload(_request(temperature=0.7))
            self.assertEqual(p["temperature"], 0.7, model)
            self.assertNotIn("thinking", p, model)

    def test_current_gen_drops_sampling(self):
        for model in ("claude-opus-4-7", "claude-opus-4-8", "claude-fable-5"):
            p = _provider(model)._payload(_request(temperature=0.7))
            self.assertNotIn("temperature", p, model)
            self.assertNotIn("thinking", p, model)

    def test_sonnet5_disables_adaptive_thinking(self):
        p = _provider("claude-sonnet-5")._payload(_request())
        self.assertNotIn("temperature", p)
        self.assertEqual(p["thinking"], {"type": "disabled"})

    def test_sonnet46_not_mistaken_for_sonnet5(self):
        p = _provider("claude-sonnet-4-6")._payload(_request(temperature=0.3))
        self.assertIn("temperature", p)
        self.assertNotIn("thinking", p)

    def test_core_fields_always_present(self):
        p = _provider("claude-opus-4-8")._payload(_request(max_tokens=123))
        self.assertEqual(p["model"], "claude-opus-4-8")
        self.assertEqual(p["max_tokens"], 123)
        self.assertEqual(p["system"], "s")
        self.assertEqual(p["messages"], [{"role": "user", "content": "hi"}])


class TestPurposeRouting(unittest.TestCase):
    """[provider.models] routes a request's purpose to a model; the payload
    capability rules must follow the routed model, not the default."""

    def test_routed_purpose_uses_override_model(self):
        prov = _provider("claude-opus-4-8", routes={"oracle": "claude-haiku-4-5"})
        p = prov._payload(_request(purpose="oracle", temperature=0.8))
        self.assertEqual(p["model"], "claude-haiku-4-5")
        # Haiku is a legacy-surface model: temperature must be sent.
        self.assertEqual(p["temperature"], 0.8)

    def test_unrouted_purpose_falls_back_to_default(self):
        prov = _provider("claude-opus-4-8", routes={"oracle": "claude-haiku-4-5"})
        p = prov._payload(_request(purpose="planner", temperature=0.7))
        self.assertEqual(p["model"], "claude-opus-4-8")
        # Opus 4.8 rejects sampling params: temperature must be omitted.
        self.assertNotIn("temperature", p)

    def test_capability_rules_follow_routed_model(self):
        prov = _provider("claude-haiku-4-5", routes={"speaker": "claude-sonnet-5"})
        p = prov._payload(_request(purpose="speaker"))
        self.assertEqual(p["model"], "claude-sonnet-5")
        self.assertNotIn("temperature", p)
        self.assertEqual(p["thinking"], {"type": "disabled"})

    def test_cache_keyed_by_routed_model(self):
        async def run():
            with tempfile.TemporaryDirectory() as tmp:
                prov = CountingProvider(Path(tmp))
                prov.routes = {"oracle_merge": "other-model"}
                a = _request(purpose="consolidation", deterministic=True)
                b = _request(purpose="oracle_merge", deterministic=True)
                await prov.complete(a)
                await prov.complete(b)   # same content, different routed model
                return prov.raw_calls
        # Identical request bodies must NOT share a cache entry when routed
        # to different models.
        self.assertEqual(asyncio.run(run()), 2)

    def test_config_roundtrip_from_toml(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "limen.toml"
            path.write_text(textwrap.dedent("""
                [provider]
                kind = "mock"
                model = "claude-opus-4-8"

                [provider.models]
                oracle = "claude-haiku-4-5"
                consolidation = "claude-opus-4-8"
            """), encoding="utf-8")
            cfg = Config.load(path)
            self.assertEqual(cfg.provider.models["oracle"], "claude-haiku-4-5")
            self.assertEqual(cfg.provider.models["consolidation"], "claude-opus-4-8")

    def test_config_rejects_non_string_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "limen.toml"
            path.write_text("[provider.models]\noracle = 3\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                Config.load(path)


class TestRetryAfter(unittest.TestCase):
    def test_numeric_header_parses(self):
        self.assertEqual(_retry_after_secs("2"), 2.0)
        self.assertEqual(_retry_after_secs("0.5"), 0.5)

    def test_missing_or_date_form_ignored(self):
        self.assertIsNone(_retry_after_secs(None))
        self.assertIsNone(_retry_after_secs(""))
        self.assertIsNone(_retry_after_secs("Wed, 21 Oct 2026 07:28:00 GMT"))


class CountingProvider(MeteredProvider):
    model = "counting"

    def __init__(self, cache_dir: Path):
        super().__init__(
            BudgetMeter(tokens_per_day=10 ** 9, day_ticks=10),
            ResponseCache(cache_dir, enabled=True),
        )
        self.raw_calls = 0

    async def _raw_complete(self, request: LLMRequest) -> LLMResponse:
        self.raw_calls += 1
        return LLMResponse(
            text="ok", input_tokens=5, output_tokens=5, model=self.model
        )


class TestDeterministicCaching(unittest.TestCase):
    """On models without a temperature knob, cache intent must be explicit."""

    def test_deterministic_flag_caches_despite_temperature(self):
        with tempfile.TemporaryDirectory() as tmp:
            prov = CountingProvider(Path(tmp))
            req = _request(temperature=0.8, deterministic=True)
            r1 = asyncio.run(prov.complete(req))
            r2 = asyncio.run(prov.complete(req))
            self.assertEqual(prov.raw_calls, 1)
            self.assertFalse(r1.cached)
            self.assertTrue(r2.cached)
            self.assertEqual(r2.stop_reason, "end_turn")  # survives roundtrip

    def test_sampled_requests_still_bypass_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            prov = CountingProvider(Path(tmp))
            req = _request(temperature=0.8)   # deterministic defaults to False
            asyncio.run(prov.complete(req))
            asyncio.run(prov.complete(req))
            self.assertEqual(prov.raw_calls, 2)

    def test_legacy_low_temperature_still_caches(self):
        with tempfile.TemporaryDirectory() as tmp:
            prov = CountingProvider(Path(tmp))
            req = _request(temperature=0.0)
            asyncio.run(prov.complete(req))
            asyncio.run(prov.complete(req))
            self.assertEqual(prov.raw_calls, 1)


if __name__ == "__main__":
    unittest.main()
