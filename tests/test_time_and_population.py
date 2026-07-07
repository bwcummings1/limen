import asyncio
import tempfile
import unittest
from pathlib import Path

from limen.config import PopulationConfig
from limen.population import Ensemble
from limen.providers.base import BudgetMeter, LLMRequest, LLMResponse, MeteredProvider, ResponseCache
from limen.timekeeper import Timekeeper


class TestTimekeeper(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tk = Timekeeper(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_one_shot_fires_once(self):
        self.tk.schedule("email Dana", due_tick=5, tick=1)
        self.assertEqual(self.tk.collect_due(4, set()), [])
        fired = self.tk.collect_due(5, set())
        self.assertEqual(len(fired), 1)
        self.assertIn("email Dana", fired[0].content)
        self.assertEqual(fired[0].source, "future_self")
        self.assertEqual(self.tk.collect_due(6, set()), [])

    def test_recurring_reschedules(self):
        self.tk.schedule("daily review", due_tick=3, tick=0, every=3)
        self.assertEqual(len(self.tk.collect_due(3, set())), 1)
        self.assertEqual(len(self.tk.collect_due(6, set())), 1)
        self.assertEqual(len(self.tk.pending), 1)  # still armed

    def test_deadman_fires_on_absence(self):
        self.tk.arm_deadman("no heartbeat from backup job!",
                            watch_tag="backup_ok", within=4, tick=0)
        self.assertEqual(self.tk.collect_due(2, set()), [])
        fired = self.tk.collect_due(4, set())
        self.assertEqual(len(fired), 1)
        self.assertIn("DEAD-MAN", fired[0].content)

    def test_deadman_disarmed_by_presence(self):
        self.tk.arm_deadman("alarm", watch_tag="backup_ok", within=4, tick=0)
        self.assertEqual(self.tk.collect_due(2, {"backup_ok"}), [])
        self.assertEqual(self.tk.collect_due(10, set()), [])  # gone
        self.assertEqual(len(self.tk.pending), 0)

    def test_persistence_roundtrip(self):
        self.tk.schedule("survive restart", due_tick=9, tick=1)
        tk2 = Timekeeper(Path(self.tmp.name))
        self.assertEqual(len(tk2.pending), 1)


class ScriptedProvider(MeteredProvider):
    """Returns queued answers in persona order — for controlled clustering."""

    model = "scripted"

    def __init__(self, answers: dict[str, str], merged: str = "merged view"):
        tmp = Path(tempfile.mkdtemp())
        super().__init__(
            BudgetMeter(tokens_per_day=10**9, day_ticks=10),
            ResponseCache(tmp, enabled=False),
        )
        self.answers = answers
        self.merged = merged

    async def _raw_complete(self, request: LLMRequest) -> LLMResponse:
        text = self.merged
        for persona, answer in self.answers.items():
            if f"persona: {persona}" in request.system:
                text = answer
        return LLMResponse(text=text, input_tokens=10, output_tokens=10,
                           model=self.model)


class TestPopulation(unittest.TestCase):
    def _run(self, answers):
        cfg = PopulationConfig(personas=list(answers.keys()))
        ens = Ensemble(cfg, ScriptedProvider(answers))
        return asyncio.run(ens.fork("should we migrate?"))

    def test_consensus_yields_low_disagreement(self):
        same = "Yes, migrate the blog to a static site generator now."
        result = self._run({"a": same, "b": same, "c": same})
        self.assertEqual(len(result.clusters), 1)
        self.assertEqual(result.disagreement, 0.0)
        self.assertEqual(result.confidence, 1.0)

    def test_split_yields_high_disagreement(self):
        result = self._run({
            "a": "Yes, absolutely migrate to the static site generator now.",
            "b": "No, keep WordPress; a migration is pure risk and no gain.",
            "c": "Wait a quarter and gather traffic data before deciding.",
        })
        self.assertGreaterEqual(len(result.clusters), 2)
        self.assertGreater(result.disagreement, 0.5)
        self.assertIn("disagreement", result.merged)


if __name__ == "__main__":
    unittest.main()
