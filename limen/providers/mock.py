"""limen.providers.mock — a deterministic stand-in cortex.

LIMEN must run end-to-end with no network and no API key: the architecture
is the point, and it has to be testable. MockProvider produces *plausible,
role-aware, seeded-deterministic* text by pattern-matching the request's
system prompt and last message against the small vocabulary of purposes the
specialists actually use (plan, critique, distill, answer-as-persona, ...).

It is not intelligent. It is a wind tunnel: shaped airflow for testing the
airframe. Swap in AnthropicProvider (provider.kind = "anthropic") and the
identical airframe flies with a real cortex.
"""
from __future__ import annotations

import asyncio
import hashlib
import random

from .base import LLMRequest, LLMResponse, MeteredProvider
from ..util import estimate_tokens, keywords

_PERSONA_STANCE = {
    "analyst": (
        "On balance, yes — proceed, but stage it. The main factors are "
        "{k0} and {k1}; measure both before and after."
    ),
    "skeptic": (
        "I would not proceed yet. The claim leans on {k0}, which is "
        "unverified, and the cost of being wrong about {k1} is asymmetric."
    ),
    "optimist": (
        "Yes — proceed. {k0} is the real opportunity here, and {k1} is a "
        "manageable risk with a rollback plan."
    ),
    "pragmatist": (
        "Proceed, but only the smallest reversible slice first; let {k0} "
        "prove itself before touching {k1}."
    ),
}


def _seed_for(request: LLMRequest, base_seed: int) -> int:
    blob = f"{base_seed}|{request.system[:200]}|{request.messages[-1]['content'][:400]}"
    return int(hashlib.sha256(blob.encode()).hexdigest()[:12], 16)


class MockProvider(MeteredProvider):
    """Deterministic template responder. Same seed + same request => same text."""

    def __init__(self, budget, cache, seed: int = 7, latency: float = 0.0) -> None:
        super().__init__(budget, cache)
        self.model = "mock-cortex-1"
        self.seed = seed
        self.latency = latency

    async def _raw_complete(self, request: LLMRequest) -> LLMResponse:
        if self.latency:
            await asyncio.sleep(self.latency)
        rng = random.Random(_seed_for(request, self.seed))
        text = self._respond(request, rng)
        return LLMResponse(
            text=text,
            input_tokens=request.estimated_input_tokens,
            output_tokens=estimate_tokens(text),
            model=self.model,
        )

    # ------------------------------------------------------------ templates

    _SCAFFOLD = frozenset(
        "conscious contents goal goals question persona plan risk memory tick "
        "workspace author priority respond user stated current forks reminder "
        "verdict assessment perception disagreement remind stimulus broadcast "
        "idle tool utterance belief consensus schedule scheduled dead".split()
    )

    def _respond(self, request: LLMRequest, rng: random.Random) -> str:
        system = request.system.lower()
        last = request.messages[-1]["content"]
        ks = [w for w in keywords(last, 24) if w not in self._SCAFFOLD][:8]
        ks = ks or ["the-matter", "the-details"]
        k = {f"k{i}": ks[i % len(ks)] for i in range(4)}

        if "persona:" in system:
            persona = system.split("persona:", 1)[1].split()[0].strip(".,")
            template = _PERSONA_STANCE.get(
                persona, "Considering {k0} and {k1}, a cautious yes."
            )
            return template.format(**k)

        if "planner" in system or "make a plan" in system:
            return (
                "PLAN:\n"
                f"1. Clarify the goal around {k['k0']} and note what success looks like.\n"
                f"2. Gather the two facts that decide it: state of {k['k1']}, and constraints on {k['k2']}.\n"
                "3. Run the smallest reversible step and observe.\n"
                f"4. Decide, record the decision, and schedule a follow-up check."
            )

        if "critic" in system or "red-team" in system:
            return (
                f"RISK: The current line of thinking assumes {k['k0']} is stable, "
                f"which has not been verified. Failure mode: {k['k1']} changes "
                "underneath the plan. Mitigation: verify before acting, and keep "
                "step 3 reversible."
            )

        if "distill" in system or "consolidat" in system:
            return (
                f"LESSON: Decisions about {k['k0']} were revisited; verify current "
                "status before advising, since positions can reverse.\n"
                f"LESSON: Reminders tied to {k['k1']} were useful; keep scheduling "
                "explicit follow-ups after giving advice."
            )

        if "summarize" in system or "merge" in system:
            return (
                f"Consensus view: proceed carefully on {k['k0']}; the main "
                f"disagreement concerns {k['k1']}."
            )

        if "speaker" in system or "reply to the user" in system:
            return (
                f"Here's where I've landed on {k['k0']}: it looks workable, with one "
                f"real caveat around {k['k1']}. My internal review didn't fully "
                "agree, so treat this as a leaning, not a verdict — I'd stage the "
                "change and keep a rollback. I've scheduled myself a follow-up to "
                "check on this."
            )

        # generic fallback — varied but deterministic
        opener = rng.choice(["Noted.", "Understood.", "Considered."])
        return f"{opener} The salient elements are {k['k0']} and {k['k1']}."
