# LIMEN Memory Systems

Four systems, one philosophy: **append, decay, reinterpret — never
silently overwrite.** All state is human-readable on disk.

## 1. Episodic memory (`memory/episodic.py`)

The autobiography: `episodic.jsonl`, one JSON object per line, append-only.

**Event kinds:** `stimulus`, `broadcast`, `idle`, `tool`, `utterance`,
`belief_write`, `contradiction`, `ensemble`, `alarm`, `sleep_report`.

**Common fields:** `n` (sequence), `kind`, `tick`, `content` (renderable
text), plus kind-specific payload (`author`/`bkind`/`priority`/`tags` for
broadcasts, `source` for stimuli, `belief_id`/`confidence` for writes,
`disagreement`/`clusters` for ensembles).

**Access paths:**
* a hot ring buffer (last 400 events) serves all per-tick queries with
  zero disk reads and is rewarmed from disk on restart;
* `since_tick(t)` powers sleep replay and dead-man tag scanning;
* `search(query)` is the librarian's similarity scan over hot-window text.

Append-only is a feature: the mind never rewrites its history, it
reinterprets it in the ledger. `grep` is a debugger for the soul.

## 2. The belief ledger (`memory/ledger.py`)

Semantic memory as an auditable claims database: `beliefs.json`.

### Schema

```json
{
  "id": "blf_00003k2fa",
  "claim": "User decided to stay on WordPress rather than migrate",
  "confidence": 0.9,
  "created_tick": 9,
  "updated_tick": 9,
  "half_life": 480,
  "provenance": [{"kind": "scribe", "ref": "tick@9", "tick": 9}],
  "tags": ["user", "decision"],
  "status": "active",              // active | deprecated | contradicted
  "contradicts": ["blf_00001x9qp"]
}
```

### Invariants

1. Nothing is believed without provenance.
2. Confidence is never *stored* fresh — reads apply decay lazily; sleep
   persists the decayed value.
3. Contradictions are detected, logged, reconciled by explicit rule — the
   losing belief is kept, cross-linked, and marked, never deleted.

### The math

**Decay.** Effective confidence at read time:

```
c_eff(t) = c · 0.5^((t − updated_tick) / half_life)
```

Default `half_life` = 480 ticks (5 "days" at 96 ticks/day). Volatile facts
should be asserted with short half-lives; stable ones long. Sleep's
`decay_and_prune` bakes `c ← c_eff(now)` in and deprecates actives below
`prune_floor` (0.05) — that is what forgetting *is* here.

**Reinforcement (noisy-OR).** When a new assertion matches an active
belief at similarity ≥ `merge_threshold` (0.72) with same polarity:

```
c' = 1 − (1 − c_eff)(1 − c_new · κ)        κ = reinforce_kappa = 0.6
```

Independent restatements push confidence up asymptotically — never past 1,
with diminishing returns — and append provenance. Two 0.5 assertions yield
0.65, not 1.0.

**A note on similarity.** Everywhere this document says "similarity", the
metric is `util.similarity` — the stdlib heuristic by default, upgradable
to an embedding backend via `[embeddings]` (see docs/CONFIGURATION.md).
Merging, topicality, and retrieval all sharpen with embeddings; the
*polarity* half of contradiction detection below deliberately does not
use embeddings (they score "we will migrate" ≈ "we won't migrate") — it
stays the regex + keyword heuristic whatever the backend.

**Contradiction.** On every insert, *all* active beliefs are scanned for
an **opposed rival**:

* *opposed* = ≥ 2 shared content keywords **and** exactly one side carries
  a negation/reversal marker (`not`, `never`, `no longer`, `decided
  against`, `instead of`, `rather than`, `stay on`, `cancel`, …);
* *topicality* = `max(similarity, |k_a ∩ k_b| / min(|k_a|, |k_b|))` — the
  overlap coefficient catches short reversals ("we decided to stay") of
  long originals that plain similarity under-scores.

If the best rival's topicality ≥ `contradiction_threshold` (0.30):
**reconcile** — the side with higher effective confidence stays `active`
(ties favor the newer evidence); the other is marked `contradicted`; both
gain `contradicts` cross-links; a `contradiction` event is logged. This
heuristic is the always-on floor beneath any LLM-side judgment; it is
deliberately conservative (the false-positive test in
`test_ledger.py` guards the shared-keyword requirement).

**Retrieval.** `retrieve(query, t)` ranks actives by
`similarity(query, claim) × c_eff(t)` above a floor (0.30) — a strong
recent memory can interrupt; a faint old one can't.

## 3. Procedural memory (`memory/procedural.py`)

Skills the mind writes for itself: markdown files under `skills/` plus a
trigger-keyword index. Sleep promotes `PROCEDURE: <title> :: <body>`
distillations into skill files; the librarian bids relevant skills back
into consciousness when trigger keywords match the workspace. The mind's
competence is partly *files it wrote* — inspectable and editable by its
human.

## 4. Consolidation — sleep (`memory/consolidation.py`)

**Triggers:** every `sleep.every_ticks` (24) ticks, or an idle streak of
`sleep.idle_trigger` (6).

**Pipeline:**

1. **Replay** episodic events since the last sleep (≤ `replay_window`,
   200), *excluding* metabolic noise (`idle`, `sleep_report`), rendered as
   `[t=N kind] text…` lines.
2. **Distill** through the provider at temperature 0 (cacheable), system-
   prompted to emit only `LESSON: …` / `PROCEDURE: title :: body` lines,
   at most `max_lessons` (5). An empty replay skips the call entirely.
3. **Write** lessons via `ledger.assert_claim(conf=0.65, tags=["lesson"])`
   — the ordinary merge/reinforce/contradict machinery applies, so a
   repeated lesson strengthens rather than duplicates. Procedures go to
   the skill store.
4. **Decay & prune** the whole ledger (see §2).
5. **Report**: a `sleep_report` event with lessons, skills written,
   beliefs pruned — so the next morning's librarian can surface "while
   you slept, I learned…".

Budget exhaustion or provider failure during sleep degrades gracefully:
the distillation is skipped, decay/prune still run, the failure lands in
interoception.

## 5. Working memory

Is the workspace itself — see [ARCHITECTURE.md §2](ARCHITECTURE.md)
(admission, refresh-in-place, TTL aging, priority×freshness eviction).
The four systems above are what survives it.
