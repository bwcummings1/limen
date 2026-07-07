# Operating a LIMEN Mind

## Running modes
* **REPL** — `python -m limen run`. Your lines are stimuli; `/tick N`,
  `/inspect WHAT`, `/quit`.
* **One-shot** — `python -m limen ask "…" [--trace]` (ticks until it
  speaks, max 8 by default).
* **Batch time** — `python -m limen tick -n 24 [--stimulus "…"]`.
* **Daemon** — `python -m limen daemon --period 5` maps one tick to five
  wall-seconds. At `--period 900` and `day_ticks=96` a budget-day is one
  real day. Stop with Ctrl-C; state persists; restarting resumes from disk
  (episodic hot window, ledger, intentions all reload).
* **Embedded** — construct a `Mind` in your process and call
  `tick_async()` from your own loop (see docs/API.md).

## Cost control (real provider)
Defense in depth, all in `[budget]`/`[provider]`:
1. **Hard daily cap** — pre-flight estimated spend, post-flight settle
   with real usage; `hard_stop=true` raises `BudgetExceeded`, which
   surfaces as an interoceptive failure and a budget alarm the mind can
   *act on* (it will prefer cheap behavior; the speaker still relays
   reminders — no LLM needed).
2. **Trigger discipline** — LLM specialists gate on workspace conditions;
   provider failures cool a target down for 3 ticks (lost auctions may
   retry within the target's TTL window, which bounds the episode); an
   idle mind makes zero calls. Worst observed: the demo's 26-tick life
   = 8 calls.
3. **Cache** — deterministic-flagged calls (sleep distills, ensemble
   merges; legacy temperature ≤ 0.1) are content-addressed on disk;
   identical days are free.
4. **Estimator honesty** — `max(chars/4, words)` runs high on English
   prose, so the cap errs conservative until real usage reconciles it.

Watch spending live: `python -m limen inspect metrics`
(`calls_by_purpose`, `tokens_in/out`, `budget_remaining_frac`).

## Safety posture
* **No self-directed effectors.** The Toolbelt has no exec, no shell, no
  network. Adding an effector is a code+config decision a human makes.
* **Filesystem sandbox** — writes confined to `data_dir/notes/` with
  path-traversal checks; skills/ledger writes go through typed APIs.
* **Human-delivered speech** — `respond()` only queues; the interface
  layer decides delivery.
* **Total auditability** — every broadcast, tool call, belief write,
  contradiction, alarm, and sleep is one greppable JSONL line. The stream
  of consciousness *is* the audit log.
* **No secret state** — everything on disk is human-readable JSON/markdown;
  `diff` two data_dirs to see exactly how two lives diverged.

## Backup, reset, surgery
`data_dir` is the whole mind. Copy it = snapshot. Delete it = fresh mind.
Hand-edit `beliefs.json` (it's validated on load) = neurosurgery. Delete
`cache/` any time; it only costs money to rebuild.

## Anthropic provider setup
```bash
export ANTHROPIC_API_KEY=sk-ant-…
```
```toml
[provider]
kind = "anthropic"
model = "claude-opus-4-8"     # any Messages-API model id; payload auto-adapts
                              # (cheaper: claude-sonnet-4-6, claude-haiku-4-5)

[provider.models]             # optional: route purposes to different models
oracle = "claude-haiku-4-5"   # 3 parallel persona forks — cheap and chatty
critic = "claude-haiku-4-5"
consolidation = "claude-opus-4-8"  # sleep writes long-term memory — spend here
```
Endpoint, retry, and header details: `limen/providers/anthropic.py`
(stdlib urllib; API reference https://docs.claude.com/en/api/overview).
The payload adapts per model generation (current-gen models drop
`temperature`; Sonnet 5 gets `thinking` disabled so small `max_tokens`
buys text, not thinking blocks); `retry-after` headers are honored;
refusal/truncation stop reasons surface as interoceptive failures.
Rough sizing at defaults: an *active* tick that triggers planner + oracle
(3 forks) + merge + speaker ≈ 6 calls of a few hundred tokens each;
`tokens_per_day=200000` comfortably covers a busy interactive day. Set it
to your own comfort; the meter is the guarantee, not the guess.

## Embeddings setup (optional)
The stdlib similarity heuristic is paraphrase-blind; an embedding backend
sharpens attention novelty, belief merging, clustering, and retrieval in
one config change. Vectors are cached on disk (each text embedded once,
ever) and calls are not budget-metered (~1000× cheaper than completions).

For local, prefer `kind = "openai"` — the OpenAI-compatible
`/v1/embeddings` protocol is what the local-inference world standardized
on, so LM Studio, llama.cpp's `llama-server`, vLLM, and Ollama itself are
all just a `base_url`:

```bash
ollama pull nomic-embed-text           # or load an embed model in LM Studio
export VOYAGE_API_KEY=pa-…             # only for kind = "voyage" (hosted)
```
```toml
[embeddings]
kind = "openai"                        # "voyage" hosted; "none" = heuristic
base_url = "http://localhost:11434/v1" # Ollama; LM Studio: :1234/v1
model = "nomic-embed-text"
```
After switching backends, retune `ledger.merge_threshold` and
`population.cluster_threshold` — cosine distributions are model-specific
(that's what `calibration_floor` coarse-adjusts). Note: a network-backed
similarity ends byte-level determinism unless every vector is already
cached; the mock + `kind="none"` combination stays fully deterministic.

## Sensors (giving the daemon something to perceive)
```toml
[sensors]
watch_dirs = ["~/notes/inbox"]         # new/changed files become percepts
rss_feeds = ["https://example.com/feed.xml"]
rss_every_ticks = 12                   # at --period 900: every 3 hours
```
Sensors poll in the SENSE phase, digest their news (one percept per
batch), persist seen-state under `data_dir/sensors/`, and — like
specialists — fail into interoception rather than crashing the tick.
Compose with dead-man switches: a log-scanning sensor that tags percepts
`backup_ok` feeds `tools.arm_deadman("no backup!", "backup_ok", within=N)`.
Custom channels: subclass `limen.sensors.Sensor`, implement
`poll(tick) -> list[Percept]`, register with `mind.add_sensor(...)`.

## Evals (the ablation matrix)
`evals/` measures what each mechanism buys — same seeds, same budget,
one mechanism removed per arm:

```bash
python -m evals.run                              # offline (mock), seconds
python -m evals.run --scenarios rumination --arms full,no_habituation
python -m evals.run --provider anthropic --seeds 7   # real cortex, costs money
```

Scenarios: prospective_memory, belief_revision, rumination, distraction,
consolidation. Arms: full, no_habituation, no_threshold, no_sleep,
no_reflection, no_ensemble. Read the deltas against `full`: offline
results already show the architecture working (e.g. rumination repeat
ignitions: full = 0, no_habituation = 5; belief revision fails without
the scribe/librarian; consolidation fails without sleep). `*_ok` metrics
— higher is better; `repeat_*`/`zombie_*` — lower is better.

## Troubleshooting
* **"mind had nothing to say"** — it idled; `--trace`/`-v` to watch bids,
  lower `ignition_threshold`, or just `/tick` a few times.
* **Same answer every run** — that's `seed=7` + mock. Remove the seed or
  switch providers.
* **`BudgetExceeded` in logs** — by design; raise the cap or wait for the
  day roll. The mind stays alive (idles, sleeps, relays reminders).
* **Unknown config key error** — deliberate strictness; check spelling
  against docs/CONFIGURATION.md.
