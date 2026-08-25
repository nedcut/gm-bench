#!/usr/bin/env python3
"""Record decision windows for illustrative puzzle content.

This is content generation, not measurement. Nothing it writes feeds a score, a
leaderboard row, or a published artifact, and it is deliberately not pinned to a
benchmark contract. It runs at HEAD.

Each recorded decision holds the observation the acting agent saw, the actions
it chose, and the immediate change in ``score_components`` those actions caused,
alongside the same three things for every ghost -- other policies handed the
identical observation on a throwaway copy of the league.

Scripted agents are the default subjects because they are free and deterministic,
so the extraction pipeline can be built and tuned before any model spend. Point
``--agent`` at a model adapter to record real model decisions the same way.

    python scripts/record_decisions.py --seeds 1 2 3 --seasons 5
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gm_bench.agents import AGENTS  # noqa: E402
from gm_bench.recorder import DEFAULT_GHOSTS, DecisionRecorder, record_episode  # noqa: E402
from gm_bench.scoring import score_team  # noqa: E402

DEFAULT_SUBJECTS = ("conservative", "win-now", "rebuild", "value", "random")
DEFAULT_OUTPUT = Path("data/decision-records")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--agents",
        nargs="+",
        default=list(DEFAULT_SUBJECTS),
        help="agents whose decisions are recorded (default: the weaker scripted policies)",
    )
    parser.add_argument("--seeds", nargs="+", type=int, default=[1, 2, 3, 5, 8, 11, 13, 21])
    parser.add_argument("--seasons", type=int, default=5)
    parser.add_argument(
        "--ghosts",
        nargs="+",
        default=list(DEFAULT_GHOSTS),
        help="policies replayed on each decision to supply puzzle options",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    unknown = [name for name in [*args.agents, *args.ghosts] if name not in AGENTS]
    if unknown:
        parser.error(f"unknown agents {unknown}; expected names from {sorted(AGENTS)}")

    args.output.mkdir(parents=True, exist_ok=True)
    total = 0
    for agent_name in args.agents:
        for seed in args.seeds:
            path = args.output / f"{agent_name}-seed{seed}.jsonl"
            with DecisionRecorder(path, agent_name=agent_name, ghost_agents=args.ghosts) as recorder:
                league = record_episode(
                    AGENTS[agent_name](),
                    seed=seed,
                    recorder=recorder,
                    seasons=args.seasons,
                )
            total += recorder.decision_index
            print(
                f"{agent_name:14} seed {seed:3}  score {score_team(league, 0):8.1f}  "
                f"cups {league.user_team.championships}  decisions {recorder.decision_index}",
                flush=True,
            )
    print(f"\nrecorded {total} decisions to {args.output}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
