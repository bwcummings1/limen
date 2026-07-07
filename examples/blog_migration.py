"""The demo scenario, driven through the Python API instead of the CLI.

Run from the repo root:  python examples/blog_migration.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root,
# so the example runs on a fresh clone without `pip install`.

from limen import Config, Mind

cfg = Config()
cfg.mind.data_dir = "limen-example"
cfg.provider.kind = "mock"          # set "anthropic" + ANTHROPIC_API_KEY for a real cortex

mind = Mind.from_config(cfg)

# Tick 1: a question with an embedded reminder request.
mind.stimulate(
    "I'm planning to migrate our blog from WordPress to a static site "
    "generator. Is that a good idea? Also, remind me in a bit to email "
    "Dana about the DNS cutover."
)
replies, _ = mind.run_until_response(max_ticks=6)
print("MIND:", replies[0], "\n")

# Let time pass; the scheduled reminder fires on its own.
for r in mind.run_ticks(5):
    for u in r.utterances:
        print("MIND:", u, "\n")

# The user reverses their decision → contradiction machinery engages.
mind.stimulate("Actually, we've decided to stay on WordPress rather than migrate.")
replies, _ = mind.run_until_response(max_ticks=4)
print("MIND:", replies[0], "\n")

# Sleep on it, then inspect what the mind now believes.
mind.run_ticks(12)
tick = mind.clock.tick
print("--- beliefs ---")
for b in mind.ledger.active(tick):
    print(f"[{b.effective_confidence(tick):.2f}] {b.claim}")
for b in mind.ledger.beliefs.values():
    if b.status != "active":
        print(f"[{b.status}] {b.claim}")
print("\n--- vitals ---")
for k, v in mind.metrics.snapshot().items():
    print(f"{k}: {v}")
