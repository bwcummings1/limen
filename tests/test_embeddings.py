"""Embeddings seam tests: cosine, calibration, heuristic fallback and
max-blend, the vector cache, and Mind wiring. All offline — a fake embedder
stands in for the network backends."""
import tempfile
import unittest
from pathlib import Path

from limen.config import Config
from limen.embeddings import (
    EmbeddingCache,
    HTTPEmbedder,
    OpenAICompatEmbedder,
    SemanticSimilarity,
    build_similarity,
    cosine,
)
from limen.util import (
    heuristic_similarity,
    set_similarity_backend,
    similarity,
)


class FakeEmbedder(HTTPEmbedder):
    """Deterministic vectors from a fixed table; None for unknown text."""

    name = "fake"

    def __init__(self, table: dict[str, list[float]]):
        super().__init__(EmbeddingCache(Path(tempfile.mkdtemp()), enabled=False))
        self.table = table
        self.embed_calls = 0

    def embed(self, text: str):
        self.embed_calls += 1
        return self.table.get(text)


class TestCosine(unittest.TestCase):
    def test_identical_and_orthogonal(self):
        self.assertAlmostEqual(cosine([1, 0], [1, 0]), 1.0)
        self.assertAlmostEqual(cosine([1, 0], [0, 1]), 0.0)

    def test_zero_vector_safe(self):
        self.assertEqual(cosine([0, 0], [1, 2]), 0.0)


class TestSemanticSimilarity(unittest.TestCase):
    A = "we are staying on wordpress"
    B = "the migration is off"          # paraphrase: near-zero surface overlap
    C = "bird watching in the park"

    def setUp(self):
        self.emb = FakeEmbedder({
            self.A: [1.0, 0.0],
            self.B: [0.96, 0.28],        # cos(A,B) ≈ 0.96 — same meaning
            self.C: [0.0, 1.0],          # cos(A,C) = 0    — unrelated
        })
        self.sim = SemanticSimilarity(self.emb, calibration_floor=0.55)

    def test_paraphrase_scores_above_heuristic(self):
        h = heuristic_similarity(self.A, self.B)
        s = self.sim(self.A, self.B)
        self.assertGreater(s, h, "embedding must lift a true paraphrase")
        self.assertGreater(s, 0.8)

    def test_unrelated_falls_back_to_heuristic_exactly(self):
        # cosine 0 scales below the floor to 0, so max-blend returns the
        # heuristic score unchanged — the backend never *raises* noise.
        self.assertAlmostEqual(
            self.sim(self.A, self.C), heuristic_similarity(self.A, self.C)
        )

    def test_max_blend_never_below_heuristic(self):
        # Same text: embeddings unknown for this string -> fallback, and
        # the result must equal the (perfect) heuristic score.
        t = "verbatim repeated thought"
        self.assertAlmostEqual(self.sim(t, t), heuristic_similarity(t, t))

    def test_embedding_failure_falls_back(self):
        s = self.sim(self.A, "text with no vector")
        self.assertAlmostEqual(
            s, heuristic_similarity(self.A, "text with no vector")
        )


class TestBackendSeam(unittest.TestCase):
    def tearDown(self):
        set_similarity_backend(None)   # never leak into other tests

    def test_backend_installs_and_clears(self):
        marker = lambda a, b: 0.42
        set_similarity_backend(marker)
        self.assertEqual(similarity("x", "y"), 0.42)
        set_similarity_backend(None)
        self.assertEqual(similarity("x", "y"), heuristic_similarity("x", "y"))

    def test_build_similarity_none_kind(self):
        cfg = Config()   # embeddings.kind defaults to "none"
        self.assertIsNone(build_similarity(cfg, Path(tempfile.mkdtemp())))

    def test_build_similarity_rejects_unknown_kind(self):
        cfg = Config()
        cfg.embeddings.kind = "wibble"
        with self.assertRaises(ValueError):
            cfg.validate()


class TestOpenAICompatEmbedder(unittest.TestCase):
    """The protocol embedder: request shape, URL normalization, auth
    header optionality, and per-(host, model) cache keying."""

    def _emb(self, base_url, model="", api_key=None):
        return OpenAICompatEmbedder(
            EmbeddingCache(Path(tempfile.mkdtemp()), enabled=False),
            base_url=base_url, model=model, api_key=api_key,
        )

    def test_url_normalization(self):
        self.assertEqual(self._emb("http://localhost:1234").url,
                         "http://localhost:1234/v1/embeddings")
        self.assertEqual(self._emb("http://localhost:1234/v1").url,
                         "http://localhost:1234/v1/embeddings")
        self.assertEqual(self._emb("http://localhost:1234/v1/").url,
                         "http://localhost:1234/v1/embeddings")

    def test_request_shape_local_server(self):
        emb = self._emb("http://localhost:1234/v1", model="nomic-embed-text")
        url, headers, body = emb._request("hello")
        self.assertEqual(body, {"input": ["hello"], "model": "nomic-embed-text"})
        self.assertNotIn("authorization", headers)   # local: no key needed

    def test_request_shape_with_key_and_no_model(self):
        emb = self._emb("https://api.example.com", api_key="sk-test")
        url, headers, body = emb._request("hello")
        self.assertEqual(headers["authorization"], "Bearer sk-test")
        self.assertNotIn("model", body)              # server's loaded model

    def test_extract_openai_shape(self):
        emb = self._emb("http://localhost:1234")
        vec = emb._extract({"data": [{"embedding": [0.1, 0.2]}]})
        self.assertEqual(vec, [0.1, 0.2])

    def test_cache_keys_distinguish_hosts(self):
        a = self._emb("http://localhost:1234", model="m")
        b = self._emb("http://localhost:11434", model="m")
        self.assertNotEqual(a.name, b.name)   # same model, different backend

    def test_config_requires_base_url(self):
        cfg = Config()
        cfg.embeddings.kind = "openai"
        with self.assertRaises(ValueError):
            cfg.validate()
        cfg.embeddings.base_url = "http://localhost:1234/v1"
        cfg.validate()   # now fine


class TestEmbeddingCache(unittest.TestCase):
    def test_roundtrip_and_memory_hit(self):
        with tempfile.TemporaryDirectory() as tmp:
            c1 = EmbeddingCache(Path(tmp), enabled=True)
            c1.put("k", [0.1, 0.2])
            self.assertEqual(c1.get("k"), [0.1, 0.2])
            # A fresh instance reads from disk.
            c2 = EmbeddingCache(Path(tmp), enabled=True)
            self.assertEqual(c2.get("k"), [0.1, 0.2])

    def test_disabled_cache_is_memory_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            c1 = EmbeddingCache(Path(tmp), enabled=False)
            c1.put("k", [1.0])
            self.assertEqual(c1.get("k"), [1.0])          # memory works
            c2 = EmbeddingCache(Path(tmp), enabled=False)
            self.assertIsNone(c2.get("k"))                # nothing persisted


if __name__ == "__main__":
    unittest.main()
