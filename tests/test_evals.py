"""Eval harness smoke tests (offline, mock provider): the runner works,
the full arm passes the flagship scenarios, and at least one ablation
measurably differs from full — the differentiation the harness exists for."""
import unittest

from evals.harness import ARMS, run_matrix, run_once
from evals.scenarios import PROSPECTIVE, RUMINATION


class TestHarness(unittest.TestCase):
    def test_full_arm_passes_prospective_memory(self):
        r = run_once(PROSPECTIVE, ARMS["full"], seed=7)
        self.assertEqual(r["fired_ok"], 1.0)
        self.assertEqual(r["on_time_ok"], 1.0)
        self.assertEqual(r["relayed_ok"], 1.0)

    def test_habituation_ablation_ruminates_more(self):
        full = run_once(RUMINATION, ARMS["full"], seed=7)
        ablated = run_once(RUMINATION, ARMS["no_habituation"], seed=7)
        self.assertEqual(full["first_ignited_ok"], 1.0)
        self.assertGreater(
            ablated["repeat_ignitions"], full["repeat_ignitions"],
            "removing habituation must increase rumination — if it doesn't, "
            "the ablation harness (or the mechanism) is broken",
        )

    def test_matrix_shape_and_pairing(self):
        res = run_matrix([PROSPECTIVE], ["full", "no_threshold"], seeds=[7])
        self.assertIn("prospective_memory", res)
        self.assertEqual(
            set(res["prospective_memory"].keys()), {"full", "no_threshold"}
        )
        for arm in res["prospective_memory"].values():
            self.assertIn("fired_ok", arm)


if __name__ == "__main__":
    unittest.main()
