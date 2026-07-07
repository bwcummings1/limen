"""limen.attention — the auction that decides what becomes conscious.

Every tick, all specialists submit Proposals; this module scores them and
either IGNITES (winners enter the workspace and are broadcast) or stays
quiet (an idle tick — nothing cleared the threshold).

The priority formula, term by term (all weights in [attention] config):

    priority(p) = salience
                × (α + (1−α)·novelty)        # repeats are discounted…
                × (1 − β·habituation)        # …and chronic repeaters more so
                × (γ + (1−γ)·goal_relevance) # goal-relevant content amplified
                + coalition_bonus            # allies pool strength

  salience        the author's own urgency estimate — trust, but modulate.
  novelty         1 − max similarity to the last N broadcasts. A mind that
                  can't discount repetition ruminates.
  habituation     per-(author,topic) fatigue: each auction WIN adds
                  habituation_gain, decaying by habituation_decay per tick.
                  Novelty compares content; habituation tracks *who keeps
                  winning about what*. Both are needed: novelty stops echo,
                  habituation stops monomania.
  goal_relevance  similarity to the active goal stack — top-down attention,
                  vs. the bottom-up salience term.
  coalitions      proposals sharing a coalition tag add coalition_bonus ×
                  each ally's raw score: weak evidence that agrees can
                  outbid strong evidence standing alone. (GWT: processor
                  coalitions compete for access.)

IGNITION: if the best priority < ignition_threshold, nothing becomes
conscious. Sub-threshold content simply never happened, cognitively — that
threshold is the limen the project is named for.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from .bus import Broadcast, Proposal
from .config import AttentionConfig
from .util import clamp, keywords, similarity, stable_hash, truncate


@dataclass
class AuctionReport:
    ignited: bool
    threshold: float
    scored: list[tuple[Proposal, float]] = field(default_factory=list)  # all, desc
    winners: list[tuple[Proposal, float]] = field(default_factory=list)

    def top_priority(self) -> float:
        return self.scored[0][1] if self.scored else 0.0


class Habituation:
    """Fatigue tracker keyed by (author, topic-hash of content keywords)."""

    def __init__(self, gain: float, decay: float) -> None:
        self.gain = gain
        self.decay_rate = decay
        self.levels: dict[str, float] = {}

    @staticmethod
    def key(p: Proposal) -> str:
        topic = " ".join(sorted(keywords(p.content, 6)))
        return f"{p.author}:{stable_hash(topic, 8)}"

    def level(self, p: Proposal) -> float:
        return self.levels.get(self.key(p), 0.0)

    def reinforce(self, p: Proposal) -> None:
        k = self.key(p)
        self.levels[k] = clamp(self.levels.get(k, 0.0) + self.gain, 0.0, 0.95)

    def decay(self) -> None:
        self.levels = {
            k: v * self.decay_rate
            for k, v in self.levels.items()
            if v * self.decay_rate > 0.01
        }


class Attention:
    def __init__(self, config: AttentionConfig) -> None:
        self.cfg = config
        self.habituation = Habituation(config.habituation_gain, config.habituation_decay)

    # ---------------------------------------------------------------- scoring

    def _novelty(self, p: Proposal, recent: list[Broadcast]) -> float:
        if not recent:
            return 1.0
        window = recent[-self.cfg.recent_window:]
        return 1.0 - max(similarity(p.content, b.content) for b in window)

    def _goal_relevance(self, p: Proposal, goal_text: str) -> float:
        if not goal_text:
            return 0.5  # no goals: neither amplified nor suppressed
        return similarity(p.content, goal_text)

    def score(self, p: Proposal, recent: list[Broadcast], goal_text: str) -> float:
        a, b, g = self.cfg.novelty_floor, self.cfg.habituation_strength, self.cfg.goal_floor
        s = clamp(p.salience)
        nov = self._novelty(p, recent)
        hab = self.habituation.level(p)
        rel = self._goal_relevance(p, goal_text)
        return s * (a + (1 - a) * nov) * (1 - b * hab) * (g + (1 - g) * rel)

    # ---------------------------------------------------------------- auction

    def select(
        self,
        proposals: list[Proposal],
        recent_broadcasts: list[Broadcast],
        goal_text: str,
        budget_tokens: int,
    ) -> AuctionReport:
        if not proposals:
            return AuctionReport(ignited=False, threshold=self.cfg.ignition_threshold)

        base = {p.id: self.score(p, recent_broadcasts, goal_text) for p in proposals}

        # Coalition pooling: allies add a fraction of their raw scores.
        by_coalition: dict[str, list[Proposal]] = {}
        for p in proposals:
            if p.coalition:
                by_coalition.setdefault(p.coalition, []).append(p)
        final = dict(base)
        for members in by_coalition.values():
            if len(members) < 2:
                continue
            for p in members:
                allies = sum(base[q.id] for q in members if q.id != p.id)
                final[p.id] = clamp(base[p.id] + self.cfg.coalition_bonus * allies)

        ranked = sorted(proposals, key=lambda p: final[p.id], reverse=True)
        scored = [(p, final[p.id]) for p in ranked]

        report = AuctionReport(
            ignited=False, threshold=self.cfg.ignition_threshold, scored=scored
        )
        if scored[0][1] < self.cfg.ignition_threshold:
            return report  # sub-liminal tick: nothing becomes conscious

        # Fill the workspace budget with above-threshold winners. No single
        # item may occupy more than max_item_fraction of consciousness:
        # oversized proposals are truncated to fit — capacity forces
        # abstraction, which is half the point of a bounded workspace.
        report.ignited = True
        spent = 0
        item_cap = max(20, int(budget_tokens * self.cfg.max_item_fraction))
        for p, score in scored:
            if score < self.cfg.ignition_threshold:
                break
            if p.tokens > item_cap:
                p = replace(p, content=truncate(p.content, item_cap))
            if spent + p.tokens > budget_tokens:
                if report.winners:
                    continue  # doesn't fit; smaller lower-ranked items may
                p = replace(p, content=truncate(p.content, budget_tokens))
            report.winners.append((p, score))
            spent += p.tokens
        for p, _ in report.winners:
            self.habituation.reinforce(p)
        return report

    def end_of_tick(self) -> None:
        self.habituation.decay()
