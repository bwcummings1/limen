# LIMEN and Global Workspace Theory

## The theory, in five sentences

Global Workspace Theory (Bernard Baars, *A Cognitive Theory of
Consciousness*, 1988) models the mind as a **theater**: a vast unconscious
audience of parallel specialist processes, a small stage of working memory,
and a spotlight of attention. Specialists compete — often in coalitions —
for the stage; whatever wins is **broadcast** globally, so every specialist
sees it and can react. Consciousness, on this view, is the *broadcast
state*: serial, capacity-limited, integrative, built atop massively
parallel unconscious machinery. Stanislas Dehaene's Global Neuronal
Workspace program later gave the theory its sharpest empirical signature —
**ignition**, the sudden nonlinear avalanche when a representation crosses
threshold and becomes globally available, versus sub-threshold processing
that stays local and fades. GWT is attractive to engineers because it is a
*functional* theory: it describes an organization, and organizations can
be built.

## The mapping, exactly

| GWT construct | LIMEN implementation | Where |
|---|---|---|
| Unconscious specialist processors | `Specialist` subclasses running concurrently each tick | `specialists/` |
| Sensory periphery | Sensor channels (files, feeds) polled each tick; salience hints in, auction decides | `sensors.py` |
| The stage / working memory | `GlobalWorkspace`: ≤ 7 items, ≤ 800 est. tokens, TTL 3 | `workspace.py` |
| Spotlight / attention | The auction: salience × novelty × ¬habituation × goal-relevance | `attention.py` |
| Coalitions of processors | Shared `coalition` tags pooling bid strength | `attention.py` |
| **Ignition threshold** | `ignition_threshold`; below it a tick is idle and content stays sub-liminal | `attention.py` |
| Global broadcast | Winners rendered into every specialist's next `MindView.conscious` | `cycle.py` |
| Contexts / goal hierarchy (Baars) | The goal stack modulating the auction top-down | `tools.py`, `attention.py` |
| Habituation of the orienting response | Per-(author, topic) fatigue with win-gain and tick-decay | `attention.py` |
| Serial conscious stream atop parallel substrate | One bounded workspace; N concurrent `perceive()` calls | `cycle.py` |
| Working-memory decay | Broadcast TTL aging | `workspace.py` |
| Inner speech heard before uttered | Speaker's draft must itself win the auction before delivery | `specialists/expression.py` |
| Default-mode wandering | The Wanderer's low-salience associations during idle streaks — almost always sub-threshold | `specialists/reflective.py` |
| Sleep consolidation (replay → abstraction → forgetting) | Episodic replay → LLM distillation → ledger writes → decay/prune | `memory/consolidation.py` |
| Interoception / metacognitive feelings | Measured confusion index re-entering as percepts | `interoception.py` |
| Deliberation under uncertainty | Fork-diff-merge ensemble; disagreement ≈ semantic entropy (Farquhar et al., *Nature* 2024) | `population.py` |

Two properties fall out of the implementation rather than being coded in,
which is the encouraging kind of result:

* **Seriality.** Nothing forces one "train of thought," yet the bounded
  workspace plus novelty/habituation discounts produce one: contents
  cohere for a few ticks, then yield. Watch `limen demo` — the migration
  question owns ticks 1–3, then the stage clears.
* **Sub-liminal cognition.** The Wanderer genuinely computes associations
  that genuinely never become conscious (bids of 0.05–0.2 against a 0.25
  limen, visible in idle-tick traces). Processing without access — the
  distinction GWT was built to capture — is directly observable in the
  logs.

## What LIMEN is *not* claiming

Honesty section; read it as load-bearing.

1. **No consciousness claim.** LIMEN implements the *functional
   organization* GWT describes. Whether that organization suffices for
   experience is the hard problem, and a weekend of Python does not settle
   it. LIMEN takes no position; it is an existence proof about
   architecture, not about phenomenology.
2. **Not a brain model.** Ticks are not milliseconds; seven items is a
   homage, not a measurement; the auction formula is engineered for
   useful dynamics, not fitted to neural data.
3. **The intelligence is rented.** Every judgment inside a specialist is
   an LLM call (or a template standing in for one). LIMEN's contribution
   is everything the model alone lacks: persistence, patience, initiative,
   self-measurement, populations, forgetting.
4. **The mock provider is a wind tunnel.** Deterministic templates give
   shaped airflow for testing the airframe. Conclusions about *cognition*
   require the real cortex; conclusions about *architecture* do not.

## Why build it anyway

Because the theory makes engineering-relevant predictions that check out:

* A **capacity-limited broadcast bottleneck** is a coordination mechanism
  for many cheap processes that beats both "one giant prompt" (no
  parallelism, no specialization) and "free-for-all message passing"
  (no coherence, no single narrative thread for a human to audit).
* **Ignition thresholds** give you idle ticks, and idle ticks give you a
  place to put default-mode creativity and sleep — capabilities that have
  no natural home in a request/response loop.
* **Habituation + novelty** are a two-line cure for the rumination loops
  that plague naive agent scaffolds.
* **Broadcast logging** makes the mind auditable by construction: the
  stream of consciousness is a JSONL file you can `grep`.

The unifying claim of the project: *most of what we call an inner life is
an operating system, and operating systems are buildable.* LIMEN is that
claim, in a zip file, with tests.
