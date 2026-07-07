import tempfile
import unittest
from pathlib import Path

from limen.config import LedgerConfig
from limen.memory.ledger import BeliefLedger

PROV = {"kind": "test", "ref": "t"}


class TestLedger(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = BeliefLedger(Path(self.tmp.name), LedgerConfig())

    def tearDown(self):
        self.tmp.cleanup()

    def test_half_life_decay(self):
        b, action = self.ledger.assert_claim(
            "the deploy pipeline uses blue-green releases", 0.8, tick=0,
            provenance=PROV, half_life=100,
        )
        self.assertEqual(action, "created")
        self.assertAlmostEqual(b.effective_confidence(0), 0.8, places=5)
        self.assertAlmostEqual(b.effective_confidence(100), 0.4, places=5)
        self.assertAlmostEqual(b.effective_confidence(200), 0.2, places=5)

    def test_reinforcement_noisy_or(self):
        self.ledger.assert_claim("user prefers markdown reports", 0.5,
                                 tick=0, provenance=PROV)
        b, action = self.ledger.assert_claim("user prefers markdown reports",
                                             0.5, tick=1, provenance=PROV)
        self.assertEqual(action, "reinforced")
        self.assertGreater(b.confidence, 0.5)
        self.assertLess(b.confidence, 1.0)
        self.assertEqual(len(b.provenance), 2)

    def test_contradiction_detected_and_reconciled(self):
        old, _ = self.ledger.assert_claim(
            "User is planning to migrate the blog from WordPress to a "
            "static site", 0.85, tick=0, provenance=PROV,
        )
        new, action = self.ledger.assert_claim(
            "User decided to stay on WordPress rather than migrate the blog",
            0.9, tick=5, provenance=PROV,
        )
        self.assertEqual(action, "contradiction")
        self.assertIn(old.id, new.contradicts)
        self.assertEqual(old.status, "contradicted")   # newer + stronger wins
        self.assertEqual(new.status, "active")

    def test_no_false_contradiction_on_unrelated_negation(self):
        self.ledger.assert_claim("the cat likes sunny windowsills", 0.8,
                                 tick=0, provenance=PROV)
        _, action = self.ledger.assert_claim(
            "the build server is not reachable today", 0.8,
            tick=1, provenance=PROV,
        )
        self.assertEqual(action, "created")

    def test_decay_and_prune(self):
        self.ledger.assert_claim("ephemeral detail about lunch", 0.2,
                                 tick=0, provenance=PROV, half_life=10)
        pruned = self.ledger.decay_and_prune(tick=100, floor=0.05)
        self.assertEqual(len(pruned), 1)
        self.assertEqual(len(self.ledger.active(100)), 0)

    def test_retrieval_ranks_by_similarity_times_confidence(self):
        self.ledger.assert_claim("user timezone is UTC+2", 0.9, tick=0,
                                 provenance=PROV)
        self.ledger.assert_claim("the office plant needs water weekly", 0.9,
                                 tick=0, provenance=PROV)
        hits = self.ledger.retrieve("what timezone is the user in?", tick=1)
        self.assertTrue(hits)
        self.assertIn("timezone", hits[0][0].claim)

    def test_persistence_roundtrip(self):
        self.ledger.assert_claim("persistent fact", 0.7, tick=0, provenance=PROV)
        reloaded = BeliefLedger(Path(self.tmp.name), LedgerConfig())
        self.assertEqual(len(reloaded.beliefs), 1)


if __name__ == "__main__":
    unittest.main()
