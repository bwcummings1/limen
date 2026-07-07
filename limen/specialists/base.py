"""limen.specialists.base — the contract every processor signs.

A Specialist is one member of the unconscious audience. Each tick it gets
two chances to participate:

  perceive(view) -> [Proposal]   THE BID PHASE. Read the conscious contents
                                 (view.conscious), fresh percepts, goals and
                                 vitals; return zero or more bids. Heavy
                                 LLM work happens here, because its *output*
                                 must compete for consciousness like
                                 everything else.

  act(broadcasts, view, tools)   THE ACTION PHASE, only on ignition ticks.
                                 React to newly conscious content with
                                 effector calls through the Toolbelt.

Iron rule: specialists never talk to each other. The workspace is the only
channel. If specialist A must influence specialist B, A's content has to
win the auction and become conscious — that bottleneck is not a limitation
of the implementation, it IS Global Workspace Theory.

Specialists hold a reference to the mind for READ access (memory retrieval
at perceive time); all WRITES go through the Toolbelt so they are logged.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..bus import Broadcast, Percept, Proposal
from ..providers.base import BudgetExceeded, LLMRequest

if TYPE_CHECKING:  # avoid import cycle
    from ..mind import Mind
    from ..tools import Toolbelt
    from ..workspace import GlobalWorkspace


@dataclass
class MindView:
    """A specialist's complete sensory frame for one tick."""

    tick: int
    conscious: str                      # workspace.render()
    fresh_percepts: list[Percept]       # arrived this tick (pre-conscious)
    goals_text: str
    metrics: dict[str, Any]
    workspace: "GlobalWorkspace"        # read-only structural queries
    new_broadcasts: list[Broadcast] = field(default_factory=list)  # act phase


class Specialist:
    name = "base"

    def __init__(self, mind: "Mind") -> None:
        self.mind = mind

    async def perceive(self, view: MindView) -> list[Proposal]:
        return []

    async def act(self, broadcasts: list[Broadcast], view: MindView,
                  tools: "Toolbelt") -> None:
        return None

    # ------------------------------------------------------------ LLM helper

    async def ask(self, system: str, user: str, *, max_tokens: int = 300,
                  temperature: float | None = None, purpose: str | None = None
                  ) -> str | None:
        """Guarded LLM call: budget/network failures become interoceptive
        events instead of crashes — a mind should feel errors, not die of
        them."""
        cfg = self.mind.config.provider
        req = LLMRequest(
            system=system,
            messages=[{"role": "user", "content": user}],
            max_tokens=max_tokens,
            temperature=cfg.temperature if temperature is None else temperature,
            purpose=purpose or self.name,
        )
        try:
            resp = await self.mind.provider.complete(req)
            if resp.stop_reason == "refusal":
                # Safety classifiers declined; content is empty or partial.
                self.mind.metrics.note_failure(self.name, "provider refusal")
                return None
            if resp.stop_reason == "max_tokens":
                # Output truncated — still usable, but the mind should feel it.
                self.mind.metrics.note_failure(
                    self.name, f"output truncated at max_tokens={max_tokens}"
                )
            return resp.text.strip()
        except BudgetExceeded as e:
            self.mind.metrics.note_failure(self.name, f"budget: {e}")
            return None
        except Exception as e:
            self.mind.metrics.note_failure(self.name, str(e))
            return None

    def propose(self, content: str, salience: float, kind: str = "note",
                coalition: str | None = None, tags: list[str] | None = None,
                meta: dict[str, Any] | None = None) -> Proposal:
        return Proposal(
            author=self.name, content=content, salience=salience, kind=kind,
            coalition=coalition, tags=tags or [], meta=meta or {},
        )
