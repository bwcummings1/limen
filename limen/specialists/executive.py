"""Executive specialists: GoalKeeper, Planner, Critic.

GoalKeeper  turns conscious user requests into goals (which then feed the
            auction's top-down `goal_relevance` term) and nags about stale
            ones. Goals are how the mind stays on task across ticks.
Planner     when a question/goal is conscious without a plan, produces one
            (LLM) and bids it into consciousness.
Critic      the adversarial fork: when a plan or verdict is conscious and
            uncriticized, produces the strongest objection (LLM). Structural
            pessimism — the mind pays a standing cost to argue with itself.
"""
from __future__ import annotations

from ..bus import Broadcast, Proposal
from ..util import truncate
from .base import MindView, Specialist


class GoalKeeper(Specialist):
    name = "goals"

    def __init__(self, mind) -> None:
        super().__init__(mind)
        self._handled: set[str] = set()

    async def perceive(self, view: MindView) -> list[Proposal]:
        # Nag about goals that have been active a long time with no progress.
        out = []
        for g in self.mind.goals.active():
            age = view.tick - g["tick"]
            if age >= 10 and age % 10 == 0:
                out.append(self.propose(
                    content=f"Goal ({g['id']}) has been open {age} ticks: {g['text']}",
                    salience=0.45, kind="goal_stale",
                ))
        return out

    async def act(self, broadcasts: list[Broadcast], view: MindView, tools) -> None:
        for b in broadcasts:
            if b.kind == "question" and b.id not in self._handled:
                self._handled.add(b.id)
                summary = truncate(b.content, 20)
                if not any(
                    summary[:30] in g["text"] for g in self.mind.goals.active()
                ):
                    tools.add_goal(f"Respond to the user about: {summary}")


class Planner(Specialist):
    name = "planner"
    _SYSTEM = (
        "You are the planner process of an agent mind. Given the current "
        "conscious contents, produce a short numbered PLAN (3-5 steps) for "
        "addressing the live question or goal. Begin with 'PLAN:'. Make a plan "
        "that is concrete and checkable."
    )

    # No permanent latch: with a real (nondeterministic, fallible) provider a
    # plan can fail to generate or lose the auction, and the planner must be
    # able to try again. A plan that WON is blocked by the kinds_present
    # check; a lost bid may retry next tick (bounded by the question's TTL);
    # only provider failures cool down, so a broken API isn't hammered.
    _FAILURE_COOLDOWN = 3

    def __init__(self, mind) -> None:
        super().__init__(mind)
        self._failed_at: dict[str, int] = {}   # question broadcast id -> tick

    async def perceive(self, view: MindView) -> list[Proposal]:
        questions = view.workspace.by_kind("question")
        if not questions or "plan" in view.workspace.kinds_present():
            return []
        target = questions[0]
        if view.tick - self._failed_at.get(target.id, -(10 ** 9)) < self._FAILURE_COOLDOWN:
            return []
        text = await self.ask(
            self._SYSTEM,
            f"Conscious contents:\n{view.conscious}\n\nGoals:\n{view.goals_text}",
            max_tokens=250, purpose="planner",
        )
        if not text:
            self._failed_at[target.id] = view.tick
            return []
        return [self.propose(
            content=text, salience=0.65, kind="plan",
            coalition=target.proposal.coalition,
        )]


class Critic(Specialist):
    name = "critic"
    _SYSTEM = (
        "You are the critic (red-team) process of an agent mind. Given the "
        "conscious contents, state the single strongest objection or failure "
        "mode of the current plan/verdict, and one mitigation. Begin with "
        "'RISK:'. Two or three sentences."
    )

    _FAILURE_COOLDOWN = 3   # only failures cool down (see Planner)

    def __init__(self, mind) -> None:
        super().__init__(mind)
        self._failed_at: dict[str, int] = {}   # target broadcast id -> tick

    async def perceive(self, view: MindView) -> list[Proposal]:
        targets = view.workspace.by_kind("plan") + view.workspace.by_kind("verdict")
        fresh = [
            t for t in targets
            if view.tick - self._failed_at.get(t.id, -(10 ** 9)) >= self._FAILURE_COOLDOWN
        ]
        if not fresh or "risk" in view.workspace.kinds_present():
            return []
        target = fresh[0]
        text = await self.ask(
            self._SYSTEM, f"Conscious contents:\n{view.conscious}",
            max_tokens=180, purpose="critic",
        )
        if not text:
            self._failed_at[target.id] = view.tick
            return []
        return [self.propose(content=text, salience=0.55, kind="risk")]
