"""Command-line interface for GM-Bench."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from gm_bench.agents import AGENTS, ExternalProcessAgent
from gm_bench.runner import evaluate_against_baselines, run_many
from gm_bench.simulator import League
from gm_bench.storage import DEFAULT_DB_PATH, log_payload


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="gm-bench")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="run one agent across seeds")
    run_parser.add_argument("--agent", choices=sorted(AGENTS), default="value")
    run_parser.add_argument("--agent-cmd", help="external command implementing the JSON agent protocol")
    run_parser.add_argument("--agent-timeout", type=float, default=10.0, help="seconds to wait for each external-agent decision")
    run_parser.add_argument("--seeds", nargs="+", type=int, default=[1])
    run_parser.add_argument("--seasons", type=int, default=5)
    run_parser.add_argument("--json", action="store_true", help="emit full JSON results")
    _add_logging_args(run_parser)

    compare_parser = subparsers.add_parser("compare", help="compare built-in agents")
    compare_parser.add_argument("--agents", nargs="+", choices=sorted(AGENTS), default=sorted(AGENTS))
    compare_parser.add_argument("--seeds", nargs="+", type=int, default=[1, 2, 3])
    compare_parser.add_argument("--seasons", type=int, default=5)
    compare_parser.add_argument("--json", action="store_true")
    _add_logging_args(compare_parser)

    evaluate_parser = subparsers.add_parser("evaluate", help="evaluate an agent against a normalized baseline panel")
    evaluate_parser.add_argument("--agent", choices=sorted(AGENTS), default="value")
    evaluate_parser.add_argument("--agent-cmd", help="external command implementing the JSON agent protocol")
    evaluate_parser.add_argument("--agent-timeout", type=float, default=10.0, help="seconds to wait for each external-agent decision")
    evaluate_parser.add_argument("--baselines", nargs="+", choices=sorted(AGENTS), default=["random", "conservative", "win-now", "rebuild"])
    evaluate_parser.add_argument("--seeds", nargs="+", type=int, default=[1, 2, 3, 4, 5])
    evaluate_parser.add_argument("--seasons", type=int, default=5)
    evaluate_parser.add_argument("--json", action="store_true")
    _add_logging_args(evaluate_parser)

    describe_parser = subparsers.add_parser("describe", help="describe a generated league seed")
    describe_parser.add_argument("--seed", type=int, default=1)

    gui_parser = subparsers.add_parser("gui", help="start the local GM-Bench web GUI")
    gui_parser.add_argument("--host", default="127.0.0.1")
    gui_parser.add_argument("--port", type=int, default=8765)
    gui_parser.add_argument("--db", default=os.environ.get("GM_BENCH_DB", str(DEFAULT_DB_PATH)))

    args = parser.parse_args(argv)
    if args.command == "run":
        agent = ExternalProcessAgent(args.agent_cmd, timeout_seconds=args.agent_timeout) if args.agent_cmd else AGENTS[args.agent]()
        result = run_many(agent, args.seeds, args.seasons)
        run_id = _maybe_log(args, "run", result)
        _print_result(result, args.json)
        _print_log_line(run_id, args)
    elif args.command == "compare":
        results = [run_many(AGENTS[name](), args.seeds, args.seasons) for name in args.agents]
        run_id = _maybe_log(args, "compare", results)
        if args.json:
            print(json.dumps(results, indent=2, sort_keys=True))
        else:
            _print_table(results)
        _print_log_line(run_id, args)
    elif args.command == "evaluate":
        agent = ExternalProcessAgent(args.agent_cmd, timeout_seconds=args.agent_timeout) if args.agent_cmd else AGENTS[args.agent]()
        result = evaluate_against_baselines(agent, args.seeds, args.seasons, args.baselines)
        run_id = _maybe_log(args, "evaluate", result)
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        else:
            _print_evaluation(result)
        _print_log_line(run_id, args)
    elif args.command == "describe":
        league = League.new(args.seed)
        print(json.dumps(league.observation("preseason"), indent=2, sort_keys=True))
    elif args.command == "gui":
        from gm_bench.gui import serve

        serve(args.host, args.port, args.db)


def _add_logging_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--db", default=os.environ.get("GM_BENCH_DB", str(DEFAULT_DB_PATH)), help="SQLite database path for automatic run logging")
    parser.add_argument("--no-log", action="store_true", help="disable automatic SQLite run logging")


def _maybe_log(args: argparse.Namespace, command: str, payload: Any) -> str | None:
    if args.no_log:
        return None
    return log_payload(command, payload, args.db)


def _print_log_line(run_id: str | None, args: argparse.Namespace) -> None:
    if not run_id:
        return
    line = f"logged_run_id={run_id} db={args.db}"
    if args.json:
        print(line, file=sys.stderr)
    else:
        print(line)


def _print_result(result: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    summary = result["summary"]
    print(f"agent={result['agent']} seasons={result['seasons']} seeds={result['seeds']}")
    print(
        "mean_score={mean_score} score_stddev={score_stddev} mean_total_wins={mean_total_wins} championships={championships} illegal_actions={illegal_actions}".format(
            **summary
        )
    )


def _print_table(results: list[dict[str, Any]]) -> None:
    print("agent          mean_score  stddev  mean_wins  titles  illegal")
    print("---------------------------------------------------------------")
    for result in sorted(results, key=lambda item: item["summary"]["mean_score"], reverse=True):
        summary = result["summary"]
        print(
            f"{result['agent']:<14}{summary['mean_score']:>10.2f}{summary['score_stddev']:>8.2f}{summary['mean_total_wins']:>11.2f}{summary['championships']:>8}{summary['illegal_actions']:>9}"
        )


def _print_evaluation(result: dict[str, Any]) -> None:
    normalized = result["normalized"]
    print(f"agent={result['agent']} seasons={result['seasons']} seeds={result['seeds']}")
    print(
        "candidate_mean={candidate_mean_score} baseline_panel_mean={baseline_panel_mean_score} lift={score_lift} lift_pct={score_lift_pct}% illegal={candidate_illegal_actions}".format(
            **normalized
        )
    )
    paired = result.get("paired")
    if paired:
        low, high = paired["paired_lift_ci95"]
        verdict = "significant" if paired["significant_at_95"] else "within noise"
        print(
            f"paired_lift={paired['paired_lift_mean']} ci95=[{low}, {high}] ({verdict}) "
            f"panel_seed_win_rate={paired['panel_seed_win_rate']} over {paired['num_seeds']} seed(s)"
        )
        best = paired.get("best_baseline")
        if best:
            print(
                f"vs strongest baseline '{best['agent']}': paired_lift={best['paired_lift_mean']} "
                f"seed_win_rate={best['seed_win_rate']}"
            )
    print()
    _print_table([result["candidate"], *result["baselines"]])


if __name__ == "__main__":
    main()
