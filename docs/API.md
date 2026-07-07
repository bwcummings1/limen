# LIMEN Python API

Import surface: `from limen import Mind, Config, TickResult, Percept,
Proposal, Broadcast, Specialist`. Everything else is reachable as
attributes of a `Mind`.

## Mind (`limen/mind.py`)

```python
Mind.from_config(cfg | "path.toml" | None) -> Mind   # None ⇒ defaults + ./limen.toml if present
mind.stimulate(content, source="user", salience=0.9, tags=None)  # queue a percept for next tick
mind.tick() -> TickResult                            # one cycle (sync; wraps asyncio.run)
await mind.tick_async() -> TickResult                # same, for your own event loop
mind.run_ticks(n) -> list[TickResult]
mind.run_until_response(max_ticks=10) -> (list[str], list[TickResult])
mind.status() -> dict                                # counts + metrics snapshot
```

Attributes you'll actually use: `mind.clock.tick`, `mind.config`,
`mind.goals` (GoalStack), `mind.ledger`, `mind.episodic`, `mind.skills`,
`mind.timekeeper`, `mind.workspace`, `mind.metrics`, `mind.provider`,
`mind.specialists` (a plain list — append your own), `mind.sensors`
(likewise), `mind.tools` (Toolbelt), `mind.ensemble`.

```python
mind.add_sensor(sensor)   # register a sensory channel (polled next tick on)
```

Threading model: a Mind is single-threaded by design; call it from one
place. Concurrency lives *inside* a tick (specialist fan-out).

## TickResult (`limen/cycle.py`)

`tick:int · ignited:bool · top_priority:float · threshold:float ·
winners:list[{author,kind,priority,content}] · utterances:list[str] ·
sleep_report:dict|None · proposal_count:int`

## Config (`limen/config.py`)

`Config()` → all defaults; `Config.load(path)` → overlay TOML (strict);
mutate sub-dataclass fields freely before `Mind.from_config(cfg)`:
`cfg.attention.ignition_threshold = 0.3`. `cfg.validate()` re-checks
invariants after manual edits.

## Memory

```python
mind.ledger.assert_claim(claim, confidence, tick, provenance, tags=None,
                         half_life=None) -> (Belief, "created"|"reinforced"|"contradiction")
mind.ledger.retrieve(query, tick, n=4, floor=0.30) -> [(Belief, score)]
mind.ledger.active(tick) -> [Belief]                 # sorted by effective confidence
mind.ledger.decay_and_prune(tick, floor) -> [pruned ids]
belief.effective_confidence(tick) -> float

mind.episodic.log(kind, tick, payload) -> event      # prefer Toolbelt in specialists
mind.episodic.recent(n=20, kind=None) / .since_tick(t) / .search(query, n=5)

mind.skills.write(title, body, tick, source) -> Path
mind.skills.relevant(context, n=2) -> [{slug,title,body,score}]
```

## Timekeeper

```python
mind.timekeeper.schedule(message, due_tick, tick, every=None) -> Intention
mind.timekeeper.arm_deadman(message, watch_tag, within, tick) -> Intention
mind.timekeeper.disarm(watch_tag) -> int
```
(Inside specialists, use `tools.schedule(message, in_ticks, every=None)` /
`tools.arm_deadman(...)` so the calls are logged.)

## Toolbelt (act-phase surface)

`respond(text)` · `write_note(name, text)` (sandboxed to `data_dir/notes/`)
· `schedule(message, in_ticks, every=None)` · `arm_deadman(message,
watch_tag, within)` · `add_goal(text)` · `complete_goal(goal_id)` ·
`remember(claim, confidence, tags=None, half_life=None)`. Every call is
episodic-logged.

## Providers

```python
from limen.providers import LLMRequest, build_provider
resp = await mind.provider.complete(LLMRequest(system=..., messages=[...],
        max_tokens=300, temperature=0.2, purpose="mytool",
        deterministic=False))   # deterministic=True ⇒ disk-cache eligible
resp.text · resp.input_tokens · resp.output_tokens · resp.cached · resp.stop_reason
mind.provider.budget.fraction_remaining() · mind.provider.stats
mind.provider.model_for("mytool")   # per-purpose routing ([provider.models])
```
The request's `purpose` label doubles as the routing key: `[provider.models]`
maps purposes to model ids, falling back to `provider.model`. Inside a
Specialist, prefer `self.ask(system, user, ...) -> str|None`, which routes
failures (including `refusal` stops) to interoception and notes
`max_tokens` truncation.

## Sensors

```python
from limen.sensors import Sensor, FileWatcher, RSSWatcher
class Heartbeat(Sensor):
    name = "heartbeat"
    def poll(self, tick):            # sync; runs on a thread, watchdogged
        return [Percept(source="sensor:heartbeat", content="...",
                        salience_hint=0.6, tags=["ops"])]
mind.add_sensor(Heartbeat())
```
Built-ins are configured via `[sensors]` (see docs/CONFIGURATION.md) or
constructed directly: `FileWatcher(path, state_dir, salience=0.55)`,
`RSSWatcher(url, state_dir, every_ticks=12)`. Digest your news — one
percept per batch; the auction is metered attention, not a message queue.

## Embeddings

```python
from limen.util import set_similarity_backend, heuristic_similarity
from limen.embeddings import build_similarity, SemanticSimilarity
set_similarity_backend(build_similarity(cfg, data_dir))  # Mind does this
set_similarity_backend(None)                             # back to heuristic
```
The backend is process-global (one mind per process is the intended
shape); it upgrades every `util.similarity` call site at once. Configure
via `[embeddings]` rather than calling these directly.

## Population

```python
result = await mind.ensemble.fork("Should we…?", context="…")
result.answers · result.clusters · result.disagreement · result.confidence · result.merged
```

## Writing a specialist

See docs/SPECIALISTS.md §3 and `examples/add_a_specialist.py` — subclass
`Specialist`, implement `perceive`/`act`, then either
`mind.specialists.append(You(mind))` or register in
`limen.specialists.REGISTRY` + `[specialists].enabled`.
