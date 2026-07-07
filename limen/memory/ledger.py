"""limen.memory.ledger — semantic memory as an auditable belief ledger.

Every long-term claim the mind holds is a Belief with:

  claim        the proposition, plain text
  confidence   in (0,1]; decays exponentially with a per-belief half-life
  half_life    ticks for confidence to halve (volatile facts decay fast,
               stable facts slowly)
  provenance   list of {kind, ref, tick} records — *why* the mind believes it
  status       active | deprecated | contradicted

Three invariants:

  1. Nothing is believed without provenance.
  2. Confidence is never stored fresh — reads apply decay lazily
     (`effective_confidence`), sleeps persist the decayed value.
  3. Contradictions are never silently overwritten: they are detected,
     logged, and reconciled by an explicit rule (higher effective confidence
     wins; loser is marked `contradicted`, cross-linked, and kept).

Reinforcement uses noisy-OR:  c' = 1 - (1-c)(1-c_new*kappa)  — repeated
independent evidence pushes confidence up asymptotically, never past 1.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from ..config import LedgerConfig
from ..util import clamp, keywords, new_id, similarity

_NEGATION = re.compile(
    r"\b(not|no longer|never|isn't|aren't|won't|don't|doesn't|cancel(?:led)?|"
    r"stopped|reversed|instead of|rather than|decided against|stay(?:ing)? on)\b"
)


@dataclass
class Belief:
    claim: str
    confidence: float
    created_tick: int
    updated_tick: int
    half_life: int
    provenance: list[dict[str, Any]] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    status: str = "active"                # active | deprecated | contradicted
    contradicts: list[str] = field(default_factory=list)
    id: str = field(default_factory=lambda: new_id("blf"))

    def effective_confidence(self, now_tick: int) -> float:
        dt = max(0, now_tick - self.updated_tick)
        return self.confidence * (0.5 ** (dt / max(self.half_life, 1)))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BeliefLedger:
    def __init__(self, directory: Path, config: LedgerConfig) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "beliefs.json"
        self.cfg = config
        self.beliefs: dict[str, Belief] = {}
        self._load()

    # ------------------------------------------------------------ persistence

    def _load(self) -> None:
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for entry in data:
                b = Belief(**entry)
                self.beliefs[b.id] = b

    def save(self) -> None:
        payload = [b.to_dict() for b in self.beliefs.values()]
        self.path.write_text(
            json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8"
        )

    # ------------------------------------------------------------------ write

    def assert_claim(
        self,
        claim: str,
        confidence: float,
        tick: int,
        provenance: dict[str, Any],
        tags: list[str] | None = None,
        half_life: int | None = None,
    ) -> tuple[Belief, str]:
        """Insert / reinforce / contradict. Returns (belief, action) where
        action in {"created", "reinforced", "contradiction"}.
        """
        confidence = clamp(confidence, 0.01, 1.0)
        match, sim = self._closest_active(claim)

        # Reinforce: same claim restated -> noisy-OR confidence bump.
        if match and sim >= self.cfg.merge_threshold and not self._opposed(claim, match.claim):
            eff = match.effective_confidence(tick)
            match.confidence = clamp(
                1.0 - (1.0 - eff) * (1.0 - confidence * self.cfg.reinforce_kappa),
                0.01, 1.0,
            )
            match.updated_tick = tick
            match.provenance.append({**provenance, "tick": tick})
            if tags:
                match.tags = sorted(set(match.tags) | set(tags))
            self.save()
            return match, "reinforced"

        belief = Belief(
            claim=claim,
            confidence=confidence,
            created_tick=tick,
            updated_tick=tick,
            half_life=half_life or self.cfg.default_half_life,
            provenance=[{**provenance, "tick": tick}],
            tags=tags or [],
        )
        self.beliefs[belief.id] = belief

        # Contradiction: scan ALL active beliefs for an opposed-polarity
        # rival on the same topic (the closest-by-similarity belief is not
        # necessarily the contradicting one).
        rival, topical = self._most_opposed(claim, exclude=belief.id)
        if rival is not None and topical >= self.cfg.contradiction_threshold:
            self._reconcile(belief, rival, tick)
            self.save()
            return belief, "contradiction"

        self.save()
        return belief, "created"

    def _reconcile(self, new: Belief, old: Belief, tick: int) -> None:
        """Newer evidence wins ties; otherwise higher effective confidence wins."""
        new.contradicts.append(old.id)
        old.contradicts.append(new.id)
        if new.effective_confidence(tick) >= old.effective_confidence(tick):
            old.status = "contradicted"
        else:
            new.status = "contradicted"

    # ------------------------------------------------------------------- read

    def _closest_active(self, claim: str) -> tuple[Belief | None, float]:
        best, best_sim = None, 0.0
        for b in self.beliefs.values():
            if b.status != "active":
                continue
            s = similarity(claim, b.claim)
            if s > best_sim:
                best, best_sim = b, s
        return best, best_sim

    def _opposed(self, a: str, b: str) -> bool:
        """Heuristic polarity opposition: shared topic (>= 2 content words),
        exactly one side carrying a negation/reversal marker. Deliberately
        conservative; the always-on floor beneath any LLM-side judgement.
        """
        na, nb = bool(_NEGATION.search(a.lower())), bool(_NEGATION.search(b.lower()))
        if na == nb:
            return False
        shared = set(keywords(a, 16)) & set(keywords(b, 16))
        return len(shared) >= 2

    def _most_opposed(self, claim: str, exclude: str) -> tuple[Belief | None, float]:
        """The active belief most topically entangled with `claim` among
        those with opposed polarity. Topicality = max(similarity, keyword
        overlap coefficient) — overlap coefficient catches short reversals
        ('we decided to stay') of long originals that plain similarity
        under-scores."""
        best, best_t = None, 0.0
        kc = set(keywords(claim, 16))
        for b in self.beliefs.values():
            if b.status != "active" or b.id == exclude:
                continue
            if not self._opposed(claim, b.claim):
                continue
            kb = set(keywords(b.claim, 16))
            overlap = (
                len(kc & kb) / min(len(kc), len(kb)) if kc and kb else 0.0
            )
            t = max(similarity(claim, b.claim), overlap)
            if t > best_t:
                best, best_t = b, t
        return best, best_t

    def retrieve(self, query: str, tick: int, n: int = 4, floor: float = 0.30
                 ) -> list[tuple[Belief, float]]:
        """Active beliefs relevant to `query`, ranked by similarity × decay."""
        scored = []
        for b in self.beliefs.values():
            if b.status != "active":
                continue
            s = similarity(query, b.claim)
            if s >= floor:
                scored.append((b, s * b.effective_confidence(tick)))
        scored.sort(key=lambda p: p[1], reverse=True)
        return scored[:n]

    def active(self, tick: int) -> list[Belief]:
        return sorted(
            (b for b in self.beliefs.values() if b.status == "active"),
            key=lambda b: b.effective_confidence(tick),
            reverse=True,
        )

    # ---------------------------------------------------------- maintenance

    def decay_and_prune(self, tick: int, floor: float) -> list[str]:
        """Sleep-time pass: persist decayed confidences, prune the forgotten."""
        pruned: list[str] = []
        for b in list(self.beliefs.values()):
            b.confidence = b.effective_confidence(tick)
            b.updated_tick = tick
            if b.status == "active" and b.confidence < floor:
                b.status = "deprecated"
                pruned.append(b.id)
        self.save()
        return pruned
