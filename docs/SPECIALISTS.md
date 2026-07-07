# LIMEN Specialists

Specialists are the unconscious audience: small processors that watch the
conscious contents and bid for the stage. This document is the complete
contract plus a reference for every built-in.

## 1. The contract (`specialists/base.py`)

```python
class Specialist:
    name = "yourname"

    async def perceive(self, view: MindView) -> list[Proposal]: ...
    async def act(self, broadcasts: list[Broadcast],
                  view: MindView, tools: Toolbelt) -> None: ...
```

**`perceive(view)` — the bid phase.** Runs every tick, concurrently with
every other specialist, on an identical immutable view. Return zero or
more Proposals. This is where LLM calls belong (via the guarded
`self.ask(system, user, ...)` helper, which converts budget/network
failures into interoceptive notes and returns `None`), because the output
must then *compete for consciousness* like everything else.

**`act(broadcasts, view, tools)` — the action phase.** Runs only on
ignition ticks, after the workspace has been updated. `broadcasts` is the
list of *newly admitted* contents. React with effector calls through the
Toolbelt only. Keep it cheap; no LLM calls here by convention.

**`MindView` fields:** `tick`, `conscious` (the rendered workspace — your
entire window onto the rest of the mind), `fresh_percepts` (arrived this
tick, pre-conscious), `goals_text`, `metrics` (interoception snapshot
dict), `workspace` (for read-only structural queries:
`kinds_present()`, `by_kind(k)`, `contents`), and — act phase only —
`new_broadcasts`.

**The iron rule.** Specialists never call each other, never share state,
never pass messages. The workspace is the only channel. If your specialist
needs another's output, it waits for that output to become conscious. This
bottleneck is the theory; violating it produces a multi-agent system, not
a global workspace.

**Reads vs writes.** Reading the mind at perceive time is allowed and
encouraged (`self.mind.ledger.retrieve(...)`, `self.mind.episodic.recent(...)`,
`self.mind.skills.relevant(...)`). Every *write* goes through the Toolbelt
so it is episodic-logged.

**Failure containment.** Exceptions and timeouts in either method are
caught by the cycle, logged to interoception, and cost you only that
tick's participation. Design idempotently anyway — but prefer **cooldowns
over permanent latches** for perceive-phase triggers: with a real
(fallible, nondeterministic) provider, a generated bid can fail or lose
the auction, and a write-once "handled" set silences the specialist
forever. The built-ins' pattern: a bid that WON is blocked by workspace
`kinds_present()` checks; a lost bid may retry next tick (bounded by the
target's TTL); only provider failures cool down (3 ticks), so a broken
API isn't hammered. Act-phase effectors (Scribe, Perception's scheduler)
still use plain handled-id sets — acting twice is worse than acting late.

## 2. The built-ins

| name | perceive (bids) | act (effectors) | LLM? |
|---|---|---|---|
| **perception** | classifies each fresh percept → `question`/`statement`/`reminder`/`alarm` at the channel's salience hint; extracts "remind me … to X" → a `reminder_request` bid in the same coalition | schedules the reminder once its request is conscious (the mind never commits to a future it wasn't aware of) | no |
| **goals** | nags about goals open ≥10 ticks (`goal_stale`, 0.45) | on a conscious `question`, adds a "Respond to the user about: …" goal | no |
| **planner** | when a `question` is conscious with no `plan`: drafts a numbered PLAN (salience 0.65, question's coalition); lost bids may retry, failures cool down 3 ticks | — | yes |
| **critic** | when a `plan`/`verdict` is conscious and uncriticized: bids the strongest objection (`risk`, 0.55); same retry/cooldown pattern | — | yes |
| **librarian** | retrieves ≤2 relevant beliefs (salience `0.35+0.5·score`, capped 0.8) and ≤1 skill against the current workspace | — | no |
| **introspector** | converts pending interoception alarms into `alarm` bids (0.7 confusion / 0.8 budget) | — | no |
| **oracle** | on a conscious `question` ≥ `min_salience` with no verdict: runs the fork-diff-merge ensemble, records disagreement, bids the merged `verdict` (`0.6+0.15·confidence`); one *successful* ensemble per question ever, failed forks retry after a 3-tick cooldown | — | yes (K+1 calls) |
| **scribe** | — | writes conscious verdicts (`confidence = max(0.2, 0.9·ensemble_conf)`), user decisions (`0.9`), and stated intentions from questions (`0.8`) into the ledger via `tools.remember` | no |
| **speaker** | with an active goal and a conscious `verdict`/`plan` and no pending draft: drafts a reply — seeing the timekeeper's live intentions, so promised follow-ups are real, not hallucinated — and bids it as `utterance_draft` (0.7); a lost draft is redrafted while an answer is still conscious, failures cool down 3 ticks | delivers its own conscious draft via `tools.respond` + completes the goal; relays `reminder`/`alarm` from future_self with a ⏰ prefix; acks recorded decisions | yes (draft) |
| **wanderer** | on idle streaks ≥2: bids a random belief↔episode association (`daydream`, salience uniform 0.12–0.28 — usually sub-liminal by design) | — | no |

Enable/disable any subset via `[specialists].enabled` in `limen.toml`. A
mind with only `perception` and `speaker` is a chatbot; the rest is the
inner life.

## 3. Writing your own

Complete working example (also in `examples/add_a_specialist.py`):

```python
from limen import Config, Mind
from limen.specialists.base import MindView, Specialist

class Gratitude(Specialist):
    name = "gratitude"

    async def perceive(self, view: MindView):
        for pct in view.fresh_percepts:
            if pct.source == "user" and "thank" in pct.content.lower():
                return [self.propose(
                    content="The user expressed thanks; acknowledge warmly.",
                    salience=0.6, kind="social")]
        return []

    async def act(self, broadcasts, view, tools):
        for b in broadcasts:
            if b.author == self.name and b.kind == "social":
                tools.respond("You're very welcome — glad it helped.")

mind = Mind.from_config()
mind.specialists.append(Gratitude(mind))       # ad-hoc registration
```

For config-driven registration, add your class to
`limen.specialists.REGISTRY` and list its name in `[specialists].enabled`.

### Design guidance

* **Bid honestly.** Salience is your urgency estimate, not a volume knob.
  The auction's novelty/habituation terms will punish shouting; a
  specialist that always bids 0.95 ends up structurally ignored.
* **Trigger narrowly.** Gate LLM calls on workspace conditions
  (`view.workspace.kinds_present()`), and remember what you've already
  handled. Cost discipline is architectural in LIMEN, not aspirational.
* **Use `kind` for routing, `meta` for payloads.** Downstream specialists
  key off `kind`; structured data rides in `meta` and never pollutes the
  rendered workspace.
* **Join coalitions when your bid is evidence for someone else's.** Same
  `coalition` string ⇒ pooled priority.
* **Two-stage anything irreversible.** Follow the Speaker's pattern: bid
  the intention into consciousness first; execute only when it wins. The
  tick between the two is where the Critic lives.
