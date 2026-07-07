# LIMEN Architecture

This document specifies exactly how a LIMEN mind works — every phase of the
cognitive cycle, every datatype crossing a boundary, every formula. For the
picture version first, see [DIAGRAM.md](DIAGRAM.md). Reading order: this
file, then [MEMORY.md](MEMORY.md), then [SPECIALISTS.md](SPECIALISTS.md).

## 1. The three datatypes (`limen/bus.py`)

Everything that moves between subsystems is one of three dataclasses. If
you can serialize these, you can serialize the entire stream of
consciousness — and LIMEN does, to `episodic.jsonl`.

**Percept** — pre-conscious input arriving at the edge of the mind.

| field | type | meaning |
|---|---|---|
| `source` | str | channel: `user`, `future_self`, `interoception`, `tool` |
| `content` | str | the raw material |
| `salience_hint` | float [0,1] | the channel's own urgency estimate |
| `tags` | list[str] | routing labels (e.g. `deadman`, `scheduled`) |
| `tick`, `id` | int, str | stamped on arrival |

**Proposal** — a specialist's bid for consciousness.

| field | type | meaning |
|---|---|---|
| `author` | str | specialist name |
| `content` | str | what would become conscious |
| `salience` | float [0,1] | the author's importance estimate |
| `kind` | str | routing hint: `question`, `statement`, `plan`, `verdict`, `risk`, `memory`, `reminder`, `alarm`, `reminder_request`, `utterance_draft`, `daydream`, `goal_stale`, `social`, `note` |
| `coalition` | str \| None | proposals sharing a tag pool strength |
| `meta` | dict | structured payload, never rendered into prompts |

**Broadcast** — a proposal after ignition. Wraps the proposal and adds
`priority` (its winning auction score), `tick`, and `ttl` (remaining ticks
of workspace residence).

## 2. The cognitive cycle (`limen/cycle.py`)

One tick = one pass of the following nine phases, in this exact order.
Several invariants depend on the ordering; do not rearrange casually.

### Phase 1 — WAKE
`clock.advance()`; `metrics.on_tick_start(tick)` rolls the budget day when
`tick // budget.day_ticks` changes (spent-counter resets to zero).

### Phase 2 — FUTURES
`timekeeper.collect_due(tick, seen_tags)`:

* `seen_tags` is the union of `tags` on every episodic event logged since
  the previous scan (`Mind.drain_seen_tags`). Any pending **dead-man
  switch** whose `watch_tag` appears in `seen_tags` is silently disarmed —
  the watched-for event happened.
* One-shot intentions with `due_tick <= tick` fire once and archive.
* Recurring intentions fire and reschedule to `tick + every`.
* Dead-man switches with `tick - armed_tick >= within` fire (**absence** as
  a trigger).

Every firing becomes a `Percept(source="future_self", salience_hint=0.8…0.85)`
prefixed `"Reminder from your past self:"` or `"DEAD-MAN TRIPPED:"`.

### Phase 3 — SENSE
Two sources, in order:

1. **Sensors** (`limen/sensors.py`) — every registered channel's
   `poll(tick)` runs on a thread under the same watchdog + exception guard
   as specialists (a failing sensor contributes nothing plus a
   `note_failure`). Built-ins: `FileWatcher` (directory changes) and
   `RSSWatcher` (feed digests); both batch their news into digest percepts
   and persist seen-state under `data_dir/sensors/`. Channels assign
   salience *hints*; the auction decides what matters. Sensors are the
   interface layer — they may touch wall time and the network; their
   output is tick-stamped percepts like any other.
2. **Inbox** — `Mind.drain_inbox()` empties the stimulus queue filled by
   `Mind.stimulate()` (user messages, external events).

All fresh percepts — fired intentions, sensor output, stimuli — are
tick-stamped and logged as `stimulus` events.

### Phase 4 — BID
An immutable **MindView** is assembled:

```
MindView(tick, conscious=workspace.render(), fresh_percepts,
         goals_text, metrics=metrics.snapshot(), workspace)
```

Every enabled specialist's `perceive(view)` runs **concurrently**
(`asyncio.gather`), each wrapped in a watchdog
(`cycle.max_specialist_secs`) and an exception guard: a crashing specialist
contributes zero proposals and a `metrics.note_failure` entry — a mind
should *feel* its component failures, not die of them. All returned
proposals are flattened and tick-stamped.

Heavy LLM work happens **here**, in perceive — because its output must then
compete for consciousness like everything else. The act phase is for
effectors only.

### Phase 5 — AUCTION (`limen/attention.py`)
Each proposal is scored:

```
priority(p) = salience
            × (α + (1−α) · novelty)          α = novelty_floor        (0.40)
            × (1 − β · habituation)          β = habituation_strength (0.70)
            × (γ + (1−γ) · goal_relevance)   γ = goal_floor           (0.50)
```

* **novelty** = `1 − max(similarity(p.content, b.content) for b in last
  recent_window broadcasts)`. Similarity defaults to
  `max(difflib ratio, keyword Jaccard)` (`util.heuristic_similarity`) and
  is upgradable to an embedding backend via `util.set_similarity_backend`
  / the `[embeddings]` config — one seam sharpens novelty, dedup, belief
  merging, clustering, and retrieval at once (see `limen/embeddings.py`).
  A repeat of what's already been conscious is discounted toward the α
  floor.
* **habituation** is per-`(author, topic-hash)` fatigue, where topic-hash
  is a hash of the proposal's sorted top-6 keywords. Each auction **win**
  adds `habituation_gain` (0.25, capped 0.95); every tick it decays
  multiplicatively by `habituation_decay` (0.90). Novelty compares
  *content*; habituation tracks *who keeps winning about what*. Both are
  needed: novelty stops echo, habituation stops monomania.
* **goal_relevance** = `similarity(p.content, goal_stack_text)`; when no
  goals are active the term is neutral (0.5 is substituted). This is
  top-down attention; salience is bottom-up.

**Coalitions.** Proposals sharing a `coalition` tag pool strength:

```
final(p) = clamp( base(p) + coalition_bonus · Σ base(allies) )
```

Weak evidence that agrees can outbid strong evidence standing alone.
Perception tags every proposal derived from one percept with
`pct:<percept_id>`, so a question and its embedded reminder-request rise
together.

**Ignition.** Proposals are ranked by final score. If the top score is
below `ignition_threshold` (0.25), the tick is **idle**: nothing becomes
conscious, nothing is broadcast, no act phase runs. Sub-threshold content
simply never happened, cognitively. That threshold is the limen.

**Admission.** Otherwise, winners fill the workspace budget greedily by
rank. No single item may occupy more than `max_item_fraction` (0.5) of
capacity — oversized proposals are **truncated to fit** (capacity forces
abstraction). Items that don't fit in the remaining budget are skipped
(they may win a later, emptier tick). Each admitted winner reinforces its
habituation key.

### Phase 6a — IGNITION
Winners enter the workspace (`workspace.admit`). A near-duplicate of an
existing resident (same author, similarity > 0.9) *refreshes* it (TTL
reset, priority maxed, and the newer wording adopted — a paraphrase may
carry updated detail) instead of duplicating. Bounds are enforced by
evicting lowest `priority × (0.5 + 0.5·freshness)` until `≤ max_items` and
`≤ capacity_tokens`.

Every **new** broadcast is:
1. appended to the novelty window (`Mind._recent`, deque of 12),
2. logged as a `broadcast` episodic event,
3. counted into the ignition-rate EWMA.

Then the **ACT phase**: the view is re-rendered (the stage just changed)
and every specialist's `act(new_broadcasts, view, tools)` runs
concurrently under the same guards. Actions go exclusively through the
**Toolbelt** (`limen/tools.py`): `respond`, `write_note`, `schedule`,
`arm_deadman`, `add_goal`, `complete_goal`, `remember`. Every tool call is
episodic-logged — the mind cannot act secretly from itself or its human.

### Phase 6b — IDLE
`metrics.record_idle()` grows the idle streak (feeding confusion, the
wanderer's activation condition, and the sleep trigger) and logs an `idle`
event recording the losing top bid.

### Phase 7 — DECAY
`workspace.age()` decrements TTLs and evicts the expired; unrefreshed
content is conscious for `item_ttl` (3) ticks. `attention.end_of_tick()`
decays all habituation levels.

### Phase 8 — SLEEP?
Consolidation runs when `tick − last_sleep ≥ sleep.every_ticks` (24) **or**
the idle streak reaches `sleep.idle_trigger` (6). See
[MEMORY.md §4](MEMORY.md) for the replay → distill → write → prune
pipeline. The sleep report is logged and returned on the `TickResult`.

### Phase 9 — EXPRESS
The Toolbelt outbox is drained into `TickResult.utterances`. **Only the
interface layer** (CLI, daemon, or your code) delivers speech; the mind
queues it. `TickResult` carries: `tick, ignited, top_priority, threshold,
winners, utterances, sleep_report, proposal_count`.

## 3. Information flow rules

1. **Specialists never talk to each other.** The workspace is the only
   channel. For A to influence B, A's content must win the auction. This
   bottleneck is not an implementation shortcut — it *is* the theory.
2. **Reads are free, writes are tooled.** Specialists may read memory
   (librarian, wanderer) at perceive time; every mutation goes through the
   Toolbelt and is logged.
3. **LLM calls only in perceive (and sleep).** Act is cheap and effector-
   only, keeping worst-case tick cost = (number of LLM specialists that
   triggered) concurrent calls.
4. **Nothing branches on wall time.** All cognition is in ticks; the daemon
   maps ticks to seconds. This is what makes a 26-tick life a unit test.

## 4. The speech loop (worth spelling out)

The Speaker does not blurt. When a goal is active and a `verdict`/`plan`
is conscious, it drafts a reply (LLM) and bids the **draft** into
consciousness (`kind="utterance_draft"`). Only when the draft itself wins
the auction — the mind has "heard itself about to speak," and the Critic
had the same tick to bid a risk alongside — does `act` deliver it via
`tools.respond` and complete the goal. Reflex speech (relaying a fired
reminder, acking a recorded decision) skips the draft stage.

## 5. Interoception feedback loop (`limen/interoception.py`)

Per-tick vitals: ignition-rate EWMA (`ewma_alpha` 0.30), mean winning
priority, last ensemble disagreement, provider stats (calls, cache hits,
failures, tokens), budget fraction remaining. Headline number:

```
confusion = 0.4·(1 − ignition_rate) + 0.4·disagreement + 0.2·failure_rate
```

When `confusion ≥ confusion_threshold` (0.60) or budget fraction ≤
`budget_alarm_fraction` (0.20), the **Introspector** bids an alarm percept
(salience 0.7 / 0.8). Each alarm fires once and re-arms only after its
condition clears. The mind can therefore *change strategy because of how
it feels* — hedge, ask the user, defer spending.

## 6. Population deliberation (`limen/population.py`)

Trigger: a `question` broadcast with priority ≥ `population.min_salience`
(0.55) and no verdict yet — one *successful* ensemble per question, ever;
a failed fork (API error, budget) cools the question down for 3 ticks and
may retry, so one transient failure doesn't permanently silence
deliberation. Pipeline:

1. **fork** — K concurrent persona-flavored completions (temperature 0.8;
   diversity is the point).
2. **cluster** — greedy agglomerative: an answer joins the first cluster
   whose representative it matches at ≥ `cluster_threshold` (0.62), else
   founds a new one.
3. **disagreement** = `0.5·(1 − |largest|/K) + 0.5·H(cluster sizes)/ln K`
   — a zero-dependency cousin of semantic entropy (Farquhar et al.,
   *Nature* 2024): meaning-level disagreement among samples predicts
   confabulation better than any single sample's stated confidence.
4. **merge** — LLM synthesis: majority view + strongest minority objection
   ("Dissent: …"), never averaged away. The merged text is bid as a
   `verdict` with `salience = 0.6 + 0.15·confidence`, and the disagreement
   number flows to interoception and into the Scribe's stored confidence.

## 7. Providers (`limen/providers/`)

One choke point: `await provider.complete(LLMRequest)`. The
`MeteredProvider` base wires, in order: content-addressed **disk cache**
(requests flagged `deterministic`, or legacy temperature ≤ 0.1) →
**budget pre-spend** (estimate; raises `BudgetExceeded` when exhausted and
`hard_stop`) → `_raw_complete` → **settle** (replace estimate with real
usage) → **stats**. Token estimation is `max(chars/4, words)`; real API
usage numbers override it at settle time.

**Per-purpose model routing** also lives in `MeteredProvider`: the
`[provider.models]` table maps a request's `purpose` label to a model id
(fallback: `provider.model`), and the cache is keyed by the routed model.
Routing in the provider-agnostic layer means any future provider inherits
it. Responses carry `stop_reason`; `Specialist.ask` converts `refusal`
into an interoceptive failure (returns None) and notes `max_tokens`
truncation.

* `MockProvider` — deterministic, seeded, role-aware templates keyed on
  the system prompt (`persona:`, planner, critic, distill, merge, speaker).
  A wind tunnel: shaped airflow for testing the airframe.
* `AnthropicProvider` — stdlib `urllib` POST to the Messages API,
  exponential backoff + jitter on 408/409/429/5xx/529 (honoring numeric
  `retry-after`), calls pushed to a thread so the specialist fan-out stays
  concurrent. The payload adapts to the (routed) model's generation:
  current-gen models omit `temperature` (the API rejects sampling params);
  Sonnet 5 gets `thinking` explicitly disabled so small `max_tokens` buys
  text rather than empty thinking blocks. Model/keys in config and
  environment only.

## 8. Persistence layout

```
<data_dir>/
├── episodic.jsonl      append-only autobiography (every event)
├── beliefs.json        the ledger (all statuses, full provenance)
├── intentions.json     pending + archived intentions
├── skills/             self-written procedures (*.md + _index.json)
├── notes/              Toolbelt write_note sandbox
├── sensors/            per-sensor seen-state (survives daemon restarts)
└── cache/              content-addressed LLM responses
    └── embeddings/     content-addressed vectors (each text embedded once)
```

Everything is human-readable JSON/markdown. `rm -rf <data_dir>` is a
lobotomy; copying it is a backup; diffing two of them is science.

## 9. Determinism

With `mind.seed` set, the mock provider, and `embeddings.kind = "none"`:
identical stimuli at identical ticks ⇒ **byte-identical utterances and
ledgers** across runs (asserted by `test_determinism_same_seed_same_life`).
Sources of entropy — id suffixes, wanderer sampling, mock text — all draw
from the seeded RNG. With the Anthropic provider, determinism naturally
ends at the API boundary; the cache restores it for deterministic-flagged
calls. An embedding backend is deterministic only insofar as its vectors
are cached (each text is embedded exactly once, so replays from a warm
cache are stable).
