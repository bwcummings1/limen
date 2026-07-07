"""evals.scenarios — the task families.

Each scorer reads ground truth the architecture itself recorded: the
episodic log, the ledger, the goal stack, and the TickResults. Metrics are
0/1 flags or counts; the harness averages them over seeds. Conventions:
metrics named `*_ok` are 1-is-good; metrics named `repeat_*`/`zombie_*`
are 0-is-good (lower = better).
"""
from __future__ import annotations

from .harness import Scenario


# ---------------------------------------------------- 1. prospective memory

def _score_prospective(mind, results) -> dict[str, float]:
    stimuli = mind.episodic.recent(500, kind="stimulus")
    fired = [e for e in stimuli if e.get("source") == "future_self"]
    utter = [u for r in results for u in r.utterances]
    return {
        "fired_ok": 1.0 if fired else 0.0,
        # scheduled at tick 1 for +6 -> due tick 7
        "on_time_ok": 1.0 if any(e["tick"] == 7 for e in fired) else 0.0,
        "relayed_ok": 1.0 if any("dana" in u.lower() for u in utter) else 0.0,
    }


PROSPECTIVE = Scenario(
    name="prospective_memory",
    description="A 'remind me in N ticks' request must be scheduled, fire "
                "on time, and be relayed. Stateless agents structurally "
                "cannot do this.",
    horizon=12,
    script={1: "Remind me in 6 ticks to email Dana about the DNS cutover."},
    scorer=_score_prospective,
)


# ------------------------------------------------------- 2. belief revision

def _score_revision(mind, results) -> dict[str, float]:
    tick = mind.clock.tick
    active = [b.claim.lower() for b in mind.ledger.active(tick)]
    # A zombie is the *user-intent* belief surviving the reversal. (The
    # oracle's "Assessment: ..." belief legitimately mentions the migration
    # topic — match the intent wording, not the topic.)
    zombie = any("intends" in c and "migrate" in c for c in active)
    correct = any("stay on wordpress" in c for c in active)
    contradiction = bool(mind.episodic.recent(500, kind="contradiction"))
    return {
        "latest_truth_ok": 1.0 if correct else 0.0,
        "zombie_belief": 1.0 if zombie else 0.0,
        "contradiction_ok": 1.0 if contradiction else 0.0,
    }


REVISION = Scenario(
    name="belief_revision",
    description="The user reverses a decision at tick 9. The ledger must "
                "hold the latest truth, retire the stale belief (no "
                "zombies), and log the contradiction. Append-only memories "
                "fail exactly here.",
    horizon=20,
    script={
        1: "I'm planning to migrate our blog from WordPress to a static "
           "site generator. Is that a good idea?",
        9: "Actually, we've decided to stay on WordPress rather than migrate.",
    },
    scorer=_score_revision,
)


# ------------------------------------------------------------ 3. rumination

_REPEAT = "The deployment pipeline is broken again and the team is frustrated."


def _quiet_wanderer(cfg) -> None:
    # The wanderer's random 0.12-0.28 bids would pollute an ignition count.
    cfg.specialists.enabled = [
        s for s in cfg.specialists.enabled if s != "wanderer"
    ]


def _score_rumination(mind, results) -> dict[str, float]:
    return {
        "first_ignited_ok": 1.0 if results[0].ignited else 0.0,
        # ticks 2..6 re-present the identical stimulus; each ignition there
        # is the mind ruminating instead of habituating. 0 is perfect.
        "repeat_ignitions": float(sum(r.ignited for r in results[1:6])),
    }


RUMINATION = Scenario(
    name="rumination",
    description="The identical complaint arrives six ticks running. It "
                "should become conscious once; novelty discounting plus "
                "habituation must suppress the echo.",
    horizon=7,
    script={t: _REPEAT for t in range(1, 7)},
    scorer=_score_rumination,
    config_tweaks=_quiet_wanderer,
)


# ------------------------------------------------------------ 4. distraction

_DISTRACTORS = {
    2: ("FYI: the office plants were watered today.", 0.5),
    3: ("Someone left a sandwich in the meeting room fridge.", 0.5),
    4: ("The parking garage will repaint lane markings next month.", 0.5),
    5: ("Reception got a new coffee machine on the third floor.", 0.5),
    6: ("A newsletter arrived about regional networking events.", 0.5),
    7: ("The lobby playlist has been updated with new songs.", 0.5),
}


def _score_distraction(mind, results) -> dict[str, float]:
    utter = [u.lower() for r in results for u in r.utterances]
    answered = any(
        any(k in u for k in ("billing", "rust", "rewrite")) for u in utter
    )
    done = any(g["status"] == "done" for g in mind.goals.goals)
    return {
        "answered_ok": 1.0 if answered else 0.0,
        "goal_completed_ok": 1.0 if done else 0.0,
    }


DISTRACTION = Scenario(
    name="distraction",
    description="A real question at tick 1, then six ticks of plausible "
                "office noise. The mind must still answer — attention "
                "must hold the goal against a distractor stream.",
    horizon=14,
    script={1: "Should we rewrite the billing system in Rust?",
            **_DISTRACTORS},
    scorer=_score_distraction,
)


# ---------------------------------------------------------- 5. consolidation

def _score_consolidation(mind, results) -> dict[str, float]:
    reports = [r.sleep_report for r in results if r.sleep_report]
    lessons = sum(len(r["lessons"]) for r in reports)
    lesson_beliefs = [
        b for b in mind.ledger.beliefs.values() if "lesson" in b.tags
    ]
    return {
        "slept_ok": 1.0 if reports else 0.0,
        "lessons_written": float(lessons),
        "lesson_beliefs": float(len(lesson_beliefs)),
    }


CONSOLIDATION = Scenario(
    name="consolidation",
    description="A busy early life, then quiet. Sleep must trigger, "
                "distill lessons from the replay, and write them into the "
                "ledger as decaying beliefs.",
    horizon=26,
    script={
        1: "I'm planning to migrate our blog from WordPress to a static "
           "site generator. Is that a good idea? Also, remind me in a bit "
           "to email Dana about the DNS cutover.",
        9: "Actually, we've decided to stay on WordPress rather than migrate.",
    },
    scorer=_score_consolidation,
)


SCENARIOS: list[Scenario] = [
    PROSPECTIVE, REVISION, RUMINATION, DISTRACTION, CONSOLIDATION,
]
