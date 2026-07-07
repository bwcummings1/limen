"""limen.tools — the mind's hands, deliberately small.

Specialists never touch subsystems directly during action; they act through
this allowlisted, fully-logged surface. Design rules:

  * Every call is logged to episodic memory (the mind cannot act secretly
    from itself — or from its human, who can read the same log).
  * Filesystem writes are confined to data_dir/notes/ (path-traversal
    checked). No exec, no shell, no network. LIMEN's power comes from
    orchestration, not from a big effector; adding effectors is a config
    decision a human makes, never one the mind makes.
  * respond() queues text to the outbox; the interface layer (CLI/daemon)
    is the only thing that delivers it. The mind proposes speech; the
    harness performs it.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


class GoalStack:
    """Ordered active goals. Tiny by design: a goal is a string + status."""

    def __init__(self) -> None:
        self.goals: list[dict[str, Any]] = []
        self._n = 0

    def add(self, text: str, tick: int) -> dict[str, Any]:
        self._n += 1
        g = {"id": f"goal_{self._n}", "text": text, "tick": tick, "status": "active"}
        self.goals.append(g)
        return g

    def complete(self, goal_id: str) -> bool:
        for g in self.goals:
            if g["id"] == goal_id and g["status"] == "active":
                g["status"] = "done"
                return True
        return False

    def active(self) -> list[dict[str, Any]]:
        return [g for g in self.goals if g["status"] == "active"]

    def render(self) -> str:
        act = self.active()
        if not act:
            return "(no active goals)"
        return "\n".join(f"- ({g['id']}) {g['text']}" for g in act)


class Toolbelt:
    """Bound to one Mind; passed to specialists during the action phase."""

    def __init__(self, mind: Any) -> None:
        self._mind = mind
        self.outbox: list[str] = []

    # ------------------------------------------------------------- speaking

    def respond(self, text: str) -> None:
        """Queue an utterance for the human. Delivered by the interface layer."""
        self.outbox.append(text)
        self._mind.episodic.log(
            "utterance", self._mind.clock.tick, {"content": text}
        )

    def drain_outbox(self) -> list[str]:
        out, self.outbox = self.outbox, []
        return out

    # --------------------------------------------------------------- notes

    def write_note(self, name: str, text: str) -> str:
        notes = Path(self._mind.data_dir) / "notes"
        notes.mkdir(parents=True, exist_ok=True)
        safe = "".join(c for c in name if c.isalnum() or c in "-_")[:60] or "note"
        path = (notes / f"{safe}.md").resolve()
        if notes.resolve() not in path.parents:
            raise PermissionError("note path escapes the notes sandbox")
        path.write_text(text, encoding="utf-8")
        self._mind.episodic.log(
            "tool", self._mind.clock.tick,
            {"tool": "write_note", "content": f"wrote note {safe} ({len(text)} chars)"},
        )
        return str(path)

    # ------------------------------------------------------------ scheduling

    def schedule(self, message: str, in_ticks: int, every: int | None = None) -> str:
        tick = self._mind.clock.tick
        i = self._mind.timekeeper.schedule(
            message=message, due_tick=tick + max(1, in_ticks), tick=tick, every=every
        )
        self._mind.episodic.log(
            "tool", tick,
            {"tool": "schedule", "content": f"scheduled '{message}' in {in_ticks} ticks"},
        )
        return i.id

    def arm_deadman(self, message: str, watch_tag: str, within: int) -> str:
        tick = self._mind.clock.tick
        i = self._mind.timekeeper.arm_deadman(message, watch_tag, within, tick)
        self._mind.episodic.log(
            "tool", tick,
            {"tool": "deadman",
             "content": f"armed dead-man on '{watch_tag}' within {within} ticks"},
        )
        return i.id

    # ---------------------------------------------------------------- goals

    def add_goal(self, text: str) -> str:
        g = self._mind.goals.add(text, self._mind.clock.tick)
        self._mind.episodic.log(
            "tool", self._mind.clock.tick,
            {"tool": "add_goal", "content": f"added goal: {text}"},
        )
        return g["id"]

    def complete_goal(self, goal_id: str) -> bool:
        ok = self._mind.goals.complete(goal_id)
        if ok:
            self._mind.episodic.log(
                "tool", self._mind.clock.tick,
                {"tool": "complete_goal", "content": f"completed {goal_id}"},
            )
        return ok

    # --------------------------------------------------------------- memory

    def remember(self, claim: str, confidence: float, tags: list[str] | None = None,
                 half_life: int | None = None) -> tuple[str, str]:
        tick = self._mind.clock.tick
        belief, action = self._mind.ledger.assert_claim(
            claim=claim, confidence=confidence, tick=tick,
            provenance={"kind": "scribe", "ref": f"tick@{tick}"},
            tags=tags, half_life=half_life,
        )
        self._mind.episodic.log(
            "belief_write", tick,
            {"content": f"[{action}] {claim}", "belief_id": belief.id,
             "confidence": round(belief.confidence, 3)},
        )
        if action == "contradiction":
            self._mind.episodic.log(
                "contradiction", tick,
                {"content": f"belief conflict resolved: '{claim}' vs prior; "
                            f"kept the better-supported side", "belief_id": belief.id},
            )
        return belief.id, action
