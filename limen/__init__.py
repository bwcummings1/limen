"""LIMEN — a Global Workspace Theory runtime for LLM agents.

    limen (n., psychophysics): the threshold below which a stimulus is not
    perceived. Content below it is, literally, sub-liminal.

LIMEN implements Bernard Baars' Global Workspace Theory as running glue
code: many cheap specialist processes bid for a single small "conscious"
workspace; winners are broadcast to everyone; a clock, four memory systems,
interoceptive self-monitoring, and fork-diff-merge deliberation complete
the loop. An inner life assembled from cron jobs and JSON files.

Quickstart:
    from limen import Mind, Config
    mind = Mind.from_config()                 # defaults + optional limen.toml
    mind.stimulate("Should we rewrite the billing service in Rust?")
    replies, _ = mind.run_until_response()
    print(replies[0])
"""
from .bus import Broadcast, Percept, Proposal
from .config import Config
from .cycle import TickResult
from .mind import Mind
from .specialists import Specialist

__version__ = "1.0.0"
__all__ = [
    "Mind", "Config", "TickResult",
    "Percept", "Proposal", "Broadcast", "Specialist",
    "__version__",
]
