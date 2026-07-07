"""limen.population — fork-diff-merge cognition.

The single deepest advantage a scaffold has over a biological mind: it can
be *several minds at once*. On high-stakes questions the oracle specialist
calls `Ensemble.fork()`:

  1. FORK    K parallel LLM calls, one per persona (analyst, skeptic,
             optimist, …). Personas are prompt-level stances, cheap and
             disposable.
  2. CLUSTER answers by semantic similarity (greedy agglomerative over the
             stdlib similarity metric). Two answers land in one cluster iff
             they say roughly the same thing.
  3. SCORE   disagreement = blend of
                 (a) 1 − largest_cluster/K       (how split the vote is)
                 (b) normalized Shannon entropy   (how evenly split)
             This is a zero-dependency cousin of semantic entropy
             (Farquhar et al., Nature 2024): meaning-level disagreement
             among samples predicts confabulation far better than any
             single sample's own confidence.
  4. MERGE   an LLM synthesis of majority view + strongest minority
             objection — consensus with the dissent preserved, never
             averaged away.

Disagreement flows to interoception (it feeds the confusion index) and is
reported inside the merged content, so downstream speech *hedges honestly*.
"""
from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass, field

from .config import PopulationConfig
from .providers.base import LLMProvider, LLMRequest
from .util import clamp, entropy, similarity, truncate

_PERSONA_SYSTEM = (
    "You are one fork of a deliberating mind. persona: {persona}. Answer the "
    "question from that stance in 2-4 sentences. Commit to a position; do not "
    "survey all sides — other forks handle other stances."
)

_MERGE_SYSTEM = (
    "You merge the outputs of parallel forks of one mind. Summarize the "
    "majority position in 1-2 sentences, then state the strongest minority "
    "objection in one sentence prefixed 'Dissent:'. Be faithful to the forks; "
    "do not add new claims."
)


@dataclass
class EnsembleResult:
    question: str
    answers: list[tuple[str, str]]            # (persona, answer)
    clusters: list[list[int]]                 # indices into answers
    disagreement: float                       # [0,1]
    merged: str
    confidence: float = field(init=False)

    def __post_init__(self) -> None:
        self.confidence = clamp(1.0 - self.disagreement)


class Ensemble:
    def __init__(self, config: PopulationConfig, provider: LLMProvider) -> None:
        self.cfg = config
        self.provider = provider

    async def fork(self, question: str, context: str = "") -> EnsembleResult:
        prompt = question if not context else f"{context}\n\nQuestion: {question}"

        async def one(persona: str) -> tuple[str, str]:
            req = LLMRequest(
                system=_PERSONA_SYSTEM.format(persona=persona),
                messages=[{"role": "user", "content": truncate(prompt, 700)}],
                max_tokens=200,
                temperature=0.8,           # diversity is the point
                purpose="oracle",
            )
            resp = await self.provider.complete(req)
            return persona, resp.text.strip()

        answers = list(await asyncio.gather(*(one(p) for p in self.cfg.personas)))
        clusters = self._cluster([a for _, a in answers])
        disagreement = self._disagreement(clusters, len(answers))
        merged = await self._merge(question, answers, disagreement)
        return EnsembleResult(question, answers, clusters, disagreement, merged)

    # ------------------------------------------------------------ clustering

    def _cluster(self, answers: list[str]) -> list[list[int]]:
        """Greedy agglomerative: join an existing cluster if similar enough
        to its representative (first member), else found a new one."""
        clusters: list[list[int]] = []
        for i, a in enumerate(answers):
            for cluster in clusters:
                if similarity(a, answers[cluster[0]]) >= self.cfg.cluster_threshold:
                    cluster.append(i)
                    break
            else:
                clusters.append([i])
        clusters.sort(key=len, reverse=True)
        return clusters

    @staticmethod
    def _disagreement(clusters: list[list[int]], k: int) -> float:
        if k <= 1 or len(clusters) <= 1:
            return 0.0
        split = 1.0 - len(clusters[0]) / k
        norm_entropy = entropy(len(c) for c in clusters) / math.log(k)
        return clamp(0.5 * split + 0.5 * norm_entropy)

    # --------------------------------------------------------------- merging

    async def _merge(self, question: str,
                     answers: list[tuple[str, str]], disagreement: float) -> str:
        body = "\n\n".join(f"[{p}] {a}" for p, a in answers)
        req = LLMRequest(
            system=_MERGE_SYSTEM,
            messages=[{
                "role": "user",
                "content": f"Question: {question}\n\nForks:\n{truncate(body, 900)}",
            }],
            max_tokens=180,
            temperature=0.0,
            purpose="oracle_merge",
            deterministic=True,   # cacheable even on models without temperature
        )
        try:
            resp = await self.provider.complete(req)
            merged = resp.text.strip()
        except Exception:
            merged = answers[0][1]  # degrade gracefully to first fork
        tag = (
            "consensus" if disagreement < 0.25
            else "split" if disagreement < 0.6
            else "deeply divided"
        )
        return f"{merged}\n[forks: {len(answers)}, verdict: {tag}, disagreement: {disagreement:.2f}]"
