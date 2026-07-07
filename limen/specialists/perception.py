"""Perception — the sensory gateway.

Converts fresh Percepts (user messages, fired reminders, interoceptive
alarms) into Proposals. It performs light classification only — question vs
statement, reminder-request extraction — and passes the channel's own
salience hint through. Perception makes things *available* to
consciousness; it does not decide what matters. The auction does.

On ignition it has one effector duty: when a reminder_request it authored
becomes conscious, it schedules the intention with the timekeeper. (The
request had to pass through consciousness first — the mind never commits
to a future it wasn't aware of.)
"""
from __future__ import annotations

import re

from ..bus import Broadcast, Proposal
from .base import MindView, Specialist

_QUESTION = re.compile(
    r"\?|^\s*(is|are|was|should|would|could|can|do|does|did|how|what|why|when|where|which|who)\b",
    re.IGNORECASE,
)
_REMIND = re.compile(
    r"remind me(?:\s+in\s+(\d+)\s+ticks?)?(?:\s+\w+){0,3}?\s+to\s+(.+?)(?:[.!?]|$)",
    re.IGNORECASE,
)
_DEFAULT_REMIND_TICKS = 6


class Perception(Specialist):
    name = "perception"

    def __init__(self, mind) -> None:
        super().__init__(mind)
        self._scheduled: set[str] = set()

    async def perceive(self, view: MindView) -> list[Proposal]:
        out: list[Proposal] = []
        for pct in view.fresh_percepts:
            kind = self._classify(pct.source, pct.content, pct.tags)
            coalition = f"pct:{pct.id}"
            out.append(self.propose(
                content=pct.content,
                salience=pct.salience_hint,
                kind=kind,
                coalition=coalition,
                tags=list(pct.tags) + [pct.source],
            ))
            if pct.source == "user":
                m = _REMIND.search(pct.content)
                if m:
                    in_ticks = int(m.group(1)) if m.group(1) else _DEFAULT_REMIND_TICKS
                    task = m.group(2).strip()
                    out.append(self.propose(
                        content=f"Schedule request: '{task}' in {in_ticks} ticks.",
                        salience=0.75,
                        kind="reminder_request",
                        coalition=coalition,
                        meta={"task": task, "in_ticks": in_ticks},
                    ))
        return out

    @staticmethod
    def _classify(source: str, content: str, tags: list[str]) -> str:
        if source == "future_self":
            return "alarm" if "deadman" in tags else "reminder"
        if source == "interoception":
            return "alarm"
        if source == "user":
            return "question" if _QUESTION.search(content) else "statement"
        return "note"

    async def act(self, broadcasts: list[Broadcast], view: MindView, tools) -> None:
        for b in broadcasts:
            if b.kind == "reminder_request" and b.author == self.name \
                    and b.proposal.id not in self._scheduled:
                self._scheduled.add(b.proposal.id)
                meta = b.proposal.meta
                tools.schedule(meta["task"], in_ticks=meta["in_ticks"])
