"""limen.timekeeper — patience and initiative, synthesized.

A chat model lives in an eternal present; the timekeeper gives the mind a
future. It persists intentions to `intentions.json` and, at the start of
every cycle, converts due intentions into high-salience percepts from the
channel "future_self" — messages the mind wrote to a later version of
itself.

Three intention shapes:

  one-shot   {due_tick, message}                fire once, archive
  recurring  {due_tick, every, message}         fire, reschedule (+every)
  dead-man   {watch_tag, within, message}       fire IF no episodic event
                                                carrying watch_tag occurs
                                                within `within` ticks —
                                                absence as a trigger.

All timing is in cognitive ticks; the daemon maps ticks to wall time.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from .bus import Percept
from .util import new_id


@dataclass
class Intention:
    message: str
    due_tick: int | None = None
    every: int | None = None                  # recurring interval
    watch_tag: str | None = None              # dead-man switch fields
    within: int | None = None
    armed_tick: int | None = None
    salience: float = 0.8
    created_tick: int = 0
    fired_count: int = 0
    id: str = field(default_factory=lambda: new_id("int"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Timekeeper:
    def __init__(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "intentions.json"
        self.pending: dict[str, Intention] = {}
        self.archive: list[dict[str, Any]] = []
        self._load()

    # ------------------------------------------------------------ persistence

    def _load(self) -> None:
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for entry in data.get("pending", []):
                i = Intention(**entry)
                self.pending[i.id] = i
            self.archive = data.get("archive", [])

    def save(self) -> None:
        self.path.write_text(
            json.dumps(
                {
                    "pending": [i.to_dict() for i in self.pending.values()],
                    "archive": self.archive[-200:],
                },
                indent=1,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    # -------------------------------------------------------------- schedule

    def schedule(self, message: str, due_tick: int, tick: int,
                 every: int | None = None, salience: float = 0.8) -> Intention:
        i = Intention(
            message=message, due_tick=due_tick, every=every,
            salience=salience, created_tick=tick,
        )
        self.pending[i.id] = i
        self.save()
        return i

    def arm_deadman(self, message: str, watch_tag: str, within: int,
                    tick: int, salience: float = 0.85) -> Intention:
        i = Intention(
            message=message, watch_tag=watch_tag, within=within,
            armed_tick=tick, salience=salience, created_tick=tick,
        )
        self.pending[i.id] = i
        self.save()
        return i

    def disarm(self, watch_tag: str) -> int:
        """Cancel dead-man switches watching `watch_tag` (the event occurred)."""
        hits = [i for i in self.pending.values() if i.watch_tag == watch_tag]
        for i in hits:
            self.archive.append({**i.to_dict(), "outcome": "disarmed"})
            del self.pending[i.id]
        if hits:
            self.save()
        return len(hits)

    # ------------------------------------------------------------------ fire

    def collect_due(self, tick: int, seen_tags: set[str]) -> list[Percept]:
        """Called at the top of every cycle. `seen_tags` = episodic tags seen
        since last check, used to disarm dead-man switches passively."""
        fired: list[Percept] = []
        for i in list(self.pending.values()):
            if i.watch_tag is not None:
                if i.watch_tag in seen_tags:
                    self.disarm(i.watch_tag)
                    continue
                if tick - (i.armed_tick or 0) >= (i.within or 0):
                    fired.append(self._fire(i, tick, kind="deadman"))
                continue
            if i.due_tick is not None and tick >= i.due_tick:
                fired.append(self._fire(i, tick, kind="reminder"))
                if i.every:
                    i.due_tick = tick + i.every
                    i.fired_count += 1
                    self.pending[i.id] = i
        if fired:
            self.save()
        return fired

    def _fire(self, i: Intention, tick: int, kind: str) -> Percept:
        if not (i.every and kind == "reminder"):
            self.archive.append({**i.to_dict(), "outcome": f"fired@{tick}"})
            self.pending.pop(i.id, None)
        prefix = "DEAD-MAN TRIPPED" if kind == "deadman" else "Reminder from your past self"
        return Percept(
            source="future_self",
            content=f"{prefix}: {i.message}",
            salience_hint=i.salience,
            tags=["scheduled", kind],
            tick=tick,
        )

    def __len__(self) -> int:
        return len(self.pending)
