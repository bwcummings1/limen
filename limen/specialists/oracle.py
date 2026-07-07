"""Oracle — population cognition on demand.

When a high-salience question is conscious and unanswered, the oracle forks
the ensemble (limen.population): K persona forks answer in parallel, the
answers are clustered, disagreement is measured, and a merged verdict —
with the dissent preserved — is bid back into consciousness.

The disagreement number is also written into interoception, where it feeds
the confusion index. A divided ensemble literally makes the mind feel less
sure, which makes the speaker hedge and the introspector consider alarms.
Calibration as a systems property, not a personality trait.
"""
from __future__ import annotations

from ..bus import Proposal
from ..util import truncate
from .base import MindView, Specialist


class Oracle(Specialist):
    name = "oracle"

    _RETRY_COOLDOWN = 3   # ticks before re-forking after a failed attempt

    def __init__(self, mind) -> None:
        super().__init__(mind)
        self._answered: set[str] = set()        # succeeded — never re-fork
        self._attempted: dict[str, int] = {}    # failed attempts cool down

    async def perceive(self, view: MindView) -> list[Proposal]:
        cfg = self.mind.config.population
        candidates = [
            b for b in view.workspace.contents
            if b.kind in cfg.trigger_kinds
            and b.priority >= cfg.min_salience
            and b.id not in self._answered
            and view.tick - self._attempted.get(b.id, -(10 ** 9)) >= self._RETRY_COOLDOWN
        ]
        if not candidates or "verdict" in view.workspace.kinds_present():
            return []
        target = max(candidates, key=lambda b: b.priority)
        self._attempted[target.id] = view.tick

        try:
            result = await self.mind.ensemble.fork(
                question=target.content,
                context=f"Current goals:\n{view.goals_text}",
            )
        except Exception as e:
            # Transient failure: the cooldown lets the fork retry, instead of
            # one API blip permanently silencing the ensemble on this question.
            self.mind.metrics.note_failure(self.name, str(e))
            return []
        self._answered.add(target.id)  # one *successful* ensemble per question

        self.mind.metrics.record_disagreement(result.disagreement)
        self.mind.episodic.log("ensemble", view.tick, {
            "content": f"forked {len(result.answers)} personas on "
                       f"'{truncate(target.content, 20)}' → disagreement "
                       f"{result.disagreement:.2f}",
            "disagreement": round(result.disagreement, 3),
            "clusters": [len(c) for c in result.clusters],
        })
        return [self.propose(
            content=result.merged,
            salience=0.6 + 0.15 * result.confidence,
            kind="verdict",
            coalition=target.proposal.coalition,
            meta={"disagreement": result.disagreement,
                  "confidence": result.confidence},
        )]
