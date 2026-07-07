"""limen.cli — watching a mind think.

  limen demo                  scripted end-to-end scenario (mock provider,
                              zero keys, deterministic) with a live
                              stream-of-consciousness trace
  limen run                   interactive REPL: your lines become stimuli
  limen ask "…"               one-shot question
  limen tick -n 5             advance cognitive time
  limen inspect <what>        beliefs | workspace | metrics | episodic |
                              skills | intentions | status
  limen daemon --period 5     free-run, one tick per N wall-seconds
"""
from __future__ import annotations

import argparse
import json
import sys
import time

from .config import Config
from .cycle import TickResult
from .mind import Mind


# ------------------------------------------------------------------ tracing

def print_tick(r: TickResult, verbose: bool = True) -> None:
    if r.ignited:
        print(f"t={r.tick:03d} ⚡{r.top_priority:.2f} ignition "
              f"({r.proposal_count} bids)")
        for w in r.winners:
            head = w["content"].splitlines()[0][:96]
            print(f"      ★ {w['author']}/{w['kind']} p={w['priority']:.2f} :: {head}")
    elif verbose:
        print(f"t={r.tick:03d} · idle (top {r.top_priority:.2f} "
              f"< {r.threshold:.2f}, {r.proposal_count} bids)")
    if r.sleep_report is not None:
        print(f"      ☾ sleep: {len(r.sleep_report['lessons'])} lessons, "
              f"{len(r.sleep_report['beliefs_pruned'])} pruned")
        for lesson in r.sleep_report["lessons"]:
            print(f"        ▹ {lesson}")
    for u in r.utterances:
        print(f"\n🗣  {u}\n")


# ------------------------------------------------------------------- demo

DEMO_SCRIPT = {
    1: ("I'm planning to migrate our blog from WordPress to a static site "
        "generator. Is that a good idea? Also, remind me in a bit to email "
        "Dana about the DNS cutover."),
    9: "Actually, we've decided to stay on WordPress rather than migrate.",
}


def cmd_demo(args: argparse.Namespace) -> None:
    cfg = Config.load(args.config)
    cfg.mind.data_dir = args.data_dir or "limen-demo"
    cfg.provider.kind = "mock"          # demo is always offline
    mind = Mind.from_config(cfg)

    print(f"── LIMEN demo · mind '{cfg.mind.name}' · seed {cfg.mind.seed} "
          f"· provider mock ──\n")
    for target in range(1, args.ticks + 1):
        if target in DEMO_SCRIPT:
            print(f'      ▷ user: "{DEMO_SCRIPT[target][:90]}…"'
                  if len(DEMO_SCRIPT[target]) > 90
                  else f'      ▷ user: "{DEMO_SCRIPT[target]}"')
            mind.stimulate(DEMO_SCRIPT[target])
        print_tick(mind.tick())

    print("\n── after-action inspection ──")
    _print_beliefs(mind)
    print()
    _print_metrics(mind)


# ------------------------------------------------------------------- run

def cmd_run(args: argparse.Namespace) -> None:
    mind = Mind.from_config(args.config)
    print("LIMEN REPL — your messages become stimuli. Commands: "
          "/tick N, /inspect WHAT, /quit")
    while True:
        try:
            line = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line == "/quit":
            break
        if line.startswith("/tick"):
            n = int(line.split()[1]) if len(line.split()) > 1 else 1
            for r in mind.run_ticks(n):
                print_tick(r)
            continue
        if line.startswith("/inspect"):
            what = line.split()[1] if len(line.split()) > 1 else "status"
            _inspect(mind, what)
            continue
        mind.stimulate(line)
        utterances, results = mind.run_until_response(max_ticks=args.max_ticks)
        for r in results:
            print_tick(r, verbose=args.verbose)
        if not utterances:
            print("(the mind had nothing to say — try /tick to let it think)")


def cmd_ask(args: argparse.Namespace) -> None:
    mind = Mind.from_config(args.config)
    mind.stimulate(args.question)
    utterances, results = mind.run_until_response(max_ticks=args.max_ticks)
    if args.trace:
        for r in results:
            print_tick(r)
    for u in utterances:
        print(u)


def cmd_tick(args: argparse.Namespace) -> None:
    mind = Mind.from_config(args.config)
    if args.stimulus:
        mind.stimulate(args.stimulus)
    for r in mind.run_ticks(args.n):
        print_tick(r)


def cmd_daemon(args: argparse.Namespace) -> None:
    mind = Mind.from_config(args.config)
    print(f"LIMEN daemon: 1 tick / {args.period}s. Ctrl-C to stop.")
    try:
        while True:
            print_tick(mind.tick(), verbose=args.verbose)
            time.sleep(args.period)
    except KeyboardInterrupt:
        print("\ndaemon stopped.")


# ---------------------------------------------------------------- inspect

def _print_beliefs(mind: Mind) -> None:
    tick = mind.clock.tick
    active = mind.ledger.active(tick)
    print(f"beliefs ({len(active)} active):")
    for b in active:
        print(f"  [{b.effective_confidence(tick):.2f}] {b.claim}  "
              f"«{','.join(b.tags) or 'untagged'}»")
    others = [b for b in mind.ledger.beliefs.values() if b.status != "active"]
    for b in others:
        print(f"  [{b.status}] {b.claim}")


def _print_metrics(mind: Mind) -> None:
    print("metrics:")
    for k, v in mind.metrics.snapshot().items():
        print(f"  {k}: {v}")


def _inspect(mind: Mind, what: str) -> None:
    tick = mind.clock.tick
    if what == "beliefs":
        _print_beliefs(mind)
    elif what == "workspace":
        print(mind.workspace.render())
    elif what == "metrics":
        _print_metrics(mind)
    elif what == "episodic":
        for e in mind.episodic.recent(20):
            print(f"  t={e['tick']:03d} {e['kind']:<12} "
                  f"{(e.get('content') or '')[:100]}")
    elif what == "skills":
        for slug, meta in mind.skills.index.items():
            print(f"  {slug}: {meta['title']} (tick {meta['tick']})")
    elif what == "intentions":
        for i in mind.timekeeper.pending.values():
            print(f"  {i.id}: {i.message} "
                  f"(due={i.due_tick} every={i.every} deadman={i.watch_tag})")
    elif what == "status":
        print(json.dumps(mind.status(), indent=2))
    else:
        print(f"unknown inspect target: {what}", file=sys.stderr)


def cmd_inspect(args: argparse.Namespace) -> None:
    _inspect(Mind.from_config(args.config), args.what)


# ------------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(
        prog="limen",
        description="LIMEN — a Global Workspace Theory runtime for LLM agents.",
    )
    p.add_argument("--config", default=None, help="path to limen.toml")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("demo", help="scripted offline demo")
    d.add_argument("--ticks", type=int, default=26)
    d.add_argument("--data-dir", default=None)
    d.set_defaults(fn=cmd_demo)

    r = sub.add_parser("run", help="interactive REPL")
    r.add_argument("--max-ticks", type=int, default=8)
    r.add_argument("-v", "--verbose", action="store_true")
    r.set_defaults(fn=cmd_run)

    a = sub.add_parser("ask", help="one-shot question")
    a.add_argument("question")
    a.add_argument("--max-ticks", type=int, default=8)
    a.add_argument("--trace", action="store_true")
    a.set_defaults(fn=cmd_ask)

    t = sub.add_parser("tick", help="advance cognitive time")
    t.add_argument("-n", type=int, default=1)
    t.add_argument("--stimulus", default=None)
    t.set_defaults(fn=cmd_tick)

    i = sub.add_parser("inspect", help="look inside the mind")
    i.add_argument("what", choices=[
        "beliefs", "workspace", "metrics", "episodic",
        "skills", "intentions", "status",
    ])
    i.set_defaults(fn=cmd_inspect)

    dm = sub.add_parser("daemon", help="free-running mind on wall time")
    dm.add_argument("--period", type=float, default=5.0)
    dm.add_argument("-v", "--verbose", action="store_true")
    dm.set_defaults(fn=cmd_daemon)

    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
