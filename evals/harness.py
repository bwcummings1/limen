"""evals.harness — scenarios × arms × seeds, scored off the episodic log.

An ARM is a named config mutation (an ablation). A SCENARIO is a scripted
life (tick → stimulus) plus a scorer that reads the mind's state and the
tick results — programmatic assertions against ground truth, no judge.

Determinism does the heavy lifting: every (scenario, arm) pair runs on the
SAME seeds, so metric differences are attributable to the ablation, not to
sampling luck. With the mock provider the whole matrix runs offline in
seconds — auction-level effects (habituation, thresholds, coalitions) are
real regardless of cortex. Run with a real provider (--provider anthropic)
for the numbers that include LLM quality; the token budget is identical
across arms, so the comparison stays fair.
"""
from __future__ import annotations

import json
import statistics
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from limen import Config, Mind

Mutator = Callable[[Config], None]


# ---------------------------------------------------------------------- arms

def _no_habituation(cfg: Config) -> None:
    cfg.attention.habituation_strength = 0.0
    cfg.attention.habituation_gain = 0.0


def _no_threshold(cfg: Config) -> None:
    cfg.attention.ignition_threshold = 0.0   # everything becomes conscious


def _no_sleep(cfg: Config) -> None:
    cfg.sleep.every_ticks = 10 ** 9
    cfg.sleep.idle_trigger = 10 ** 9


def _no_reflection(cfg: Config) -> None:
    """No librarian (recall) and no scribe (belief writing)."""
    cfg.specialists.enabled = [
        s for s in cfg.specialists.enabled if s not in ("librarian", "scribe")
    ]


def _no_ensemble(cfg: Config) -> None:
    cfg.specialists.enabled = [
        s for s in cfg.specialists.enabled if s != "oracle"
    ]


ARMS: dict[str, Mutator] = {
    "full": lambda cfg: None,
    "no_habituation": _no_habituation,
    "no_threshold": _no_threshold,
    "no_sleep": _no_sleep,
    "no_reflection": _no_reflection,
    "no_ensemble": _no_ensemble,
}


# ----------------------------------------------------------------- scenarios

@dataclass
class Scenario:
    """A scripted life. `script` maps tick -> stimulus text (or a
    (text, salience) tuple). `scorer(mind, results)` returns metric floats
    — computed from the episodic log, ledger, goals, and TickResults.
    `config_tweaks` is for scenario-level noise control (e.g. disabling the
    wanderer where its random bids would pollute an ignition count)."""

    name: str
    description: str
    horizon: int
    script: dict[int, Any]
    scorer: Callable[["Mind", list], dict[str, float]]
    config_tweaks: Mutator = field(default=lambda cfg: None)


# -------------------------------------------------------------------- runner

def run_once(scenario: Scenario, mutate: Mutator, seed: int,
             provider: str = "mock") -> dict[str, float]:
    """One life: fresh data dir, scripted stimuli, scored at the end."""
    cfg = Config()
    cfg.mind.seed = seed
    cfg.provider.kind = provider
    scenario.config_tweaks(cfg)
    mutate(cfg)
    cfg.validate()
    with tempfile.TemporaryDirectory() as tmp:
        cfg.mind.data_dir = tmp
        mind = Mind.from_config(cfg)
        results = []
        for tick in range(1, scenario.horizon + 1):
            stim = scenario.script.get(tick)
            if stim is not None:
                if isinstance(stim, tuple):
                    mind.stimulate(stim[0], salience=stim[1])
                else:
                    mind.stimulate(stim)
            results.append(mind.tick())
        return scenario.scorer(mind, results)


def run_matrix(scenarios: list[Scenario], arm_names: list[str],
               seeds: list[int], provider: str = "mock") -> dict:
    """results[scenario][arm][metric] = mean over seeds (paired)."""
    out: dict[str, dict[str, dict[str, float]]] = {}
    for sc in scenarios:
        out[sc.name] = {}
        for arm in arm_names:
            per_seed = [run_once(sc, ARMS[arm], s, provider) for s in seeds]
            metrics = sorted({k for r in per_seed for k in r})
            out[sc.name][arm] = {
                m: round(statistics.mean(r.get(m, 0.0) for r in per_seed), 3)
                for m in metrics
            }
    return out


# -------------------------------------------------------------------- report

def format_table(results: dict) -> str:
    lines = []
    for scenario, arms in results.items():
        metrics = sorted({m for a in arms.values() for m in a})
        widths = [max(14, *(len(a) for a in arms))] + [
            max(len(m), 7) for m in metrics
        ]
        header = "arm".ljust(widths[0]) + "  " + "  ".join(
            m.rjust(w) for m, w in zip(metrics, widths[1:])
        )
        lines.append(f"\n== {scenario} ==")
        lines.append(header)
        lines.append("-" * len(header))
        for arm, vals in arms.items():
            row = arm.ljust(widths[0]) + "  " + "  ".join(
                f"{vals.get(m, 0.0):.3f}".rjust(w)
                for m, w in zip(metrics, widths[1:])
            )
            lines.append(row)
    return "\n".join(lines)


def save_json(results: dict, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(results, indent=1), encoding="utf-8")
    return path
