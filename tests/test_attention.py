import unittest

from limen.attention import Attention
from limen.bus import Broadcast, Proposal
from limen.config import AttentionConfig


def prop(content: str, salience: float, author="t", coalition=None) -> Proposal:
    return Proposal(author=author, content=content, salience=salience,
                    coalition=coalition)


class TestAttention(unittest.TestCase):
    def setUp(self):
        self.att = Attention(AttentionConfig())

    def test_deterministic_scoring(self):
        p = prop("migrate the blog to a static site", 0.8)
        s1 = self.att.score(p, [], "")
        s2 = self.att.score(p, [], "")
        self.assertAlmostEqual(s1, s2)

    def test_ignition_threshold_blocks_weak_bids(self):
        report = self.att.select([prop("meh", 0.1)], [], "", budget_tokens=500)
        self.assertFalse(report.ignited)
        self.assertEqual(report.winners, [])

    def test_strong_bid_ignites(self):
        report = self.att.select(
            [prop("URGENT user question about billing", 0.9)],
            [], "", budget_tokens=500,
        )
        self.assertTrue(report.ignited)
        self.assertEqual(len(report.winners), 1)

    def test_novelty_discounts_repeats(self):
        content = "the same thought about database backups again"
        recent = [Broadcast(proposal=prop(content, 0.9), priority=0.9,
                            tick=1, ttl=3)]
        fresh = self.att.score(prop("completely unrelated gardening idea", 0.7),
                               recent, "")
        repeat = self.att.score(prop(content, 0.7), recent, "")
        self.assertGreater(fresh, repeat)

    def test_habituation_suppresses_chronic_winners(self):
        p = prop("nagging thought about the deadline", 0.8)
        first = self.att.score(p, [], "")
        for _ in range(3):  # win the auction three times
            self.att.select([p], [], "", budget_tokens=500)
        habituated = self.att.score(p, [], "")
        self.assertLess(habituated, first * 0.7)

    def test_habituation_decays_back(self):
        p = prop("a passing concern", 0.8)
        self.att.select([p], [], "", budget_tokens=500)
        level = self.att.habituation.level(p)
        for _ in range(20):
            self.att.end_of_tick()
        self.assertLess(self.att.habituation.level(p), level * 0.2)

    def test_coalitions_pool_strength(self):
        solo = prop("weak evidence A", 0.30)
        a = prop("weak evidence A", 0.30, coalition="c1")
        b = prop("weak evidence B", 0.30, coalition="c1")
        base = self.att.select([solo], [], "", budget_tokens=500)
        allied = self.att.select([a, b], [], "", budget_tokens=500)
        self.assertGreater(allied.top_priority(), base.top_priority())

    def test_goal_relevance_amplifies(self):
        goal = "ship the billing migration safely"
        on_goal = self.att.score(prop("billing migration step is ready", 0.6),
                                 [], goal)
        off_goal = self.att.score(prop("interesting bird outside", 0.6),
                                  [], goal)
        self.assertGreater(on_goal, off_goal)

    def test_budget_limits_admissions(self):
        big = prop("x " * 900, 0.9)              # ~900 tokens, exceeds budget
        small = prop("small important note", 0.85)
        report = self.att.select([big, small], [], "", budget_tokens=200)
        self.assertTrue(report.ignited)
        contents = [p.content for p, _ in report.winners]
        self.assertIn(small.content, contents)


if __name__ == "__main__":
    unittest.main()
