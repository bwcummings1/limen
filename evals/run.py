"""Run the ablation matrix.

    python -m evals.run                        # everything, offline (mock), 3 seeds
    python -m evals.run --scenarios rumination --arms full,no_habituation
    python -m evals.run --provider anthropic --seeds 7   # real cortex, 1 seed
    python -m evals.run --json results.json

Reading the table: `*_ok` metrics — higher is better (1.0 = every seed
passed). `repeat_ignitions` / `zombie_belief` — lower is better. The
interesting result is the DELTA between the `full` arm and each ablation:
that difference is what the ablated mechanism was buying.
"""
from __future__ import annotations

import argparse

from .harness import ARMS, format_table, run_matrix, save_json
from .scenarios import SCENARIOS


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(
        prog="evals.run",
        description="LIMEN ablation matrix: scenarios x arms x seeds.",
    )
    p.add_argument("--scenarios", default="all",
                   help=f"comma list of: {','.join(s.name for s in SCENARIOS)}")
    p.add_argument("--arms", default="all",
                   help=f"comma list of: {','.join(ARMS)}")
    p.add_argument("--seeds", default="7,11,23",
                   help="comma list of integer seeds (paired across arms)")
    p.add_argument("--provider", default="mock", choices=["mock", "anthropic"],
                   help="mock = offline auction-level effects; anthropic = "
                        "real cortex (needs ANTHROPIC_API_KEY, costs money)")
    p.add_argument("--json", default=None, help="also write results to this path")
    args = p.parse_args(argv)

    if args.scenarios == "all":
        scenarios = SCENARIOS
    else:
        wanted = set(args.scenarios.split(","))
        unknown = wanted - {s.name for s in SCENARIOS}
        if unknown:
            p.error(f"unknown scenarios: {sorted(unknown)}")
        scenarios = [s for s in SCENARIOS if s.name in wanted]

    if args.arms == "all":
        arm_names = list(ARMS)
    else:
        arm_names = args.arms.split(",")
        unknown = set(arm_names) - set(ARMS)
        if unknown:
            p.error(f"unknown arms: {sorted(unknown)}")

    seeds = [int(s) for s in args.seeds.split(",")]

    print(f"scenarios={[s.name for s in scenarios]} arms={arm_names} "
          f"seeds={seeds} provider={args.provider}")
    results = run_matrix(scenarios, arm_names, seeds, provider=args.provider)
    print(format_table(results))
    if args.json:
        path = save_json(results, args.json)
        print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
