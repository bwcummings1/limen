# LIMEN Configuration Reference

All tunables live in `limen.toml` (strict: unknown sections or keys raise at
load, because a typo that silently no-ops is how minds get subtle brain
damage). Delete any section to accept defaults. Load order: code defaults →
`--config` path or `./limen.toml` if present.

## [mind]
| key | default | notes |
|---|---|---|
| `name` | `"limen-01"` | cosmetic identifier in traces |
| `data_dir` | `".limen"` | root of all persistent state (memories, cache, notes). One directory per mind; two minds sharing one is undefined behavior |
| `seed` | `7` | seeds RNG + mock provider ⇒ fully deterministic runs. Comment out for entropy |

## [workspace]
| key | default | notes |
|---|---|---|
| `capacity_tokens` | `800` | size of consciousness (estimated tokens). Smaller ⇒ more abstraction pressure, more serial thought; larger ⇒ more parallel context, higher prompt costs |
| `max_items` | `7` | simultaneous conscious contents (Miller's 7±2, as homage) |
| `item_ttl` | `3` | ticks a broadcast stays without being refreshed. Raise for stickier working memory |

## [attention]
| key | default | notes |
|---|---|---|
| `ignition_threshold` | `0.25` | **the limen.** Below it, ticks idle. Raise ⇒ a quieter, more contemplative mind (more idles, more sleep); lower ⇒ excitable |
| `novelty_floor` | `0.40` | α in `(α + (1−α)·novelty)`. At 1.0 novelty is ignored; at 0 repeats are annihilated |
| `habituation_strength` | `0.70` | β in `(1 − β·habituation)`. Max suppression of chronic winners ≈ β·0.95 |
| `goal_floor` | `0.50` | γ in `(γ + (1−γ)·goal_relevance)`. At 1.0 goals don't modulate attention |
| `habituation_gain` | `0.25` | added per auction win, per (author, topic) key, capped 0.95 |
| `habituation_decay` | `0.90` | per-tick multiplier; levels <0.01 are dropped |
| `coalition_bonus` | `0.15` | fraction of each ally's raw score added |
| `recent_window` | `6` | broadcasts compared for novelty |
| `max_item_fraction` | `0.50` | max share of capacity one item may take; oversized bids are truncated to fit |

## [budget]
| key | default | notes |
|---|---|---|
| `tokens_per_day` | `200000` | hard provider budget per budget-day (estimated pre-flight, reconciled with real usage) |
| `day_ticks` | `96` | ticks per budget-day (also the timescale sleep/decay defaults assume) |
| `hard_stop` | `true` | `true`: exhausted budget ⇒ `BudgetExceeded`, which specialists surface as interoceptive failures ⇒ budget alarm. `false`: log and continue |

## [provider]
| key | default | notes |
|---|---|---|
| `kind` | `"mock"` | `"mock"` (offline, deterministic) or `"anthropic"` (needs `ANTHROPIC_API_KEY` env var) |
| `model` | `"claude-opus-4-8"` | any Messages-API model id; the payload auto-adapts per generation (current-gen models drop `temperature`; Sonnet 5 gets `thinking` disabled explicitly) — change here, never in code |
| `models` | `{}` | per-purpose routing table (`[provider.models]`): maps a request's purpose label to a model id, falling back to `model`. Purposes in use: `planner`, `critic`, `speaker`, `oracle` (persona forks), `oracle_merge`, `consolidation`; a custom specialist's `ask()` defaults to its name. The response cache is keyed by the routed model. |
| `max_tokens` | `400` | default completion cap (specialists may request less) |
| `temperature` | `0.7` | default; ensemble forks use 0.8, distill/merge use 0.0. Ignored (not sent) on Opus 4.7+/Sonnet 5/Fable 5, where the API rejects sampling params |
| `cache` | `true` | disk-cache responses for requests flagged deterministic (or legacy temperature ≤ 0.1), content-addressed under `data_dir/cache/` |
| `timeout_secs` | `60.0` | per HTTP call |
| `max_retries` | `4` | exponential backoff + jitter on 408/409/429/5xx/529 |

## [embeddings]
Optional semantic-similarity backend. Similarity is load-bearing in six
places (attention novelty, workspace dedup, belief merging, contradiction
topicality, ensemble clustering, retrieval); an embedding backend upgrades
all of them at once through the seam in `util.set_similarity_backend`. The
combined score is `max(heuristic, calibrated cosine)` — a strict upgrade;
the ledger's negation/polarity test stays heuristic regardless (embeddings
are unreliable on negation). Vectors are embedded once, ever, and cached
under `data_dir/cache/embeddings/`.

| key | default | notes |
|---|---|---|
| `kind` | `"none"` | `"none"` (stdlib heuristic — mock/tests live here), `"voyage"` (Voyage AI API, needs `VOYAGE_API_KEY`), `"openai"` (**recommended for local** — any OpenAI-compatible `/v1/embeddings` server: LM Studio, llama.cpp's llama-server, vLLM, Ollama's `/v1` surface, or a hosted provider; the protocol is the standard, the tool is just a `base_url`), `"ollama"` (Ollama's native `/api/embed`, kept for compatibility) |
| `model` | `""` | `""` ⇒ per-kind default (`voyage-3.5-lite` / `nomic-embed-text`); for `openai`, `""` sends no model field (the server's loaded model answers) |
| `base_url` | `""` | **required for `openai`** (e.g. `http://localhost:1234/v1` LM Studio, `http://localhost:11434/v1` Ollama; `/v1` is appended if missing). For `ollama`: `""` ⇒ `http://localhost:11434`. `OPENAI_API_KEY` is sent as a bearer token if set — local servers don't need it |
| `calibration_floor` | `0.55` | cosine at/below this rescales to 0; model-specific — unrelated texts score well above 0 on real embedding models. Retune similarity thresholds (`ledger.merge_threshold`, `population.cluster_threshold`) per backend |
| `cache` | `true` | content-addressed vectors on disk |
| `timeout_secs` | `20.0` | per embedding HTTP call |

## [sensors]
Sensory channels polled in the SENSE phase (see docs/ARCHITECTURE.md §2
Phase 3). Channels set salience *hints*; the auction decides what matters.
Both built-ins digest (one percept per batch of news) and persist
seen-state under `data_dir/sensors/`, so a daemon restart doesn't
re-perceive the world. Programmatic sensors: `mind.add_sensor(...)`.

| key | default | notes |
|---|---|---|
| `watch_dirs` | `[]` | one FileWatcher per directory (non-recursive; first ever run baselines silently) |
| `watch_salience` | `0.55` | salience hint on file-change percepts |
| `rss_feeds` | `[]` | one RSSWatcher per RSS 2.0/Atom URL (`file://` URLs work) |
| `rss_every_ticks` | `12` | poll cadence per feed, in ticks |
| `rss_salience` | `0.45` | salience hint on feed-digest percepts |

## [sleep]
| key | default | notes |
|---|---|---|
| `every_ticks` | `24` | consolidation cadence |
| `idle_trigger` | `6` | consecutive idle ticks that also trigger sleep |
| `max_lessons` | `5` | distilled lines per sleep |
| `prune_floor` | `0.05` | actives decayed below this are deprecated |
| `replay_window` | `200` | max episodic events replayed |

## [ledger]
| key | default | notes |
|---|---|---|
| `default_half_life` | `480` | ticks for confidence to halve (5 budget-days) |
| `merge_threshold` | `0.72` | similarity above which a same-polarity claim reinforces instead of duplicating |
| `contradiction_threshold` | `0.30` | topicality floor (max of similarity and keyword-overlap coefficient) for opposed-polarity reconciliation; the ≥2-shared-keywords rule in `_opposed` is the real false-positive guard |
| `reinforce_kappa` | `0.6` | κ in the noisy-OR reinforcement |

## [population]
| key | default | notes |
|---|---|---|
| `personas` | `["analyst","skeptic","optimist"]` | fork stances; add `"pragmatist"` or your own — they're prompt-level, so free. K = list length |
| `cluster_threshold` | `0.62` | answers co-cluster above this similarity |
| `trigger_kinds` | `["question"]` | broadcast kinds eligible for ensembles |
| `min_salience` | `0.55` | only fork for stakes above this winning priority |

## [interoception]
| key | default | notes |
|---|---|---|
| `confusion_threshold` | `0.60` | confusion index that raises the alarm percept |
| `budget_alarm_fraction` | `0.20` | remaining-budget fraction that raises the alarm |
| `ewma_alpha` | `0.30` | smoothing for ignition-rate estimate |

## [specialists]
`enabled` — list of registry names to instantiate, in fan-out order.
Default: all ten. See docs/SPECIALISTS.md.

## [cycle]
| key | default | notes |
|---|---|---|
| `idle_sleep_secs` | `0.0` | reserved for embedders; the CLI daemon uses `--period` instead |
| `max_specialist_secs` | `90.0` | watchdog per specialist call and per sensor poll; timeouts become interoceptive failures |

## Tuning recipes
* **Cheaper mind:** drop `oracle` and `critic` from `enabled`, or raise `population.min_salience` to 0.8 and shrink `personas`.
* **More contemplative:** `ignition_threshold` 0.35, `item_ttl` 5, `sleep.every_ticks` 12.
* **Long-horizon assistant:** `default_half_life` 2000+, `day_ticks` matched to your daemon period so a "day" is a real day.
