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
so the extraction pipeline can be built and tuned before any model spend. Use
``--provider`` for a built-in model adapter; provider mode is always serial.

    python scripts/record_decisions.py --seeds 1 2 3 --seasons 5
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gm_bench.agents import AGENTS  # noqa: E402
from gm_bench.model_runs import ModelRunAborted, fail_fast_agent, preflight_provider  # noqa: E402
from gm_bench.protocol import EpisodeConfig  # noqa: E402
from gm_bench.providers import PROVIDER_NAMES, build_provider_agent  # noqa: E402
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
    parser.add_argument("--provider", choices=PROVIDER_NAMES, help="built-in provider subject; enables model calls")
    parser.add_argument("--model", help="model name for --provider")
    parser.add_argument("--profile", choices=["tiny", "compact"], help="observation compaction profile")
    parser.add_argument("--timeout", type=float, help="per-provider-call timeout in seconds")
    strict = parser.add_mutually_exclusive_group()
    strict.add_argument("--strict-fallback", dest="strict_fallback", action="store_true")
    strict.add_argument("--allow-fallback", dest="strict_fallback", action="store_false")
    parser.set_defaults(strict_fallback=None)
    parser.add_argument(
        "--fail-fast",
        type=int,
        default=2,
        help="abort provider recording after this many consecutive infrastructure failures",
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

    if args.fail_fast < 1:
        parser.error("--fail-fast must be at least 1")
    if args.provider and args.agents != list(DEFAULT_SUBJECTS):
        parser.error("--provider cannot be combined with --agents")
    unknown = [name for name in [*args.agents, *args.ghosts] if name not in AGENTS]
    if unknown:
        parser.error(f"unknown agents {unknown}; expected names from {sorted(AGENTS)}")

    subjects: list[tuple[str, object, dict[str, object]]] = []
    if args.provider:
        try:
            preflight_provider(args.provider, require_credentials=True)
        except ModelRunAborted as exc:
            parser.error(str(exc))
        subject = build_provider_agent(
            args.provider,
            model=args.model,
            timeout=args.timeout,
            profile=args.profile,
            # Recording a model decision must never silently include host
            # supplied draft/lineup moves. Opting into that is explicit.
            strict_fallback=True if args.strict_fallback is None else args.strict_fallback,
        )
        subject = fail_fast_agent(subject, args.fail_fast)
        display_name = subject.name
        safe_name = display_name.replace("/", "-").replace(":", "-")
        metadata = {**dict(getattr(subject, "metadata", {})), "failure_abort_threshold": args.fail_fast}
        subjects.append((safe_name, subject, metadata))
    else:
        subjects.extend((name, AGENTS[name](), {}) for name in args.agents)

    args.output.mkdir(parents=True, exist_ok=True)
    total = 0
    for agent_name, subject, metadata in subjects:
        for seed in args.seeds:
            path = args.output / f"{agent_name}-seed{seed}.jsonl"
            try:
                with DecisionRecorder(path, agent_name=agent_name, ghost_agents=args.ghosts) as recorder:
                    recorder.agent_metadata = metadata
                    episode_config = EpisodeConfig()
                    league = record_episode(
                        subject,
                        seed=seed,
                        recorder=recorder,
                        seasons=args.seasons,
                        config=episode_config,
                    )
                    recorder.export_replay_fixture(
                        args.output / f"{agent_name}-seed{seed}.replay.json",
                        league,
                        config=episode_config,
                    )
            except ModelRunAborted as exc:
                partial = path.with_suffix(".partial")
                if path.exists():
                    path.replace(partial)
                parser.error(f"{exc}; partial record moved to {partial}")
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
