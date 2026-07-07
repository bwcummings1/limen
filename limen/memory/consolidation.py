"""limen.memory.consolidation — sleep as a scheduled job.

Every `sleep.every_ticks` ticks (or after a long idle streak), the mind:

  1. REPLAYS  the episodic log since the last sleep (bounded window),
  2. DISTILLS it through the LLM into <= max_lessons one-line lessons
              ("LESSON: ..." for semantic memory, "PROCEDURE: <title> :: <body>"
              for procedural memory),
  3. WRITES   lessons into the belief ledger (merge/reinforce/contradict
              rules apply exactly as for waking beliefs) and skill store,
  4. DECAYS   all belief confidences to their current effective value and
              prunes those below the floor,
  5. REPORTS  a sleep_report event so the next morning's librarian can say
              "while you slept, I learned…".

This is memory consolidation in the cognitive-science sense — replay,
abstraction, forgetting — implemented as literally as possible.
"""
from __future__ import annotations

import re
from typing import Any

from ..config import SleepConfig
from ..providers.base import LLMProvider, LLMRequest
from ..util import truncate

_LESSON = re.compile(r"^\s*LESSON:\s*(.+)$", re.MULTILINE)
_PROCEDURE = re.compile(r"^\s*PROCEDURE:\s*([^:]{3,80})::\s*(.+)$", re.MULTILINE)

_SYSTEM = (
    "You are the consolidation process of an agent mind, running during sleep. "
    "You will be shown a replay of recent conscious events. Distill the most "
    "durable, general takeaways. Output ONLY lines of the form:\n"
    "LESSON: <one-sentence general lesson>\n"
    "PROCEDURE: <short title> :: <one-paragraph how-to>\n"
    "At most {n} lines total. Prefer lessons about the user's stable "
    "preferences, decisions that changed, and process improvements. Do not "
    "restate raw events; distill and consolidate."
)


class Consolidator:
    def __init__(self, config: SleepConfig, provider: LLMProvider) -> None:
        self.cfg = config
        self.provider = provider
        self.last_sleep_tick = 0

    def due(self, tick: int, idle_streak: int) -> bool:
        if tick - self.last_sleep_tick >= self.cfg.every_ticks:
            return True
        return idle_streak >= self.cfg.idle_trigger and tick - self.last_sleep_tick > 3

    async def run(self, tick: int, mind: Any) -> dict[str, Any]:
        """Full sleep pass. `mind` duck-types: episodic, ledger, skills, metrics."""
        events = mind.episodic.since_tick(
            self.last_sleep_tick, limit=self.cfg.replay_window
        )
        replay = self._render_replay(events)

        lessons: list[str] = []
        procedures: list[tuple[str, str]] = []
        if replay:
            req = LLMRequest(
                system=_SYSTEM.format(n=self.cfg.max_lessons),
                messages=[{"role": "user", "content": truncate(replay, 2400)}],
                max_tokens=400,
                temperature=0.0,   # legacy models: sampled at 0
                purpose="consolidation",
                deterministic=True,  # cacheable even on models without temperature
            )
            try:
                resp = await self.provider.complete(req)
                lessons = _LESSON.findall(resp.text)[: self.cfg.max_lessons]
                procedures = _PROCEDURE.findall(resp.text)[: self.cfg.max_lessons]
            except Exception as e:  # budget exhaustion, network — sleep still runs
                mind.metrics.note_failure("consolidation", str(e))

        written = []
        for lesson in lessons:
            belief, action = mind.ledger.assert_claim(
                claim=lesson.strip(),
                confidence=0.65,
                tick=tick,
                provenance={"kind": "sleep", "ref": f"sleep@{tick}"},
                tags=["lesson"],
            )
            written.append({"belief": belief.id, "action": action})
        skill_paths = [
            str(mind.skills.write(title.strip(), body.strip(), tick, "sleep"))
            for title, body in procedures
        ]

        pruned = mind.ledger.decay_and_prune(tick, self.cfg.prune_floor)
        self.last_sleep_tick = tick

        report = {
            "replayed_events": len(events),
            "lessons": lessons,
            "skills_written": skill_paths,
            "beliefs_written": written,
            "beliefs_pruned": pruned,
        }
        mind.episodic.log("sleep_report", tick, {"content": self._summ(report), **report})
        return report

    _NOISE_KINDS = frozenset({"idle", "sleep_report"})

    @classmethod
    def _render_replay(cls, events: list[dict[str, Any]]) -> str:
        """Only substantive events reach the dream: idle ticks and prior
        sleep reports are metabolic noise, not memories."""
        lines = []
        for e in events:
            if e["kind"] in cls._NOISE_KINDS:
                continue
            text = e.get("content") or e.get("text") or ""
            if text:
                lines.append(f"[t={e['tick']} {e['kind']}] {truncate(text, 60)}")
        return "\n".join(lines)

    @staticmethod
    def _summ(report: dict[str, Any]) -> str:
        return (
            f"Slept: replayed {report['replayed_events']} events, distilled "
            f"{len(report['lessons'])} lessons, wrote {len(report['skills_written'])} "
            f"skills, pruned {len(report['beliefs_pruned'])} beliefs."
        )
