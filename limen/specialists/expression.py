"""Expression specialists: Scribe and Speaker.

Scribe   the memory hand. When verdicts or user decisions become conscious,
         it writes them into the belief ledger through the Toolbelt —
         with confidence inherited from the ensemble (a divided verdict is
         stored weakly) and provenance pointing back at the broadcast.
         The ledger's merge/contradiction machinery does the rest.

Speaker  the mouth, with a GWT twist: it does not blurt. When the mind has
         something worth saying (goal + verdict/plan conscious, unspoken),
         Speaker drafts an utterance and bids the DRAFT into consciousness.
         Only when the mind has "heard itself about to speak" — the draft
         won the auction — does Speaker deliver it and close the goal.
         Reminders and acknowledgments skip the draft stage (reflex speech,
         not deliberate speech).
"""
from __future__ import annotations

import re

from ..bus import Broadcast, Proposal
from ..util import truncate
from .base import MindView, Specialist

_DECISION = re.compile(
    r"\b(decided|we will|we won't|actually|going with|chose|no longer|"
    r"instead|cancel|stay(?:ing)? on)\b", re.IGNORECASE,
)
_INTENT = re.compile(
    r"\b(planning to|going to|intend to|about to|we will)\b", re.IGNORECASE,
)


def _sentence_with(pattern: re.Pattern, text: str) -> str | None:
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if pattern.search(sentence):
            return sentence.strip()
    return None


class Scribe(Specialist):
    name = "scribe"

    def __init__(self, mind) -> None:
        super().__init__(mind)
        self._written: set[str] = set()

    async def act(self, broadcasts: list[Broadcast], view: MindView, tools) -> None:
        for b in broadcasts:
            if b.id in self._written:
                continue
            if b.kind == "verdict":
                self._written.add(b.id)
                conf = float(b.proposal.meta.get("confidence", 0.6))
                claim = f"Assessment: {truncate(b.content.splitlines()[0], 45)}"
                tools.remember(claim, confidence=max(0.2, conf * 0.9),
                               tags=["verdict"])
            elif b.kind == "statement" and _DECISION.search(b.content):
                self._written.add(b.id)
                tools.remember(
                    f"User stated: {truncate(b.content, 45)}",
                    confidence=0.9, tags=["user", "decision"],
                )
            elif b.kind == "question" and "user" in b.proposal.tags:
                sentence = _sentence_with(_INTENT, b.content)
                if sentence:
                    self._written.add(b.id)
                    tools.remember(
                        f"User intends: {truncate(sentence, 45)}",
                        confidence=0.8, tags=["user", "intent"],
                    )


class Speaker(Specialist):
    name = "speaker"
    _SYSTEM = (
        "You are the speaker process of an agent mind: reply to the user. "
        "Given the conscious contents — question, verdict (note its "
        "disagreement level), plan, risks — compose a brief helpful reply. "
        "If fork disagreement was high, hedge honestly. Mention any follow-up "
        "the mind scheduled. 2-5 sentences, plain prose."
    )

    # A draft that WON is blocked by the utterance_draft kinds check (and
    # delivery completes the goal); a draft that LOST may be redrafted next
    # tick while a verdict/plan is still conscious — that window is bounded
    # by workspace TTL. Only provider failures cool down.
    _FAILURE_COOLDOWN = 3

    def __init__(self, mind) -> None:
        super().__init__(mind)
        self._acked: set[str] = set()
        self._failed_at: dict[str, int] = {}   # goal id -> tick of failed draft

    # ------------------------------------------------------------- perceive

    def _pending_followups(self) -> str:
        """Render the timekeeper's live intentions for the prompt — the
        system prompt asks the speaker to mention scheduled follow-ups, so
        it must actually see them (a real model would otherwise hallucinate
        or omit them; the mock happened to paper over the gap)."""
        items = list(self.mind.timekeeper.pending.values())[:5]
        if not items:
            return "(none)"
        lines = []
        for i in items:
            if i.due_tick is not None:
                lines.append(f"- '{i.message}' (due at tick {i.due_tick})")
            else:
                lines.append(f"- '{i.message}' (dead-man watching '{i.watch_tag}')")
        return "\n".join(lines)

    async def perceive(self, view: MindView) -> list[Proposal]:
        goals = self.mind.goals.active()
        if not goals:
            return []
        have_answer = {"verdict", "plan"} & view.workspace.kinds_present()
        if not have_answer or "utterance_draft" in view.workspace.kinds_present():
            return []
        goal = goals[0]
        if view.tick - self._failed_at.get(goal["id"], -(10 ** 9)) < self._FAILURE_COOLDOWN:
            return []
        text = await self.ask(
            self._SYSTEM,
            f"Conscious contents:\n{view.conscious}\n\nGoal: {goal['text']}\n\n"
            f"Scheduled follow-ups:\n{self._pending_followups()}",
            max_tokens=220, purpose="speaker",
        )
        if not text:
            self._failed_at[goal["id"]] = view.tick
            return []
        return [self.propose(
            content=text, salience=0.7, kind="utterance_draft",
            meta={"goal_id": goal["id"]},
        )]

    # ------------------------------------------------------------------ act

    async def act(self, broadcasts: list[Broadcast], view: MindView, tools) -> None:
        for b in broadcasts:
            if b.author == self.name and b.kind == "utterance_draft":
                tools.respond(b.content)
                goal_id = b.proposal.meta.get("goal_id")
                if goal_id:
                    tools.complete_goal(goal_id)
            elif b.kind in ("reminder", "alarm") and "future_self" in b.proposal.tags:
                tools.respond(f"⏰ {b.content}")
            elif (b.kind == "statement" and _DECISION.search(b.content)
                    and b.id not in self._acked):
                self._acked.add(b.id)
                tools.respond(
                    "Noted — I've updated my memory accordingly. "
                    "Say the word if anything else changed."
                )
