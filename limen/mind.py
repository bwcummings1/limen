"""limen.mind — the assembled organism.

Mind owns one instance of every subsystem and exposes the whole public API:

    mind = Mind.from_config(Config.load("limen.toml"))
    mind.stimulate("Should we migrate the blog?")   # push a percept
    result = mind.tick()                            # one cognitive cycle
    replies = mind.run_until_response(max_ticks=10) # converse
    mind.run_ticks(24)                              # let it live a while

Nothing in Mind is clever; it is the wiring diagram. All intelligence lives
in the loop (cycle.py), the auction (attention.py), and the specialists.
"""
from __future__ import annotations

import asyncio
from collections import deque
from pathlib import Path

from .attention import Attention
from .bus import Broadcast, Percept
from .config import Config
from .cycle import TickResult, run_tick
from .embeddings import build_similarity
from .interoception import Metrics
from .memory import BeliefLedger, Consolidator, EpisodicMemory, SkillStore
from .population import Ensemble
from .providers import build_provider
from .sensors import Sensor, build_sensors
from .specialists import build_specialists
from .timekeeper import Timekeeper
from .tools import GoalStack, Toolbelt
from .util import Clock, make_rng, set_similarity_backend
from .workspace import GlobalWorkspace


class Mind:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.data_dir = Path(config.mind.data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.rng = make_rng(config.mind.seed)
        self.clock = Clock()

        # substrate
        self.provider = build_provider(config, self.data_dir)
        self.metrics = Metrics(cfg=config.interoception, provider=self.provider)
        # Similarity backend is process-global (see util.py); each Mind
        # construction sets it to match its own [embeddings] config.
        set_similarity_backend(build_similarity(config, self.data_dir))

        # memory systems
        self.episodic = EpisodicMemory(self.data_dir)
        self.ledger = BeliefLedger(self.data_dir, config.ledger)
        self.skills = SkillStore(self.data_dir)
        self.consolidator = Consolidator(config.sleep, self.provider)

        # cognition
        self.workspace = GlobalWorkspace(config.workspace)
        self.attention = Attention(config.attention)
        self.timekeeper = Timekeeper(self.data_dir)
        self.ensemble = Ensemble(config.population, self.provider)
        self.goals = GoalStack()
        self.tools = Toolbelt(self)

        # the audience
        self.specialists = build_specialists(self, config.specialists.enabled)

        # the senses (polled in the SENSE phase; see limen/sensors.py)
        self.sensors: list[Sensor] = build_sensors(config, self.data_dir)

        # transient state
        self._inbox: list[Percept] = []
        self._recent: deque[Broadcast] = deque(maxlen=12)
        self._last_tag_scan_tick = 0

    # ------------------------------------------------------------ factories

    @classmethod
    def from_config(cls, config: Config | str | Path | None = None) -> "Mind":
        if config is None or isinstance(config, (str, Path)):
            config = Config.load(config)
        return cls(config)

    # ---------------------------------------------------------------- input

    def stimulate(self, content: str, source: str = "user",
                  salience: float = 0.9, tags: list[str] | None = None) -> None:
        """Queue a percept for the next tick. The one write-path into the mind."""
        self._inbox.append(Percept(
            source=source, content=content,
            salience_hint=salience, tags=tags or [],
        ))

    def drain_inbox(self) -> list[Percept]:
        out, self._inbox = self._inbox, []
        return out

    def add_sensor(self, sensor: Sensor) -> None:
        """Register a sensory channel; polled every tick from the next one."""
        self.sensors.append(sensor)

    # ------------------------------------------------------------- plumbing

    def remember_broadcast(self, b: Broadcast) -> None:
        self._recent.append(b)

    def recent_broadcasts(self) -> list[Broadcast]:
        return list(self._recent)

    def drain_seen_tags(self) -> set[str]:
        """Tags on episodic events since the last scan — dead-man food."""
        events = self.episodic.since_tick(self._last_tag_scan_tick)
        self._last_tag_scan_tick = self.clock.tick
        tags: set[str] = set()
        for e in events:
            tags.update(e.get("tags", []))
        return tags

    # ------------------------------------------------------------- lifecycle

    async def tick_async(self) -> TickResult:
        return await run_tick(self)

    def tick(self) -> TickResult:
        return asyncio.run(self.tick_async())

    def run_ticks(self, n: int) -> list[TickResult]:
        async def _run() -> list[TickResult]:
            return [await run_tick(self) for _ in range(n)]
        return asyncio.run(_run())

    def run_until_response(self, max_ticks: int = 10) -> tuple[list[str], list[TickResult]]:
        """Tick until the mind says something (or gives up). Returns
        (utterances, tick_results) — the conversational primitive."""
        async def _run():
            utterances: list[str] = []
            results: list[TickResult] = []
            for _ in range(max_ticks):
                r = await run_tick(self)
                results.append(r)
                utterances.extend(r.utterances)
                if utterances:
                    break
            return utterances, results
        return asyncio.run(_run())

    # ------------------------------------------------------------ inspection

    def status(self) -> dict:
        return {
            "name": self.config.mind.name,
            "tick": self.clock.tick,
            "workspace_items": len(self.workspace),
            "workspace_tokens": self.workspace.total_tokens(),
            "active_goals": len(self.goals.active()),
            "beliefs": len(self.ledger.active(self.clock.tick)),
            "skills": len(self.skills),
            "pending_intentions": len(self.timekeeper),
            "episodic_events": len(self.episodic),
            "metrics": self.metrics.snapshot(),
        }
