"""End-to-end: a mind lives 26 ticks of the demo scenario (mock provider,
seeded) and we assert the whole GWT story actually happened:

  * the user's question ignited into consciousness
  * a goal was created and later completed
  * the oracle forked an ensemble and recorded disagreement
  * the speaker answered the user
  * the reminder was scheduled and fired ~6 ticks later
  * a contradicting user statement flipped the belief ledger correctly
  * sleep ran, distilled lessons, and wrote them as beliefs
  * budget accounting moved and everything stayed within bounds
"""
import tempfile
import unittest

from limen import Config, Mind

MSG1 = ("I'm planning to migrate our blog from WordPress to a static site "
        "generator. Is that a good idea? Also, remind me in a bit to email "
        "Dana about the DNS cutover.")
MSG2 = "Actually, we've decided to stay on WordPress rather than migrate."


class TestFullLife(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cfg = Config()
        cfg.mind.data_dir = cls.tmp.name
        cfg.mind.seed = 7
        cfg.provider.kind = "mock"
        cls.mind = Mind.from_config(cfg)
        cls.results = []
        for tick in range(1, 27):
            if tick == 1:
                cls.mind.stimulate(MSG1)
            if tick == 9:
                cls.mind.stimulate(MSG2)
            cls.results.append(cls.mind.tick())

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    # ------------------------------------------------------------ ignition

    def test_question_ignited_on_tick_one(self):
        r = self.results[0]
        self.assertTrue(r.ignited)
        kinds = {w["kind"] for w in r.winners}
        self.assertIn("question", kinds)

    def test_some_ticks_were_idle(self):
        self.assertTrue(any(not r.ignited for r in self.results),
                        "a mind that ignites every tick has no threshold")

    # -------------------------------------------------------------- oracle

    def test_ensemble_ran_and_disagreement_recorded(self):
        events = self.mind.episodic.recent(200, kind="ensemble")
        self.assertTrue(events)
        self.assertGreaterEqual(self.mind.metrics.last_disagreement, 0.0)

    def test_verdict_became_conscious(self):
        broadcasts = self.mind.episodic.recent(200, kind="broadcast")
        self.assertTrue(any(e["bkind"] == "verdict" for e in broadcasts))

    # ------------------------------------------------------------- speaking

    def test_speaker_answered_the_user(self):
        utterances = [u for r in self.results for u in r.utterances]
        self.assertTrue(utterances)
        joined = " ".join(utterances).lower()
        self.assertTrue("migrate" in joined or "wordpress" in joined
                        or "blog" in joined)

    # ------------------------------------------------------------- reminder

    def test_reminder_scheduled_then_fired(self):
        stimuli = self.mind.episodic.recent(300, kind="stimulus")
        fired = [e for e in stimuli if e["source"] == "future_self"]
        self.assertTrue(fired, "the scheduled reminder never fired")
        self.assertIn("dana", fired[0]["content"].lower())
        # scheduled at tick 1 for +6 → fires at tick 7
        self.assertEqual(fired[0]["tick"], 7)

    def test_reminder_relayed_to_user(self):
        utter = [u for r in self.results for u in r.utterances]
        self.assertTrue(any("dana" in u.lower() for u in utter))

    # ---------------------------------------------------------------- goals

    def test_goal_created_and_completed(self):
        self.assertGreaterEqual(len(self.mind.goals.goals), 1)
        self.assertTrue(any(g["status"] == "done"
                            for g in self.mind.goals.goals))

    # --------------------------------------------------------------- ledger

    def test_belief_written_from_verdict_or_statement(self):
        self.assertGreaterEqual(len(self.mind.ledger.beliefs), 1)

    def test_contradiction_flipped_the_belief(self):
        events = self.mind.episodic.recent(300, kind="contradiction")
        self.assertTrue(events, "user reversal did not register as contradiction")
        active = [b.claim.lower() for b in
                  self.mind.ledger.active(self.mind.clock.tick)]
        self.assertTrue(any("stay on wordpress" in c for c in active))
        contradicted = [b for b in self.mind.ledger.beliefs.values()
                        if b.status == "contradicted"]
        self.assertTrue(contradicted)

    # ---------------------------------------------------------------- sleep

    def test_sleep_ran_and_distilled_lessons(self):
        reports = [r.sleep_report for r in self.results if r.sleep_report]
        self.assertTrue(reports)
        self.assertTrue(reports[0]["lessons"])
        lessons = [b for b in self.mind.ledger.beliefs.values()
                   if "lesson" in b.tags]
        self.assertTrue(lessons)

    # ------------------------------------------------------------ substrate

    def test_budget_accounting_moved(self):
        self.assertGreater(self.mind.provider.stats.calls, 0)
        self.assertGreater(self.mind.provider.budget.spent, 0)

    def test_workspace_stayed_bounded(self):
        cfg = self.mind.config.workspace
        self.assertLessEqual(len(self.mind.workspace), cfg.max_items)
        self.assertLessEqual(self.mind.workspace.total_tokens(),
                             cfg.capacity_tokens)

    def test_determinism_same_seed_same_life(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Config()
            cfg.mind.data_dir = tmp
            cfg.mind.seed = 7
            cfg.provider.kind = "mock"
            twin = Mind.from_config(cfg)
            twin_utter = []
            for tick in range(1, 27):
                if tick == 1:
                    twin.stimulate(MSG1)
                if tick == 9:
                    twin.stimulate(MSG2)
                twin_utter.extend(twin.tick().utterances)
            original = [u for r in self.results for u in r.utterances]
            self.assertEqual(original, twin_utter)


if __name__ == "__main__":
    unittest.main()
