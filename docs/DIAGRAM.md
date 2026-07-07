# LIMEN, drawn

One page of pictures for the whole machine. Everything here is accurate to
the code; file references point at the implementation. Read alongside
[ARCHITECTURE.md](ARCHITECTURE.md), which specifies the same flow in prose.

## 1. The whole mind, one tick

Content enters as **Percepts**, becomes **Proposals** (bids), and — only if
it wins the auction and clears the threshold — becomes a **Broadcast**:
conscious content every specialist sees next tick. That funnel is the
entire architecture; everything else feeds it or reacts to it.

```
              THE WORLD                          THE FUTURE
     user · watched files · feeds       reminders · recurrences ·
   (stimulate() and sensors.py)          dead-man switches (timekeeper.py)
                 │                                   │
                 └───────────────┬───────────────────┘
                                 ▼
                             PERCEPTS                    pre-conscious input
                                 │
      ┌──────────────────────────┼───────────────────────────────────┐
      │                          ▼                                   │
      │    ╔════════ THE UNCONSCIOUS AUDIENCE (specialists/) ═════╗  │
      │    ║  run concurrently, every tick, on an identical view  ║  │
      │    ║                                                      ║  │
      │    ║  perception  goals  planner  critic  librarian       ║  │
      │    ║  introspector  scribe  speaker  wanderer             ║  │
      │    ║  oracle ──► ensemble: fork K personas, cluster,      ║  │
      │    ║             measure disagreement, merge with dissent ║  │
      │    ╚══════════════════════════╤═══════════════════════════╝  │
      │                               │  Proposals (bids)            │
      │                               ▼                              │
      │    ┌───────────── ATTENTION AUCTION (attention.py) ───────┐  │
      │    │                                                      │  │
      │    │  priority = salience            (author's urgency)   │  │
      │    │           × (α + (1−α)·novelty) (repeats discounted) │  │
      │    │           × (1 − β·habituation) (chronic winners     │  │
      │    │                                  fatigue)            │  │
      │    │           × (γ + (1−γ)·goal_relevance)  (top-down)   │  │
      │    │           + coalition bonus     (allies pool)        │  │
      │    └────────┬───────────────────────────────┬─────────────┘  │
      │             │                               │                │
      │   top bid ≥ threshold             top bid < threshold        │
      │             │                               │                │
      │             ▼  IGNITION                     ▼  IDLE          │
      │    ┌─ GLOBAL WORKSPACE ──┐        nothing becomes conscious; │
      │    │  (workspace.py)     │        the bid never happened,    │
      │    │  ≤ 7 items          │        cognitively. Idle streaks  │
      │    │  ≤ 800 est. tokens  │        feed confusion, wake the   │
      │    │  TTL 3 ticks        │        wanderer, and eventually   │
      │    │  oversized bids are │        trigger sleep.             │
      │    │  truncated to fit   │                                   │
      │    └────────┬────────────┘        ── the threshold is the    │
      │             │                        limen the project is    │
      │             │ BROADCAST              named for ──            │
      │             │                                                │
      └─────────────┘ winners are rendered into every specialist's   │
                      view next tick ────────────────────────────────┘
                    │
                    │ ACT PHASE (ignition ticks only; effectors, no LLM)
                    ▼
           ┌─────────────── TOOLBELT (tools.py) ───────────────┐
           │  respond · schedule · arm_deadman · add_goal ·    │
           │  complete_goal · remember · write_note            │
           │  — every call logged; no exec, no shell, no net — │
           └─────┬──────────────┬──────────────┬───────────────┘
                 ▼              ▼              ▼
              OUTBOX       TIMEKEEPER    BELIEF LEDGER
           (speech; the   (intentions     (claims with decay,
            interface      for future     provenance, and
            layer          ticks)         contradiction
            delivers)                     handling)
```

Iron rule: specialists never talk to each other. For A to influence B,
A's content must win the auction and become conscious. The bottleneck is
not an implementation shortcut — it is the theory (ADR-5).

## 2. Anatomy of an answer

The temporal shape a static diagram can't show — how a question becomes
speech over four ticks (this is the demo's actual trace):

```
   tick 1              tick 2              tick 3              tick 4
─────────────────────────────────────────────────────────────────────────
 user question ──►  planner drafts    speaker sees goal    the stage
 IGNITES            a PLAN            + verdict, drafts    empties as
                                      a reply; the DRAFT   TTLs expire;
 goals specialist   oracle forks      itself must win      idle ticks
 opens a goal       K personas,       the auction —        resume
 (act phase)        measures dis-     "the mind hears
                    agreement,        itself about to
 workspace:         merges a          speak" (ADR-9)
 ┌───────────┐      VERDICT           critic bids RISK
 │ question  │                        the same tick
 └───────────┘      workspace:        ─ its window ─
                    ┌───────────┐     workspace:          workspace:
                    │ question  │     ┌────────────┐      ┌──────────┐
                    │ verdict   │     │ draft      │      │ (decay)  │
                    │ plan      │     │ risk       │      └──────────┘
                    │ memory    │     │ verdict…   │
                    └───────────┘     └────────────┘
                                            │
                                       act: draft won →
                                       respond() + goal
                                       completed  🗣
```

Reflex speech (relaying a fired reminder, acknowledging a decision) skips
the draft stage — deliberation is for utterances that can be wrong.

## 3. The feedback loops

Three loops close the system on itself. This is where "feelings" and
"forgetting" live.

```
 INTEROCEPTION (interoception.py)          every tick
 ┌─────────────────────────────────────────────────────────────┐
 │  1 − ignition rate  ─┐                                      │
 │  fork disagreement  ─┼─►  confusion = 0.4·a + 0.4·b + 0.2·c │
 │  tool failure rate  ─┘         │                            │
 │                                ▼                            │
 │            confusion ≥ 0.60  or  budget ≤ 20% ?             │
 │                                │                            │
 │                                ▼                            │
 │      introspector bids an ALARM percept into the auction    │
 │      → the mind can change strategy because of how it feels │
 └─────────────────────────────────────────────────────────────┘

 BUDGET (providers/base.py)                every LLM call
 ┌─────────────────────────────────────────────────────────────┐
 │  estimate → spend → call → settle with real usage           │
 │  exhausted + hard_stop → BudgetExceeded → interoceptive     │
 │  failure → budget alarm → cheaper behavior until day rolls  │
 └─────────────────────────────────────────────────────────────┘

 SLEEP (memory/consolidation.py)    every 24 ticks / 6 idle ticks
 ┌─────────────────────────────────────────────────────────────┐
 │  episodic replay ─► LLM distills ─► LESSON → belief ledger  │
 │  (since last          ≤ 5 lines     PROCEDURE → skill store │
 │   sleep)                                                    │
 │                 then: all confidences decay to present      │
 │                 value; beliefs below 0.05 are deprecated    │
 │                 — that is what forgetting is here           │
 └─────────────────────────────────────────────────────────────┘
```

## 4. Where thought is rented

Every LLM call funnels through one interface. The provider layer is where
cost, caching, and model choice live — cognition never touches HTTP.

```
      specialist.ask(...)   ensemble.fork(...)   consolidator.run(...)
                └───────────────┬──────────────────────┘
                                ▼
              MeteredProvider.complete(LLMRequest)
                                │
              cache? ── deterministic requests are content-
                │       addressed on disk; replays are free
              budget ── pre-spend estimate; BudgetExceeded
                │       when the day's tokens are gone
              route ─── request.purpose → [provider.models]
                │       (oracle → cheap forks, consolidation
                │        → strong model, …)
                ▼
        ┌── MockProvider ──────── deterministic templates; the
        │                         whole mind tests offline
        └── AnthropicProvider ─── stdlib urllib → Messages API;
                                  payload adapts per model
                                  generation; retries honor
                                  retry-after
```

The same seam pattern repeats twice more: similarity (heuristic by
default, embeddings by config — `embeddings.py`) and senses (files and
feeds in, percepts out — `sensors.py`). Swap the edges; the mind in the
middle never changes.
