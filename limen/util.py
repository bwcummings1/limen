"""limen.util — small, dependency-free primitives shared by every subsystem.

Design rule: LIMEN is 100% Python stdlib. Anything that looks like it needs
numpy or an embedding model gets a principled cheap approximation here
(token estimation, text similarity, entropy) so the whole mind runs anywhere.
"""
from __future__ import annotations

import difflib
import hashlib
import math
import random
import re
import string
import threading
import time
from typing import Iterable

# ---------------------------------------------------------------- identifiers

_ALPHABET = string.ascii_lowercase + string.digits
_id_lock = threading.Lock()
_id_counter = 0


def new_id(prefix: str, rng: random.Random | None = None) -> str:
    """Short, sortable-enough unique id: '<prefix>_<counter><4 random chars>'."""
    global _id_counter
    r = rng or random
    with _id_lock:
        _id_counter += 1
        n = _id_counter
    suffix = "".join(r.choice(_ALPHABET) for _ in range(4))
    return f"{prefix}_{n:05d}{suffix}"


def stable_hash(text: str, length: int = 10) -> str:
    """Deterministic content hash used for cache keys and habituation topics."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


# ------------------------------------------------------------------- language

_WORD_RE = re.compile(r"[a-z0-9']+")
_STOPWORDS = frozenset(
    "a an and are as at be but by for from has have i if in into is it its of on "
    "or our so that the their there they this to was we what when which who will "
    "with you your also than i'm i've it's that's we've we're don't can't "
    "won't isn't let's there's what's you're they're he's she's".split()
)


def estimate_tokens(text: str) -> int:
    """Cheap token estimate (~4 chars/token, floor of word count).

    Used for workspace capacity accounting and budget metering. Real usage
    numbers from the Anthropic API override this when available.
    """
    if not text:
        return 0
    return max(len(text) // 4, len(text.split()))


def keywords(text: str, limit: int = 12) -> list[str]:
    """Lowercased content words, stopwords removed, order-preserving unique."""
    seen: list[str] = []
    for w in _WORD_RE.findall(text.lower()):
        if w in _STOPWORDS or len(w) < 3 or w in seen:
            continue
        seen.append(w)
        if len(seen) >= limit:
            break
    return seen


def heuristic_similarity(a: str, b: str) -> float:
    """Blend of sequence similarity and keyword Jaccard, in [0, 1].

    difflib catches near-verbatim overlap; Jaccard catches paraphrase-level
    topical overlap. The max of the two is a serviceable stand-in for
    embedding cosine similarity at zero dependencies. This is the always-on
    default; see `set_similarity_backend` for the embedding upgrade path.
    """
    if not a or not b:
        return 0.0
    seq = difflib.SequenceMatcher(None, a.lower()[:600], b.lower()[:600]).ratio()
    ka, kb = set(keywords(a, 24)), set(keywords(b, 24))
    jac = len(ka & kb) / len(ka | kb) if (ka or kb) else 0.0
    return max(seq, jac)


# The similarity seam. Six cognitive functions (attention novelty, workspace
# dedup, belief merging, contradiction topicality, ensemble clustering,
# retrieval) call `similarity`; an embedding backend upgrades all of them at
# once. The backend is process-global by design: similarity is used as a free
# function throughout, and one process hosts one mind (twin tests share a
# config, so they share a backend). Mind sets it at construction from
# [embeddings]; `None` restores the heuristic.
_similarity_backend = None


def set_similarity_backend(fn) -> None:
    """Install `fn(a, b) -> float in [0,1]` as the similarity metric
    (None ⇒ the stdlib heuristic). Called by Mind from [embeddings] config."""
    global _similarity_backend
    _similarity_backend = fn


def similarity(a: str, b: str) -> float:
    """Semantic similarity in [0, 1] — heuristic by default, embedding-backed
    when a backend is installed (see limen/embeddings.py)."""
    if _similarity_backend is not None:
        return _similarity_backend(a, b)
    return heuristic_similarity(a, b)


def entropy(counts: Iterable[int]) -> float:
    """Shannon entropy (nats) of a count distribution; 0.0 for degenerate."""
    counts = [c for c in counts if c > 0]
    total = sum(counts)
    if total == 0 or len(counts) < 2:
        return 0.0
    return -sum((c / total) * math.log(c / total) for c in counts)


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def truncate(text: str, tokens: int) -> str:
    """Truncate text to at most `tokens` estimated tokens, on a word boundary.
    Guaranteed: estimate_tokens(result) <= tokens (for tokens >= 2)."""
    if estimate_tokens(text) <= tokens:
        return text
    cut = text[: max(tokens, 2) * 4]
    while estimate_tokens(cut + " …") > tokens and len(cut) > 4:
        cut = cut[: int(len(cut) * 0.8)]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut + " …"


# ---------------------------------------------------------------------- clock

class Clock:
    """Discrete cognitive time. One tick == one cognitive cycle.

    LIMEN reasons in ticks, not wall time; the daemon maps ticks onto wall
    time, and tests run ticks as fast as the CPU allows. `wall()` is provided
    for logging only — no core algorithm may branch on wall time.
    """

    def __init__(self, start: int = 0) -> None:
        self._tick = start

    @property
    def tick(self) -> int:
        return self._tick

    def advance(self) -> int:
        self._tick += 1
        return self._tick

    @staticmethod
    def wall() -> float:
        return time.time()


def make_rng(seed: int | None) -> random.Random:
    """Seeded RNG for full run determinism (mock provider, id suffixes)."""
    return random.Random(seed if seed is not None else time.time_ns())
