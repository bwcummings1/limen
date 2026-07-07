"""limen.specialists — the unconscious audience.

Registry of built-in processors. Adding your own: subclass Specialist,
register it here (or pass instances to Mind directly), list it in
[specialists].enabled. See docs/SPECIALISTS.md for the full contract.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .base import MindView, Specialist
from .expression import Scribe, Speaker
from .executive import Critic, GoalKeeper, Planner
from .oracle import Oracle
from .perception import Perception
from .reflective import Introspector, Librarian, Wanderer

if TYPE_CHECKING:
    from ..mind import Mind

REGISTRY: dict[str, type[Specialist]] = {
    "perception": Perception,
    "goals": GoalKeeper,
    "planner": Planner,
    "critic": Critic,
    "librarian": Librarian,
    "introspector": Introspector,
    "oracle": Oracle,
    "scribe": Scribe,
    "speaker": Speaker,
    "wanderer": Wanderer,
}


def build_specialists(mind: "Mind", enabled: list[str]) -> list[Specialist]:
    unknown = [n for n in enabled if n not in REGISTRY]
    if unknown:
        raise ValueError(f"unknown specialists in config: {unknown}")
    return [REGISTRY[name](mind) for name in enabled]


__all__ = ["Specialist", "MindView", "REGISTRY", "build_specialists"]
