"""limen.cycle — one tick of consciousness.

The exact order of operations, every tick (numbering used throughout the
docs; do not reorder casually — several invariants depend on it):

  1. WAKE       advance the clock; roll the budget day.
  2. FUTURES    timekeeper fires due intentions and tripped dead-man
                switches → percepts from "future_self".
  3. SENSE      poll every sensor (files, feeds — limen/sensors.py) and
                drain the inbox (user messages, external events) → percepts.
                All fresh percepts are logged as stimuli.
  4. BID        every enabled specialist runs perceive(view) CONCURRENTLY
                (asyncio.gather) on an identical, immutable view. Failures
                are contained per-specialist and become interoceptive notes.
  5. AUCTION    attention scores all proposals (salience × novelty ×
                habituation × goal relevance, + coalitions).
  6a. IGNITION  if the top bid clears the threshold: winners enter the
                workspace, each new entry is logged as a broadcast,
                habituation reinforces winning topics, and the ACT phase
                runs — every specialist sees the new broadcasts and may use
                the Toolbelt.
  6b. IDLE      otherwise nothing becomes conscious; the idle streak grows
                (feeding confusion and eventually the wanderer + sleep).
  7. DECAY      workspace TTLs age; habituation decays.
  8. SLEEP?     if consolidation is due, run it (replay → distill → write →
                prune) and log a sleep report.
  9. EXPRESS    drain the outbox; the interface layer delivers utterances.

Everything a mind does — planning, remembering, speaking, worrying — happens
*inside* this loop as content competing for the same small stage.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .bus import Percept, Proposal
from .specialists.base import MindView

if TYPE_CHECKING:
    from .mind import Mind


@dataclass
class TickResult:
    tick: int
    ignited: bool
    top_priority: float
    threshold: float
    winners: list[dict[str, Any]] = field(default_factory=list)
    utterances: list[str] = field(default_factory=list)
    sleep_report: dict[str, Any] | None = None
    proposal_count: int = 0


async def run_tick(mind: "Mind") -> TickResult:
    # 1. WAKE ---------------------------------------------------------------
    tick = mind.clock.advance()
    mind.metrics.on_tick_start(tick)

    # 2. FUTURES ------------------------------------------------------------
    seen_tags = mind.drain_seen_tags()
    fired = mind.timekeeper.collect_due(tick, seen_tags)

    # 3. SENSE --------------------------------------------------------------
    sensed = await _gather_senses(mind, tick)
    stimuli = mind.drain_inbox()
    fresh: list[Percept] = fired + sensed + stimuli
    for pct in fresh:
        pct.tick = tick
        mind.episodic.log("stimulus", tick, {
            "source": pct.source, "content": pct.content, "tags": pct.tags,
        })

    # 4. BID ----------------------------------------------------------------
    view = MindView(
        tick=tick,
        conscious=mind.workspace.render(),
        fresh_percepts=fresh,
        goals_text=mind.goals.render(),
        metrics=mind.metrics.snapshot(),
        workspace=mind.workspace,
    )
    proposals = await _gather_bids(mind, view)
    for p in proposals:
        p.tick = tick

    # 5. AUCTION ------------------------------------------------------------
    goal_text = mind.goals.render() if mind.goals.active() else ""
    report = mind.attention.select(
        proposals,
        recent_broadcasts=mind.recent_broadcasts(),
        goal_text=goal_text,
        budget_tokens=mind.config.workspace.capacity_tokens,
    )

    result = TickResult(
        tick=tick, ignited=report.ignited,
        top_priority=round(report.top_priority(), 4),
        threshold=report.threshold, proposal_count=len(proposals),
    )

    if report.ignited:
        # 6a. IGNITION --------------------------------------------------------
        new_broadcasts = mind.workspace.admit(report.winners, tick)
        for b in new_broadcasts:
            mind.remember_broadcast(b)
            mind.episodic.log("broadcast", tick, {
                "author": b.author, "bkind": b.kind, "content": b.content,
                "priority": round(b.priority, 4), "tags": b.proposal.tags,
            })
            result.winners.append({
                "author": b.author, "kind": b.kind,
                "priority": round(b.priority, 3), "content": b.content,
            })
        mind.metrics.record_ignition(report.top_priority())

        act_view = MindView(
            tick=tick,
            conscious=mind.workspace.render(),   # re-render: stage has changed
            fresh_percepts=fresh,
            goals_text=mind.goals.render(),
            metrics=mind.metrics.snapshot(),
            workspace=mind.workspace,
            new_broadcasts=new_broadcasts,
        )
        await _gather_acts(mind, new_broadcasts, act_view)
    else:
        # 6b. IDLE --------------------------------------------------------------
        mind.metrics.record_idle()
        mind.episodic.log("idle", tick, {
            "content": f"idle: top bid {report.top_priority():.2f} "
                       f"< threshold {report.threshold:.2f} "
                       f"({len(proposals)} proposals)",
        })

    # 7. DECAY ----------------------------------------------------------------
    mind.workspace.age()
    mind.attention.end_of_tick()

    # 8. SLEEP? ---------------------------------------------------------------
    if mind.consolidator.due(tick, mind.metrics.idle_streak):
        result.sleep_report = await mind.consolidator.run(tick, mind)
        mind.metrics.idle_streak = 0

    # 9. EXPRESS ----------------------------------------------------------------
    result.utterances = mind.tools.drain_outbox()
    return result


async def _gather_senses(mind: "Mind", tick: int) -> list[Percept]:
    """Poll sensors on threads under the same guard as specialists: a
    failing sensor contributes nothing and a note_failure entry."""
    if not mind.sensors:
        return []
    timeout = mind.config.cycle.max_specialist_secs

    async def guarded(sensor) -> list[Percept]:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(sensor.poll, tick), timeout=timeout
            )
        except Exception as e:
            mind.metrics.note_failure(f"sensor.{sensor.name}", str(e))
            return []

    nested = await asyncio.gather(*(guarded(s) for s in mind.sensors))
    return [p for sub in nested for p in sub]


async def _gather_bids(mind: "Mind", view: MindView) -> list[Proposal]:
    timeout = mind.config.cycle.max_specialist_secs

    async def guarded(sp) -> list[Proposal]:
        try:
            return await asyncio.wait_for(sp.perceive(view), timeout=timeout)
        except Exception as e:
            mind.metrics.note_failure(f"{sp.name}.perceive", str(e))
            return []

    nested = await asyncio.gather(*(guarded(sp) for sp in mind.specialists))
    return [p for sub in nested for p in sub]


async def _gather_acts(mind: "Mind", broadcasts, view: MindView) -> None:
    timeout = mind.config.cycle.max_specialist_secs

    async def guarded(sp) -> None:
        try:
            await asyncio.wait_for(
                sp.act(broadcasts, view, mind.tools), timeout=timeout
            )
        except Exception as e:
            mind.metrics.note_failure(f"{sp.name}.act", str(e))

    await asyncio.gather(*(guarded(sp) for sp in mind.specialists))
