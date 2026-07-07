"""limen.embeddings — optional semantic similarity backends.

The stdlib heuristic (`util.heuristic_similarity`) is paraphrase-blind:
"we're staying on WordPress" and "the migration is off" share almost no
surface tokens. Six cognitive functions sit on similarity — attention
novelty, workspace dedup, belief merging, contradiction topicality,
ensemble clustering, and retrieval — so an embedding backend upgrades the
whole mind at once through the seam in `util.set_similarity_backend`.

Zero-dependency rule (ADR-1) holds: both backends are raw stdlib urllib,
same as the Anthropic provider.

  voyage   Voyage AI's embeddings API (Anthropic's recommended partner).
           Needs VOYAGE_API_KEY. Fractions of a cent per thousand texts.
  openai   Any server speaking the OpenAI-compatible /v1/embeddings
           protocol — the 2026 lingua franca of local inference: LM Studio
           (localhost:1234), Ollama's /v1 surface (localhost:11434),
           llama.cpp's llama-server, vLLM, TGI, LocalAI, or a hosted
           provider. Target the protocol, not the tool: `base_url` is the
           only thing that changes.
  ollama   Ollama's native /api/embed (kept for compatibility; the openai
           kind pointed at http://localhost:11434/v1 is equivalent).
  none     The heuristic. The mock mind and the test suite stay here.

Design decisions that matter:

  * Every text is embedded ONCE, ever — vectors are content-addressed on
    disk under data_dir/cache/embeddings/ and held in memory.
  * Similarity = max(heuristic, calibrated cosine). Cosine scores of
    unrelated texts sit well above 0 on real models, so raw cosine is
    rescaled by `calibration_floor` before use; taking the max keeps
    near-verbatim dedup exact and makes the backend a strict upgrade —
    it can only *raise* similarity, never break what the heuristic caught.
  * NEGATION IS NOT DELEGATED. Embeddings famously score "we will migrate"
    ≈ "we won't migrate". The ledger's polarity test (`_opposed`) stays a
    regex + keyword heuristic on purpose (ADR-8); embeddings only sharpen
    the *topicality* half of contradiction detection.
  * Failures degrade, never crash: an embedder error falls back to the
    heuristic for that pair and counts on `.failures`.
  * Embedding calls are synchronous and NOT budget-metered — they cost
    ~1000x less than completions and happen inside sync cognitive code.
"""
from __future__ import annotations

import json
import math
import os
import urllib.error
import urllib.request
from pathlib import Path

from .util import clamp, heuristic_similarity, stable_hash


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class EmbeddingCache:
    """Content-addressed vector store: memory dict over one-file-per-hash
    JSON, same pattern as the provider's ResponseCache."""

    def __init__(self, directory: Path, enabled: bool = True) -> None:
        self.dir = directory
        self.enabled = enabled
        self._mem: dict[str, list[float]] = {}
        if enabled:
            self.dir.mkdir(parents=True, exist_ok=True)

    def get(self, key: str) -> list[float] | None:
        if key in self._mem:
            return self._mem[key]
        if not self.enabled:
            return None
        path = self.dir / f"{key}.json"
        if not path.exists():
            return None
        vec = json.loads(path.read_text(encoding="utf-8"))
        self._mem[key] = vec
        return vec

    def put(self, key: str, vec: list[float]) -> None:
        self._mem[key] = vec
        if self.enabled:
            (self.dir / f"{key}.json").write_text(
                json.dumps(vec), encoding="utf-8"
            )


class HTTPEmbedder:
    """Shared plumbing for URL-based embedders: cache -> _post -> cache.

    Subclasses set `name` and implement `_request(text) -> (url, headers,
    body)` and `_extract(response_json) -> list[float]`.
    """

    name = "http"

    def __init__(self, cache: EmbeddingCache, timeout: float = 20.0) -> None:
        self.cache = cache
        self.timeout = timeout
        self.calls = 0
        self.failures = 0

    def embed(self, text: str) -> list[float] | None:
        text = text[:4000]  # embedding models cap input; heads carry the topic
        key = f"{self.name}-{stable_hash(text, 24)}"
        hit = self.cache.get(key)
        if hit is not None:
            return hit
        try:
            url, headers, body = self._request(text)
            req = urllib.request.Request(
                url, data=json.dumps(body).encode("utf-8"),
                method="POST", headers=headers,
            )
            self.calls += 1
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            vec = self._extract(data)
        except Exception:
            self.failures += 1
            return None
        self.cache.put(key, vec)
        return vec

    def _request(self, text: str) -> tuple[str, dict, dict]:
        raise NotImplementedError

    def _extract(self, data: dict) -> list[float]:
        raise NotImplementedError


class VoyageEmbedder(HTTPEmbedder):
    """Voyage AI embeddings (https://docs.voyageai.com). Needs VOYAGE_API_KEY."""

    name = "voyage"
    _URL = "https://api.voyageai.com/v1/embeddings"

    def __init__(self, cache: EmbeddingCache, model: str = "voyage-3.5-lite",
                 timeout: float = 20.0, api_key: str | None = None) -> None:
        super().__init__(cache, timeout)
        self.model = model
        self.api_key = api_key or os.environ.get("VOYAGE_API_KEY", "")
        if not self.api_key:
            raise RuntimeError(
                "VoyageEmbedder requires VOYAGE_API_KEY in the environment "
                "(or embeddings.kind = \"none\" / \"ollama\" in limen.toml)."
            )
        self.name = f"voyage-{model}"  # cache keys are per-model

    def _request(self, text: str) -> tuple[str, dict, dict]:
        return (
            self._URL,
            {"content-type": "application/json",
             "authorization": f"Bearer {self.api_key}"},
            {"input": [text], "model": self.model},
        )

    def _extract(self, data: dict) -> list[float]:
        return data["data"][0]["embedding"]


class OpenAICompatEmbedder(HTTPEmbedder):
    """Any OpenAI-compatible /v1/embeddings server (LM Studio, llama-server,
    vLLM, Ollama's /v1, hosted providers). `api_key` is optional — local
    servers rarely need one; OPENAI_API_KEY is read if present."""

    name = "openai"

    def __init__(self, cache: EmbeddingCache, base_url: str,
                 model: str = "", timeout: float = 20.0,
                 api_key: str | None = None) -> None:
        super().__init__(cache, timeout)
        base = base_url.rstrip("/")
        if not base.endswith("/v1"):
            base += "/v1"
        self.url = f"{base}/embeddings"
        self.model = model
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        # Cache keys are per (host, model): the same model name served by
        # two backends may quantize differently — don't mix their vectors.
        self.name = f"openai-{stable_hash(base, 8)}-{model or 'default'}"

    def _request(self, text: str) -> tuple[str, dict, dict]:
        headers = {"content-type": "application/json"}
        if self.api_key:
            headers["authorization"] = f"Bearer {self.api_key}"
        body: dict = {"input": [text]}
        if self.model:
            body["model"] = self.model
        return self.url, headers, body

    def _extract(self, data: dict) -> list[float]:
        return data["data"][0]["embedding"]


class OllamaEmbedder(HTTPEmbedder):
    """Local embeddings via Ollama's /api/embed (Ollama >= 0.3)."""

    name = "ollama"

    def __init__(self, cache: EmbeddingCache, model: str = "nomic-embed-text",
                 base_url: str = "http://localhost:11434",
                 timeout: float = 20.0) -> None:
        super().__init__(cache, timeout)
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.name = f"ollama-{model}"

    def _request(self, text: str) -> tuple[str, dict, dict]:
        return (
            f"{self.base_url}/api/embed",
            {"content-type": "application/json"},
            {"model": self.model, "input": [text]},
        )

    def _extract(self, data: dict) -> list[float]:
        return data["embeddings"][0]


class SemanticSimilarity:
    """The callable installed via util.set_similarity_backend.

    similarity(a, b) = max( heuristic(a, b),
                            (cosine(e_a, e_b) − floor) / (1 − floor) )

    The floor rescales the model's cosine range (unrelated texts score well
    above 0 on real embedding models) onto [0, 1]; taking the max with the
    heuristic makes the backend a strict upgrade. Any embedding failure
    silently degrades to the heuristic for that pair.
    """

    def __init__(self, embedder: HTTPEmbedder,
                 calibration_floor: float = 0.55) -> None:
        self.embedder = embedder
        self.floor = calibration_floor

    def __call__(self, a: str, b: str) -> float:
        base = heuristic_similarity(a, b)
        if not a or not b:
            return base
        ea = self.embedder.embed(a)
        eb = self.embedder.embed(b)
        if ea is None or eb is None:
            return base
        scaled = clamp((cosine(ea, eb) - self.floor) / (1.0 - self.floor))
        return max(base, scaled)


def build_similarity(config, data_dir: Path) -> SemanticSimilarity | None:
    """From [embeddings] config: the backend to install, or None (heuristic).
    Mirrors providers.build_provider."""
    e = config.embeddings
    kind = e.kind.lower()
    if kind == "none":
        return None
    cache = EmbeddingCache(data_dir / "cache" / "embeddings", enabled=e.cache)
    if kind == "voyage":
        embedder = VoyageEmbedder(
            cache, model=e.model or "voyage-3.5-lite", timeout=e.timeout_secs
        )
    elif kind == "openai":
        if not e.base_url:
            raise ValueError(
                "embeddings.kind = \"openai\" requires embeddings.base_url "
                "(e.g. http://localhost:1234/v1 for LM Studio, "
                "http://localhost:11434/v1 for Ollama)"
            )
        embedder = OpenAICompatEmbedder(
            cache, base_url=e.base_url, model=e.model, timeout=e.timeout_secs
        )
    elif kind == "ollama":
        embedder = OllamaEmbedder(
            cache, model=e.model or "nomic-embed-text",
            base_url=e.base_url or "http://localhost:11434",
            timeout=e.timeout_secs,
        )
    else:
        raise ValueError(f"unknown embeddings.kind: {e.kind!r}")
    return SemanticSimilarity(embedder, calibration_floor=e.calibration_floor)
