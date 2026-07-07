"""limen.interoception — the mind's sense of its own state.

A frozen model can't feel anything about itself; the harness can measure it
and pipe it back in. Interoception collects per-cycle vitals and computes a
single headline number, the CONFUSION INDEX:

    confusion = 0.4·(1 − ignition_rate)      # nothing feels important
              + 0.4·disagreement             # my forks don't agree
              + 0.2·failure_rate             # my tools keep erroring

All three components are direct measurements, not vibes. The introspector
specialist turns threshold crossings into conscious percepts ("I am
confused", "budget nearly gone"), which lets the mind *change strategy
because of how it feels* — escalate, search, fork an ensemble, or ask the
human. That loop is the whole point of this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .config import InteroceptionConfig
from .providers.base import LLMProvider
from .util import clamp


@dataclass
class Metrics:
    cfg: InteroceptionConfig
    provider: LLMProvider

    tick: int = 0
    ignitions: int = 0
    idles: int = 0
    idle_streak: int = 0
    ignition_rate: float = 0.5          # EWMA of "did this tick ignite?"
    mean_winning_priority: float = 0.0  # EWMA
    last_disagreement: float = 0.0      # from the most recent ensemble
    failures: int = 0
    failure_notes: list[str] = field(default_factory=list)
    _alarms_raised: set[str] = field(default_factory=set)

    # ------------------------------------------------------------ recording

    def on_tick_start(self, tick: int) -> None:
        self.tick = tick
        self.provider.budget.on_tick(tick)

    def record_ignition(self, winning_priority: float) -> None:
        self.ignitions += 1
        self.idle_streak = 0
        a = self.cfg.ewma_alpha
        self.ignition_rate = (1 - a) * self.ignition_rate + a * 1.0
        self.mean_winning_priority = (
            (1 - a) * self.mean_winning_priority + a * winning_priority
        )

    def record_idle(self) -> None:
        self.idles += 1
        self.idle_streak += 1
        a = self.cfg.ewma_alpha
        self.ignition_rate = (1 - a) * self.ignition_rate

    def record_disagreement(self, d: float) -> None:
        self.last_disagreement = clamp(d)

    def note_failure(self, where: str, detail: str) -> None:
        self.failures += 1
        self.failure_notes.append(f"{where}: {detail[:120]}")
        self.failure_notes = self.failure_notes[-10:]

    # ------------------------------------------------------------- derived

    def failure_rate(self) -> float:
        calls = max(self.provider.stats.calls, 1)
        return clamp(self.provider.stats.failures / calls)

    def confusion_index(self) -> float:
        return clamp(
            0.4 * (1.0 - self.ignition_rate)
            + 0.4 * self.last_disagreement
            + 0.2 * self.failure_rate()
        )

    def snapshot(self) -> dict[str, Any]:
        s = self.provider.stats
        return {
            "tick": self.tick,
            "confusion": round(self.confusion_index(), 3),
            "ignition_rate": round(self.ignition_rate, 3),
            "idle_streak": self.idle_streak,
            "disagreement": round(self.last_disagreement, 3),
            "llm_calls": s.calls,
            "cache_hits": s.cache_hits,
            "llm_failures": s.failures,
            "tokens_in": s.input_tokens,
            "tokens_out": s.output_tokens,
            "budget_remaining_frac": round(self.provider.budget.fraction_remaining(), 3),
            "calls_by_purpose": dict(s.by_purpose),
        }

    # -------------------------------------------------------------- alarms

    def pending_alarms(self) -> list[tuple[str, str, float]]:
        """(alarm_key, message, salience) — each key fires once per episode."""
        alarms: list[tuple[str, str, float]] = []
        conf = self.confusion_index()
        if conf >= self.cfg.confusion_threshold:
            alarms.append((
                "confusion",
                f"Interoception: confusion index {conf:.2f} (ignition rate "
                f"{self.ignition_rate:.2f}, fork disagreement "
                f"{self.last_disagreement:.2f}). Consider gathering more "
                "information or asking the user before committing.",
                0.7,
            ))
        frac = self.provider.budget.fraction_remaining()
        if frac <= self.cfg.budget_alarm_fraction:
            alarms.append((
                "budget",
                f"Interoception: only {frac:.0%} of today's token budget "
                "remains. Prefer cheap actions; defer nonessential thought "
                "to after the next budget reset.",
                0.8,
            ))
        fresh = [a for a in alarms if a[0] not in self._alarms_raised]
        for key, _, _ in fresh:
            self._alarms_raised.add(key)
        # re-arm alarms once condition clears
        if conf < self.cfg.confusion_threshold:
            self._alarms_raised.discard("confusion")
        if frac > self.cfg.budget_alarm_fraction:
            self._alarms_raised.discard("budget")
        return fresh
