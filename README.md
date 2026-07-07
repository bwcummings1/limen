# LIMEN

**A Global Workspace Theory runtime for LLM agents.**
*An inner life assembled from cron jobs and JSON files.*

> **limen** *(n., psychophysics)* — the threshold below which a stimulus is
> not perceived. Content beneath it is, literally, **sub-liminal**.

LIMEN is a complete, runnable implementation of Bernard Baars' Global
Workspace Theory as agent scaffolding: many cheap specialist processes bid
for one small "conscious" workspace; whatever crosses the **ignition
threshold** is broadcast to every specialist; a clock, four memory systems,
interoceptive self-monitoring, and fork-diff-merge deliberation close the
loop. The name is the mechanism — the entire architecture pivots on that
threshold.

**Zero runtime dependencies.** Pure Python 3.11+ stdlib. It ships with a
deterministic mock cortex, so the whole mind runs, demos, and tests offline
with no API key; flip one config line to run it on the Anthropic API.

```
pip install .        # optional — or just run from the repo root:
python -m limen demo
```

## What you'll see

```
t=001 ⚡0.76 ignition (2 bids)
      ★ perception/question p=0.76 :: I'm planning to migrate our blog…
      ★ perception/reminder_request p=0.66 :: Schedule 'email Dana' in 6 ticks.
t=002 ⚡0.41 ignition (3 bids)
      ★ oracle/verdict p=0.41 :: Consensus view… [forks: 3, disagreement: 0.83]
      ★ planner/plan p=0.41 :: PLAN: 1. Clarify the goal…
      ★ librarian/memory p=0.31 :: Memory (0.80): User intends: migrate blog…
t=003 ⚡0.37 ignition
      ★ speaker/utterance_draft :: Here's where I've landed…
🗣  Here's where I've landed on planning: … my internal review didn't fully
    agree, so treat this as a leaning, not a verdict …
t=004 · idle (top 0.18 < 0.25)          ← sub-liminal tick; a wandering
t=007 ⚡0.45 ignition                       thought bid 0.18 and lost
      ★ introspector/alarm :: confusion index 0.62 …
      ★ perception/reminder :: Reminder from your past self: email Dana…
🗣  ⏰ Reminder from your past self: email Dana about the DNS cutover
```

At tick 9 the user reverses their decision; the belief ledger detects the
contradiction, deprecates the stale belief (kept, cross-linked, auditable),
and keeps the new one. At tick 15 the mind **sleeps**: replays its episodic
log, distills lessons ("verify current status before advising — positions
reverse"), writes them as decaying beliefs, prunes the forgotten.

Every bit of that behavior is glue code around a frozen model. That is the
thesis.

## Architecture at a glance

```
                        ┌────────────────────────────────┐
   user / world ──────► │  INBOX (percepts)              │
   future_self  ──────► │  ← TIMEKEEPER fires intentions │
   interoception ─────► │    reminders · dead-man        │
                        └───────────────┬────────────────┘
                                        ▼ every tick
     ┌───────────────────────────────────────────────────────────┐
     │ SPECIALISTS (parallel, unconscious)                       │
     │ perception goals planner critic librarian introspector    │
     │ oracle(→ENSEMBLE fork·cluster·merge) scribe speaker       │
     │ wanderer                                                  │
     └────────────┬───────────────────────────────▲──────────────┘
                  │ Proposals (bids)              │ broadcast to all
                  ▼                               │
     ┌─────────────────────────────┐   ┌──────────┴──────────────┐
     │ ATTENTION AUCTION           │──►│ GLOBAL WORKSPACE        │
     │ salience × novelty ×        │   │ ≤800 tokens · ≤7 items  │
     │ ¬habituation × goal-rel     │   │ TTL decay               │
     │ + coalitions ≥ LIMEN? ──────┼──►│ (= conscious contents)  │
     └─────────────────────────────┘   └──────────┬──────────────┘
                  │ ignition                      │ act phase
                  ▼                               ▼
     ┌─────────────────────────────┐   ┌─────────────────────────┐
     │ MEMORY                      │   │ TOOLBELT (sandboxed)    │
     │ episodic JSONL (all events) │◄──┤ respond · note ·        │
     │ belief ledger (decay,       │   │ schedule · goals ·      │
     │  provenance, contradiction) │   │ remember                │
     │ skills (self-written md)    │   └─────────────────────────┘
     │ SLEEP: replay→distill→prune │
     └─────────────────────────────┘
     INTEROCEPTION: confusion = f(ignition rate, fork disagreement,
     failures) → alarms re-enter as percepts.   BUDGET: hard token cap/day.
```

## Quickstart

```bash
python -m limen demo                     # scripted 26-tick life, offline
python -m limen run                      # REPL: your lines are stimuli
python -m limen ask "Should we rewrite billing in Rust?" --trace
python -m limen tick -n 10               # let it think unattended
python -m limen inspect beliefs          # …workspace|metrics|episodic|skills|intentions|status
python -m limen daemon --period 5        # free-run on wall time
```

Python API:

```python
from limen import Mind
mind = Mind.from_config("limen.toml")
mind.stimulate("Should we migrate the blog?")
replies, trace = mind.run_until_response()
```

Real cortex: set `ANTHROPIC_API_KEY`, and in `limen.toml`:

```toml
[provider]
kind = "anthropic"
model = "claude-opus-4-8"        # payload auto-adapts per model generation

[provider.models]                # optional: route purposes to models
oracle = "claude-haiku-4-5"      # cheap persona forks; Opus keeps the merge

[embeddings]
kind = "openai"                  # optional: semantic similarity via any
base_url = "http://localhost:11434/v1"   # /v1/embeddings server (or "voyage")

[sensors]
watch_dirs = ["~/notes/inbox"]   # optional: the world, arriving as percepts
```

## The pieces

| Subsystem | File | One line |
|---|---|---|
| Cognitive cycle | `limen/cycle.py` | The 9-step tick everything lives inside |
| Attention auction | `limen/attention.py` | salience × novelty × ¬habituation × goal-relevance, coalitions, **the ignition threshold** |
| Global workspace | `limen/workspace.py` | ≤7 items / ≤800 tokens of "consciousness", TTL decay |
| Specialists | `limen/specialists/` | Ten unconscious processors; workspace is their only channel |
| Episodic memory | `limen/memory/episodic.py` | Append-only JSONL autobiography |
| Belief ledger | `limen/memory/ledger.py` | Confidence half-life, provenance, contradiction reconciliation |
| Skills | `limen/memory/procedural.py` | Self-written markdown procedures |
| Sleep | `limen/memory/consolidation.py` | Replay → distill → write → prune |
| Timekeeper | `limen/timekeeper.py` | Reminders, recurrences, dead-man switches |
| Population | `limen/population.py` | Fork K personas, cluster, disagreement ≈ semantic entropy |
| Interoception | `limen/interoception.py` | Confusion index; feelings the mind can act on |
| Providers | `limen/providers/` | Mock (deterministic) + Anthropic (stdlib urllib), budget-metered, cached, per-purpose model routing |
| Sensors | `limen/sensors.py` | File & RSS channels → percepts; the auction triages, habituation de-spams |
| Embeddings | `limen/embeddings.py` | Optional semantic similarity behind one seam — Voyage, or any OpenAI-compatible local server (LM Studio, llama-server, vLLM, Ollama), stdlib urllib |
| Evals | `evals/` | Ablation matrix: what does each mechanism buy, at equal token budget? |

## Documentation

| Doc | Contents |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | The tick, step by step; every data flow; module map |
| [docs/THEORY.md](docs/THEORY.md) | GWT → code mapping; what this is and is *not* a claim about |
| [docs/MEMORY.md](docs/MEMORY.md) | Schemas and the exact decay / reinforcement / contradiction math |
| [docs/SPECIALISTS.md](docs/SPECIALISTS.md) | The specialist contract; each built-in; writing your own |
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | Every config key, default, and tuning note |
| [docs/API.md](docs/API.md) | Python API reference |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | Budgets, sandboxing, daemons, cost & safety |
| [docs/DESIGN_DECISIONS.md](docs/DESIGN_DECISIONS.md) | Why it is the way it is (ADRs) |

## Tests & evals

```bash
python -m unittest discover -s tests     # 78 tests, offline, < 1 second
python -m evals.run                      # ablation matrix, offline, seconds
```

The integration test lives a full 26-tick life and asserts the whole story:
ignition, ensemble disagreement, speech, the fired reminder, the belief
contradiction, sleep lessons, bounded workspace, byte-identical determinism
across same-seed twins.

The eval harness asks the harder question — *what does each mechanism
buy?* — by re-living scripted scenarios (prospective memory, belief
revision, rumination, distraction, consolidation) with one mechanism
removed per arm, on paired seeds at equal token budget. Offline results
already separate the arms: without habituation the mind ruminates (5
repeat ignitions vs 0), without the scribe/librarian belief revision
fails, without sleep nothing is ever learned. Run it against the real
API with `--provider anthropic` for the cognition-level numbers.

## What LIMEN is not

It is not a claim that anything here is conscious. It is a demonstration
that the *functional organization* GWT describes — parallel specialists, a
capacity-limited broadcast bottleneck, ignition, habituation, sleep — can
be built today from a frozen LLM and a few hundred lines of glue, and that
doing so buys real capabilities: patience, initiative, memory with
provenance, calibrated self-doubt. See [docs/THEORY.md](docs/THEORY.md)
for the careful version.

## Contributing

Issues and PRs welcome. Two things to know before opening one: the
project's constraints are deliberate and documented — read
[docs/DESIGN_DECISIONS.md](docs/DESIGN_DECISIONS.md) first (in particular:
**zero runtime dependencies** and **workspace-only specialist
communication** are load-bearing, and PRs that relax them will be
declined) — and `python -m unittest discover -s tests` plus
`python -m evals.run` must stay green and offline.

MIT licensed. Have fun in there.
