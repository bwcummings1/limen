"""Writing your own specialist in ~20 lines: a 'gratitude' processor that
notices thanks from the user and bids a warm acknowledgment. Demonstrates
the full contract: perceive() bids, act() uses tools, workspace-only comms.

Run from the repo root:  python examples/add_a_specialist.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root,
# so the example runs on a fresh clone without `pip install`.

from limen import Config, Mind
from limen.specialists.base import MindView, Specialist


class Gratitude(Specialist):
    name = "gratitude"

    async def perceive(self, view: MindView):
        for pct in view.fresh_percepts:
            if pct.source == "user" and "thank" in pct.content.lower():
                return [self.propose(
                    content="The user expressed thanks; acknowledge warmly.",
                    salience=0.6, kind="social",
                )]
        return []

    async def act(self, broadcasts, view, tools):
        for b in broadcasts:
            if b.author == self.name and b.kind == "social":
                tools.respond("You're very welcome — glad it helped.")


cfg = Config()
cfg.mind.data_dir = "limen-example-custom"
cfg.provider.kind = "mock"
mind = Mind.from_config(cfg)
mind.specialists.append(Gratitude(mind))     # or subclass + REGISTRY

mind.stimulate("thank you, that was useful!")
replies, _ = mind.run_until_response()
for u in replies:
    print("MIND:", u)
