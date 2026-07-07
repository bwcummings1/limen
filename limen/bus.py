"""limen.bus — the datatypes that flow through a mind.

Global Workspace Theory vocabulary, made concrete:

  Percept    raw material arriving at the edge of the mind (a user message,
             a fired reminder, an interoceptive alarm). Percepts are inputs
             to specialists; they are not yet conscious.
  Proposal   a specialist's bid for consciousness: "this content, at this
             salience, deserves the workspace." Proposals compete in the
             attention auction each tick.
  Broadcast  a proposal that won the auction and crossed the ignition
             threshold. Broadcasts ARE the conscious contents: every
             specialist sees every broadcast on the next tick.

Nothing else crosses subsystem boundaries. If you can serialize these three
dataclasses, you can serialize the entire stream of consciousness.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any

from .util import estimate_tokens, new_id


@dataclass
class Percept:
    """Pre-conscious input. `source` identifies the sensory channel."""

    source: str                      # "user" | "future_self" | "interoception" | "tool" | ...
    content: str
    salience_hint: float = 0.5       # channel's own urgency estimate, [0,1]
    tags: list[str] = field(default_factory=list)
    tick: int = -1
    id: str = field(default_factory=lambda: new_id("pct"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Proposal:
    """A specialist's bid in the attention auction.

    salience      the specialist's own estimate of importance, [0,1].
    coalition     optional tag; proposals sharing a coalition tag pool their
                  strength (see attention.py) — the GWT notion that
                  processors form coalitions to win the workspace.
    kind          routing hint for downstream specialists, e.g. "question",
                  "plan", "risk", "reminder", "answer", "lesson", "alarm".
    meta          free-form structured payload (never rendered to prompts).
    """

    author: str
    content: str
    salience: float
    kind: str = "note"
    coalition: str | None = None
    tags: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    tick: int = -1
    id: str = field(default_factory=lambda: new_id("prp"))

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.content)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Broadcast:
    """A proposal after ignition: conscious content, visible to all.

    priority   the final auction score that won (for the record and for
               eviction ordering inside the workspace).
    ttl        remaining ticks of residence in the workspace; decremented
               each tick, evicted at 0 (working-memory decay).
    """

    proposal: Proposal
    priority: float
    tick: int
    ttl: int
    id: str = field(default_factory=lambda: new_id("bcast"))

    @property
    def content(self) -> str:
        return self.proposal.content

    @property
    def author(self) -> str:
        return self.proposal.author

    @property
    def kind(self) -> str:
        return self.proposal.kind

    @property
    def tokens(self) -> int:
        return self.proposal.tokens

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tick": self.tick,
            "ttl": self.ttl,
            "priority": round(self.priority, 4),
            "proposal": self.proposal.to_dict(),
        }


def to_jsonl(obj: Any) -> str:
    """Single-line JSON for the episodic log."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
