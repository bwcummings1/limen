# Design Decisions (ADRs)

**ADR-1 · Zero runtime dependencies.** The thesis is "an inner life from
glue code and JSON files"; a lockfile would blunt it. Costs: a cheap token
estimator, difflib-grade similarity, hand-rolled HTTP. All are isolated
behind `util.py`/`providers/` seams — swap in tiktoken/embeddings/httpx
without touching cognition.

**ADR-2 · Ticks, not wall time.** Cognition must be testable, replayable,
and fast-forwardable; only the daemon knows about seconds. Consequence: a
full life is a <1s unit test, and "sleep every 24 ticks" means the same
thing on a laptop and a server.

**ADR-3 · JSON/JSONL/markdown, not SQLite.** Human-inspectability beats
query power at this scale. Append-only episodic + load-rewrite ledger keeps
crash consistency trivial. Revisit if episodic files reach millions of
lines (the hot ring buffer already isolates the read path).

**ADR-4 · Mock-first development.** The architecture is the claim, so the
architecture must run and test with zero keys. The deterministic mock also
buys byte-identical replays — the difference between "it seems to work"
and a 37-test suite.

**ADR-5 · Workspace-only communication (the iron rule).** Direct
specialist↔specialist calls would be easier and would quietly turn LIMEN
into a message-passing multi-agent system. The bottleneck is load-bearing:
it produces seriality, auditability, and the sub-liminal/conscious
distinction the project exists to demonstrate.

**ADR-6 · LLM work in `perceive`, effectors in `act`.** Thought must
compete for consciousness before it can cause action; this also caps
worst-case cost per tick at the number of *triggered* thinkers and makes
the act phase safe to run unconditionally.

**ADR-7 · Truncate-to-fit admission.** When a winning bid exceeds its
capacity share, compress it rather than either rejecting importance or
letting one thought monopolize the stage. Capacity forcing abstraction is
a feature of bounded workspaces, so implement it literally.

**ADR-8 · Heuristic contradiction floor.** Negation-regex + shared-keyword
opposition is crude, but it is *always on*, free, and deterministic; an
LLM judgment can sit above it, never instead of it. Threshold tuned low
(0.30 topicality) because `_opposed`'s ≥2-shared-keywords rule is the real
false-positive guard.

**ADR-9 · Drafts pass through consciousness.** Irreversible acts (speech)
are two-stage: bid the intention, execute on ignition. Buys a critic
window and makes "the mind heard itself about to speak" literal — worth
one tick of latency.

**ADR-10 · Losers are kept.** Contradicted/deprecated beliefs are marked
and cross-linked, never deleted. Memory with provenance is only auditable
if the losing side of every reconciliation remains on the record.

**ADR-11 · Per-purpose model routing lives in the provider-agnostic
layer.** Every `LLMRequest` already carries a `purpose` accounting label;
`[provider.models]` promotes it to a routing key inside `MeteredProvider`
(not the Anthropic subclass), so any future provider inherits routing,
metering, and caching by implementing only `_raw_complete`. The response
cache is keyed by the *routed* model — a routing change can never serve a
stale cross-model response.

**ADR-12 · Cooldowns, not permanent latches.** The original once-per-target
sets in Planner/Critic/Oracle/Speaker were deterministic-mock artifacts: a
real provider fails and a real auction is lost sometimes, and a write-once
latch turns one bad tick into permanent silence. The pattern now: a bid
that won is blocked by `kinds_present()` checks; a lost bid may retry next
tick (bounded by the target's workspace TTL); only provider *failures*
cool down (3 ticks). Act-phase effectors keep plain handled-id sets —
acting twice is worse than acting late.

**ADR-13 · Similarity is a process-global seam; embeddings are a strict
upgrade; negation is never delegated; target the protocol, not the tool.**
For local backends the primary kind is `openai` — the OpenAI-compatible
`/v1/embeddings` shape every 2026 local server exposes (LM Studio,
llama-server, vLLM, Ollama's `/v1`) — so backends are a `base_url`, not a
per-tool integration. The same principle will govern future completion
providers (OpenRouter is an OpenAI-compatible `/v1/chat/completions`
surface). `util.similarity` is used as a
free function from six modules, so the backend is module-global state set
by Mind at construction (one mind per process is the intended shape; twin
tests share a config). The embedding score is blended as
`max(heuristic, calibrated cosine)` — it can only raise similarity, never
lose what difflib caught. The ledger's polarity test stays a regex + shared
-keyword heuristic under every backend, because embeddings notoriously
score a sentence and its negation as near-identical (extends ADR-8).

**ADR-14 · Sensors are peripherals, not cognition.** Channels poll in the
SENSE phase, may touch wall time and the network (the tick-only rule binds
core algorithms), assign salience *hints* only — the auction decides what
matters, habituation is the anti-spam — and must digest (one percept per
batch of news). Seen-state persists so a daemon restart doesn't
re-perceive the world. First run baselines silently: a fresh mind pointed
at a full folder should not drown.

**ADR-15 · Evidence by ablation at equal budget.** The architecture's
claims are tested by removing one mechanism per arm (habituation,
threshold, sleep, reflection, ensemble) and running identical scripted
lives on identical seeds and identical token budgets (`evals/`). The
budget meter makes the fairness control free; determinism makes deltas
attributable. Auction-level effects are measurable offline with the mock
(rumination: full=0 repeat ignitions, no_habituation=5); cognition-level
effects require the real cortex, same harness, `--provider anthropic`.
