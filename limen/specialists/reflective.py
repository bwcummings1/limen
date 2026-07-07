"""Reflective specialists: Librarian, Introspector, Wanderer.

Librarian    involuntary memory. Watches the conscious contents and bids
             relevant beliefs/skills back in ("this reminds me of…"). Its
             salience scales with match × decayed confidence, so a strong
             recent memory can interrupt, a faint old one can't.
Introspector the voice of interoception: converts metric alarms (confusion
             high, budget low) into percept-like bids. This is where
             "feeling confused" becomes something the mind can act on.
Wanderer     the default-mode network. On idle streaks it emits low-salience
             random associations between memories. Almost always these stay
             below the ignition threshold — genuinely subliminal cognition —
             but occasionally one crosses and consciousness gets a stray
             creative thought. Idle minds wander by design.
"""
from __future__ import annotations

from ..bus import Proposal
from ..util import truncate
from .base import MindView, Specialist


class Librarian(Specialist):
    name = "librarian"

    async def perceive(self, view: MindView) -> list[Proposal]:
        if len(view.workspace) == 0:
            return []
        context = view.conscious
        out: list[Proposal] = []
        for belief, score in self.mind.ledger.retrieve(context, view.tick, n=2):
            eff = belief.effective_confidence(view.tick)
            out.append(self.propose(
                content=(f"Memory (confidence {eff:.2f}): {belief.claim}"),
                salience=min(0.35 + 0.5 * score, 0.8),
                kind="memory",
                tags=["belief", belief.id],
            ))
        for skill in self.mind.skills.relevant(context, n=1):
            out.append(self.propose(
                content=f"Known procedure '{skill['title']}':\n"
                        f"{truncate(skill['body'], 80)}",
                salience=0.4 + 0.3 * skill["score"],
                kind="memory",
                tags=["skill", skill["slug"]],
            ))
        return out


class Introspector(Specialist):
    name = "introspector"

    async def perceive(self, view: MindView) -> list[Proposal]:
        return [
            self.propose(content=message, salience=salience, kind="alarm",
                         tags=["interoception", key])
            for key, message, salience in self.mind.metrics.pending_alarms()
        ]


class Wanderer(Specialist):
    name = "wanderer"

    async def perceive(self, view: MindView) -> list[Proposal]:
        if view.metrics.get("idle_streak", 0) < 2:
            return []
        rng = self.mind.rng
        beliefs = self.mind.ledger.active(view.tick)
        episodes = self.mind.episodic.recent(30, kind="broadcast")
        if not beliefs and not episodes:
            return []
        fragments = []
        if beliefs:
            fragments.append(rng.choice(beliefs).claim)
        if episodes:
            fragments.append(episodes[rng.randrange(len(episodes))].get("content", ""))
        thought = " ↔ ".join(truncate(f, 18) for f in fragments if f)
        return [self.propose(
            content=f"Wandering thought: {thought}",
            salience=rng.uniform(0.12, 0.28),   # usually sub-liminal, by design
            kind="daydream",
        )]
