"""limen.config — every tunable in one place, loadable from TOML.

Philosophy: the *code* defines safe defaults; a `limen.toml` overrides them.
Every field below is documented in docs/CONFIGURATION.md — if you add a field
here, document it there. Validation is strict: unknown keys raise, because a
typo in a config that silently no-ops is how minds get subtle brain damage.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any


@dataclass
class MindConfig:
    name: str = "limen-01"
    data_dir: str = ".limen"          # all persistent state lives under here
    seed: int | None = 7              # None => nondeterministic


@dataclass
class WorkspaceConfig:
    capacity_tokens: int = 800        # size of "consciousness" in est. tokens
    item_ttl: int = 3                 # ticks a broadcast persists unrefreshed
    max_items: int = 7                # Miller-ish cap on simultaneous contents


@dataclass
class AttentionConfig:
    ignition_threshold: float = 0.25  # min winning priority for ignition
    novelty_floor: float = 0.40       # α: priority ×= α+(1-α)·novelty
    habituation_strength: float = 0.70  # β: priority ×= 1-β·habituation
    goal_floor: float = 0.50          # γ: priority ×= γ+(1-γ)·goal_relevance
    habituation_gain: float = 0.25    # added to a topic each time it wins
    habituation_decay: float = 0.90   # per-tick multiplicative decay
    coalition_bonus: float = 0.15     # fraction of allies' priority added
    recent_window: int = 6            # broadcasts compared for novelty
    max_item_fraction: float = 0.50   # max share of workspace one item may take


@dataclass
class BudgetConfig:
    tokens_per_day: int = 200_000     # provider hard budget (est. or real)
    day_ticks: int = 96               # ticks per "day" for budget + sleep math
    hard_stop: bool = True            # True: refuse LLM calls when exhausted


@dataclass
class ProviderConfig:
    kind: str = "mock"                # "mock" | "anthropic"
    model: str = "claude-opus-4-8"    # default model for every call…
    models: dict[str, str] = field(default_factory=dict)
    # …overridable per purpose via [provider.models], e.g.
    #   [provider.models]
    #   oracle = "claude-haiku-4-5"          # cheap persona forks
    #   consolidation = "claude-opus-4-8"    # sleep writes long-term memory
    # Purposes in use: planner, critic, speaker, oracle, oracle_merge,
    # consolidation (a custom specialist's ask() defaults to its name).
    max_tokens: int = 400
    temperature: float = 0.7
    cache: bool = True                # content-addressed response cache
    timeout_secs: float = 60.0
    max_retries: int = 4


@dataclass
class EmbeddingsConfig:
    kind: str = "none"                # "none" (stdlib heuristic) | "voyage" |
                                      # "openai" (any /v1/embeddings server) | "ollama"
    model: str = ""                   # "" => per-kind default (voyage-3.5-lite / nomic-embed-text)
    base_url: str = ""                # openai: required (e.g. http://localhost:1234/v1);
                                      # ollama: "" => http://localhost:11434
    calibration_floor: float = 0.55   # cosine below this scales to 0 (model-specific!)
    cache: bool = True                # vectors content-addressed under data_dir/cache/embeddings
    timeout_secs: float = 20.0


@dataclass
class SensorsConfig:
    watch_dirs: list[str] = field(default_factory=list)   # FileWatcher per dir
    watch_salience: float = 0.55
    rss_feeds: list[str] = field(default_factory=list)    # RSSWatcher per URL
    rss_every_ticks: int = 12
    rss_salience: float = 0.45


@dataclass
class SleepConfig:
    every_ticks: int = 24             # consolidation cadence
    idle_trigger: int = 6             # consecutive idle ticks also trigger sleep
    max_lessons: int = 5              # distilled lessons per sleep
    prune_floor: float = 0.05         # beliefs decayed below this are pruned
    replay_window: int = 200          # max episodic events replayed


@dataclass
class LedgerConfig:
    default_half_life: int = 480      # ticks for confidence to halve
    merge_threshold: float = 0.72     # similarity above which beliefs merge
    contradiction_threshold: float = 0.30  # topicality floor for contradiction test
    reinforce_kappa: float = 0.6      # noisy-OR strength of reinforcement


@dataclass
class PopulationConfig:
    personas: list[str] = field(
        default_factory=lambda: ["analyst", "skeptic", "optimist"]
    )
    cluster_threshold: float = 0.62   # answers above this similarity co-cluster
    trigger_kinds: list[str] = field(default_factory=lambda: ["question"])
    min_salience: float = 0.55        # only fork for stakes above this


@dataclass
class InteroceptionConfig:
    confusion_threshold: float = 0.60  # confusion index that raises an alarm
    budget_alarm_fraction: float = 0.20
    ewma_alpha: float = 0.30           # smoothing for ignition-rate estimate


@dataclass
class SpecialistsConfig:
    enabled: list[str] = field(
        default_factory=lambda: [
            "perception", "goals", "planner", "critic", "librarian",
            "introspector", "oracle", "scribe", "speaker", "wanderer",
        ]
    )


@dataclass
class CycleConfig:
    idle_sleep_secs: float = 0.0      # daemon-mode pause between ticks
    max_specialist_secs: float = 90.0 # watchdog per specialist call


@dataclass
class Config:
    mind: MindConfig = field(default_factory=MindConfig)
    workspace: WorkspaceConfig = field(default_factory=WorkspaceConfig)
    attention: AttentionConfig = field(default_factory=AttentionConfig)
    budget: BudgetConfig = field(default_factory=BudgetConfig)
    provider: ProviderConfig = field(default_factory=ProviderConfig)
    embeddings: EmbeddingsConfig = field(default_factory=EmbeddingsConfig)
    sensors: SensorsConfig = field(default_factory=SensorsConfig)
    sleep: SleepConfig = field(default_factory=SleepConfig)
    ledger: LedgerConfig = field(default_factory=LedgerConfig)
    population: PopulationConfig = field(default_factory=PopulationConfig)
    interoception: InteroceptionConfig = field(default_factory=InteroceptionConfig)
    specialists: SpecialistsConfig = field(default_factory=SpecialistsConfig)
    cycle: CycleConfig = field(default_factory=CycleConfig)

    # -------------------------------------------------------------- loading

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Config":
        """Load defaults, then overlay a TOML file if given/found."""
        cfg = cls()
        if path is None:
            candidate = Path("limen.toml")
            path = candidate if candidate.exists() else None
        if path is not None:
            with open(path, "rb") as f:
                data = tomllib.load(f)
            cfg._apply(data, source=str(path))
        return cfg

    def _apply(self, data: dict[str, Any], source: str) -> None:
        sections = {f.name: f for f in fields(self)}
        for section, values in data.items():
            if section not in sections:
                raise ValueError(f"{source}: unknown config section [{section}]")
            target = getattr(self, section)
            valid = {f.name for f in fields(target)}
            for key, value in values.items():
                if key not in valid:
                    raise ValueError(
                        f"{source}: unknown key '{key}' in section [{section}]"
                    )
                setattr(target, key, value)
        self.validate()

    def validate(self) -> None:
        a = self.attention
        checks = [
            (0.0 <= a.ignition_threshold <= 1.0, "ignition_threshold in [0,1]"),
            (0.0 <= a.novelty_floor <= 1.0, "novelty_floor in [0,1]"),
            (0.0 <= a.habituation_strength < 1.0, "habituation_strength in [0,1)"),
            (self.workspace.capacity_tokens > 50, "workspace capacity > 50 tokens"),
            (self.budget.day_ticks > 0, "budget.day_ticks > 0"),
            (self.sleep.every_ticks > 1, "sleep.every_ticks > 1"),
            (len(self.population.personas) >= 2, ">= 2 population personas"),
            (
                all(
                    isinstance(k, str) and isinstance(v, str) and v
                    for k, v in self.provider.models.items()
                ),
                "[provider.models] must map purpose strings to model id strings",
            ),
            (
                self.embeddings.kind in ("none", "voyage", "openai", "ollama"),
                "embeddings.kind is 'none', 'voyage', 'openai', or 'ollama'",
            ),
            (
                self.embeddings.kind != "openai" or bool(self.embeddings.base_url),
                "embeddings.kind = 'openai' requires embeddings.base_url",
            ),
            (
                0.0 <= self.embeddings.calibration_floor < 1.0,
                "embeddings.calibration_floor in [0,1)",
            ),
            (self.sensors.rss_every_ticks > 0, "sensors.rss_every_ticks > 0"),
        ]
        for ok, msg in checks:
            if not ok:
                raise ValueError(f"config invalid: {msg}")
