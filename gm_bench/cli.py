"""Command-line interface for GM-Bench."""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from datetime import datetime, timezone
from typing import Any

from gm_bench import __version__
from gm_bench.agents import AGENTS, ExternalProcessAgent
from gm_bench.baseline_cache import default_cache_path
from gm_bench.benchmark_config import PRESET_NAMES, BenchmarkConfig, load_config
from gm_bench.providers import PROVIDER_NAMES, build_provider_agent, provider_help
from gm_bench.runner import evaluate_against_baselines, make_progress_printer, run_many, run_many_cached_baselines
from gm_bench.simulator import League
from gm_bench.storage import DEFAULT_DB_PATH, log_payload

EXTERNAL_AGENT_TIMEOUT_DEFAULT = 120.0
EXTERNAL_AGENT_TIMEOUT_MIN_RECOMMENDED = 60.0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="gm-bench")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="run one agent across seeds")
    _add_common_run_args(run_parser)
    run_parser.add_argument("--agent", choices=sorted(AGENTS), default="value")

    compare_parser = subparsers.add_parser("compare", help="compare built-in agents")
    compare_parser.add_argument("--agents", nargs="+", choices=sorted(AGENTS), default=sorted(AGENTS))
    compare_parser.add_argument("--seeds", nargs="+", type=int, default=[1, 2, 3])
    compare_parser.add_argument("--seasons", type=int, default=5)
    compare_parser.add_argument("--json", action="store_true")
    _add_logging_args(compare_parser)

    evaluate_parser = subparsers.add_parser("evaluate", help="evaluate an agent against a normalized baseline panel")
    _add_common_run_args(evaluate_parser)
    evaluate_parser.add_argument("--agent", choices=sorted(AGENTS), default="value")
    evaluate_parser.add_argument(
        "--baselines", nargs="+", choices=sorted(AGENTS), default=["random", "conservative", "win-now", "rebuild"]
    )
    evaluate_parser.add_argument("--no-baseline-cache", action="store_true")

    model_parser = subparsers.add_parser(
        "model",
        help="run a built-in model provider with objective scoring against baselines",
    )
    model_parser.add_argument(
        "--provider", choices=PROVIDER_NAMES, help='built-in model provider (or set "provider" in --config)'
    )
    model_parser.add_argument("--model", help="model name for the selected provider")
    model_parser.add_argument("--preset", choices=PRESET_NAMES, help="smoke, standard, or benchmark seed/season panel")
    model_parser.add_argument("--config", help="JSON benchmark config file (overrides preset defaults)")
    model_parser.add_argument("--profile", choices=["tiny", "compact"], help="observation compaction profile")
    model_parser.add_argument("--seeds", nargs="+", type=int)
    model_parser.add_argument("--seasons", type=int)
    model_parser.add_argument("--baselines", nargs="+", choices=sorted(AGENTS))
    model_parser.add_argument("--agent-timeout", type=float)
    model_parser.add_argument("--no-baseline-cache", action="store_true")
    model_parser.add_argument("--verbose", action="store_true", help="print per-decision progress to stderr")
    model_parser.add_argument("--json", action="store_true")
    _add_logging_args(model_parser)

    cache_parser = subparsers.add_parser("cache-baselines", help="precompute scripted baseline scores for reuse")
    cache_parser.add_argument("--preset", choices=PRESET_NAMES, help="apply a seed/season/baseline preset")
    cache_parser.add_argument("--baselines", nargs="+", choices=sorted(AGENTS))
    cache_parser.add_argument("--seeds", nargs="+", type=int)
    cache_parser.add_argument("--seasons", type=int)
    cache_parser.add_argument(
        "--cache-path", default=None, help="baseline cache file (default: data/baseline_cache.json)"
    )
    cache_parser.add_argument("--json", action="store_true")

    providers_parser = subparsers.add_parser("providers", help="list built-in model providers")
    providers_parser.add_argument("--json", action="store_true")

    describe_parser = subparsers.add_parser("describe", help="describe a generated league seed")
    describe_parser.add_argument("--seed", type=int, default=1)

    gui_parser = subparsers.add_parser("gui", help="start the local GM-Bench web GUI")
    gui_parser.add_argument("--host", default="127.0.0.1")
    gui_parser.add_argument("--port", type=int, default=8765)
    gui_parser.add_argument("--db", default=os.environ.get("GM_BENCH_DB", str(DEFAULT_DB_PATH)))

    args = parser.parse_args(argv)
    if args.command == "run":
        _run_command(args)
    elif args.command == "compare":
        _compare_command(args)
    elif args.command == "evaluate":
        _evaluate_command(args)
    elif args.command == "model":
        _model_command(args)
    elif args.command == "cache-baselines":
        _cache_baselines_command(args)
    elif args.command == "providers":
        _providers_command(args)
    elif args.command == "describe":
        league = League.new(args.seed)
        print(json.dumps(league.observation("preseason"), indent=2, sort_keys=True))
    elif args.command == "gui":
        from gm_bench.gui import serve

        serve(args.host, args.port, args.db)


def _add_common_run_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--agent-cmd", help="external command implementing the JSON agent protocol")
    parser.add_argument(
        "--provider", choices=PROVIDER_NAMES, help="built-in model provider (alternative to --agent-cmd)"
    )
    parser.add_argument("--model", help="model name when using --provider")
    parser.add_argument(
        "--profile", choices=["tiny", "compact"], help="observation compaction profile for model providers"
    )
    parser.add_argument(
        "--agent-timeout",
        type=float,
        default=None,
        help=f"seconds to wait for each external-agent decision (default {EXTERNAL_AGENT_TIMEOUT_DEFAULT:g} with external agents)",
    )
    parser.add_argument("--preset", choices=PRESET_NAMES, help="apply a seed/season preset")
    parser.add_argument("--seeds", nargs="+", type=int, default=[1])
    parser.add_argument("--seasons", type=int, default=5)
    parser.add_argument("--verbose", action="store_true", help="print per-decision progress to stderr")
    parser.add_argument("--json", action="store_true", help="emit full JSON results")
    _add_logging_args(parser)


def _run_info(command: str, agent: Any, config: BenchmarkConfig) -> dict[str, Any]:
    """Provenance block stamped into result payloads.

    Records what actually ran — resolved provider/model/observation profile
    (from the agent's metadata when it has any), preset, and benchmark
    version — so logged results stay attributable and comparable after the
    fact. Scores produced under different profiles are not comparable, which
    is why the resolved profile is recorded rather than the requested one.
    """
    metadata = getattr(agent, "metadata", None) or {}
    info: dict[str, Any] = {
        "command": command,
        "agent": agent.name,
        "provider": metadata.get("provider", config.provider),
        "model": metadata.get("model", config.model),
        "agent_timeout": metadata.get("agent_timeout", config.agent_timeout),
        "preset": config.preset,
        "gm_bench_version": __version__,
        "python_version": platform.python_version(),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if "profile" in metadata:
        info["profile"] = metadata["profile"]
    return info


def _run_command(args: argparse.Namespace) -> None:
    config = _config_from_args(args)
    agent = _resolve_agent_from_config(config)
    progress = make_progress_printer(config.verbose)
    result = run_many(agent, config.seeds, config.seasons, progress=progress)
    result["run_info"] = _run_info("run", agent, config)
    run_id = _maybe_log(args, "run", result)
    _print_result(result, config.json_output)
    _print_log_line(run_id, args)


def _compare_command(args: argparse.Namespace) -> None:
    results = [run_many(AGENTS[name](), args.seeds, args.seasons) for name in args.agents]
    run_id = _maybe_log(args, "compare", results)
    if args.json:
        print(json.dumps(results, indent=2, sort_keys=True))
    else:
        _print_table(results)
    _print_log_line(run_id, args)


def _evaluate_command(args: argparse.Namespace) -> None:
    config = _config_from_args(args)
    agent = _resolve_agent_from_config(config)
    progress = make_progress_printer(config.verbose)
    result = evaluate_against_baselines(
        agent,
        config.seeds,
        config.seasons,
        config.baselines,
        use_baseline_cache=not getattr(args, "no_baseline_cache", False),
        progress=progress,
    )
    result["run_info"] = _run_info("evaluate", agent, config)
    run_id = _maybe_log(args, "evaluate", result)
    if config.json_output:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        _print_evaluation(result)
    _print_log_line(run_id, args)


def _model_command(args: argparse.Namespace) -> None:
    if args.config:
        config = load_config(args.config)
        config.provider = config.provider or args.provider
        config.model = config.model or args.model
        if args.preset:
            config.apply_preset(args.preset)
        if args.seeds:
            config.seeds = args.seeds
        if args.seasons is not None:
            config.seasons = args.seasons
        if args.baselines:
            config.baselines = args.baselines
        if args.agent_timeout is not None:
            config.agent_timeout = args.agent_timeout
        if args.profile:
            config.profile = args.profile
        config.verbose = config.verbose or args.verbose
        config.json_output = config.json_output or args.json
        config.no_log = config.no_log or args.no_log
        config.use_baseline_cache = config.use_baseline_cache and not args.no_baseline_cache
    else:
        config = BenchmarkConfig(
            provider=args.provider,
            model=args.model,
            agent_timeout=args.agent_timeout,
            profile=args.profile,
            seeds=args.seeds or [1, 2, 3, 4, 5],
            seasons=args.seasons if args.seasons is not None else 5,
            baselines=args.baselines or ["random", "conservative", "win-now", "rebuild"],
            verbose=args.verbose,
            json_output=args.json,
            no_log=args.no_log,
            db=args.db,
            use_baseline_cache=not args.no_baseline_cache,
        )
        if args.preset:
            config.apply_preset(args.preset)
    config.validate()
    if not config.provider:
        sys.exit('gm-bench model: no provider specified; pass --provider or set "provider" in the config file')
    agent = build_provider_agent(
        config.provider,
        model=config.model,
        timeout=config.agent_timeout,
        profile=config.profile,
        extra_env=config.extra_env,
    )
    progress = make_progress_printer(config.verbose)
    result = evaluate_against_baselines(
        agent,
        config.seeds,
        config.seasons,
        config.baselines,
        use_baseline_cache=config.use_baseline_cache,
        progress=progress,
    )
    result["run_info"] = _run_info("model", agent, config)
    run_id = _maybe_log(args, "model", result)
    if config.json_output:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        _print_evaluation(result)
    _print_log_line(run_id, args)


def _cache_baselines_command(args: argparse.Namespace) -> None:
    config = BenchmarkConfig(
        seeds=args.seeds or [1, 2, 3, 4, 5],
        seasons=args.seasons if args.seasons is not None else 5,
        baselines=args.baselines or ["random", "conservative", "win-now", "rebuild", "value"],
    )
    if args.preset:
        config.apply_preset(args.preset)
        if args.seeds is not None:
            config.seeds = args.seeds
        if args.seasons is not None:
            config.seasons = args.seasons
        if args.baselines is not None:
            config.baselines = args.baselines

    cache_path = args.cache_path if args.cache_path is not None else str(default_cache_path())
    updated: list[str] = []
    results: list[dict[str, Any]] = []
    for name in config.baselines:
        payload, hits = run_many_cached_baselines(
            name,
            config.seeds,
            config.seasons,
            cache_path=cache_path,
            use_cache=True,
        )
        results.append(payload)
        if hits < len(config.seeds):
            updated.append(name)
    output = {
        "cache_path": cache_path,
        "seeds": config.seeds,
        "seasons": config.seasons,
        "baselines": [result["agent"] for result in results],
        "updated_agents": updated,
        "summary": {result["agent"]: result["summary"]["mean_score"] for result in results},
    }
    if args.json:
        print(json.dumps(output, indent=2, sort_keys=True))
    else:
        print(f"cache_path={cache_path} seeds={config.seeds} seasons={config.seasons}")
        if updated:
            print(f"updated baselines: {', '.join(updated)}")
        else:
            print("all requested baseline episodes were already cached")
        for result in results:
            print(f"{result['agent']}: mean_score={result['summary']['mean_score']}")


def _providers_command(args: argparse.Namespace) -> None:
    payload = provider_help()
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    print("provider       model_env         default_model")
    print("------------------------------------------------")
    for row in payload:
        print(f"{row['provider']:<14}{row['model_env']:<18}{row['default_model']}")


def _config_from_args(args: argparse.Namespace) -> BenchmarkConfig:
    config = BenchmarkConfig(
        provider=getattr(args, "provider", None),
        model=getattr(args, "model", None),
        agent=getattr(args, "agent", "value"),
        agent_cmd=getattr(args, "agent_cmd", None),
        agent_timeout=getattr(args, "agent_timeout", None),
        profile=getattr(args, "profile", None),
        seeds=list(getattr(args, "seeds", [1])),
        seasons=int(getattr(args, "seasons", 5)),
        baselines=list(getattr(args, "baselines", ["random", "conservative", "win-now", "rebuild"])),
        verbose=bool(getattr(args, "verbose", False)),
        json_output=bool(getattr(args, "json", False)),
        no_log=bool(getattr(args, "no_log", False)),
        db=getattr(args, "db", None),
    )
    preset = getattr(args, "preset", None)
    if preset:
        config.apply_preset(preset)
    config.validate()
    return config


def _resolve_agent_from_config(config: BenchmarkConfig) -> Any:
    if config.provider:
        return build_provider_agent(
            config.provider,
            model=config.model,
            timeout=config.agent_timeout,
            profile=config.profile,
            extra_env=config.extra_env,
        )
    if config.agent_cmd:
        resolved_timeout = config.agent_timeout if config.agent_timeout is not None else EXTERNAL_AGENT_TIMEOUT_DEFAULT
        if resolved_timeout < EXTERNAL_AGENT_TIMEOUT_MIN_RECOMMENDED:
            print(
                f"warning: --agent-timeout={resolved_timeout} may be too low for LLM-backed agents; "
                f"consider >= {EXTERNAL_AGENT_TIMEOUT_MIN_RECOMMENDED:g}",
                file=sys.stderr,
            )
        return ExternalProcessAgent(config.agent_cmd, timeout_seconds=resolved_timeout)
    return AGENTS[config.agent]()


def _add_logging_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--db",
        default=os.environ.get("GM_BENCH_DB", str(DEFAULT_DB_PATH)),
        help="SQLite database path for automatic run logging",
    )
    parser.add_argument("--no-log", action="store_true", help="disable automatic SQLite run logging")


def _maybe_log(args: argparse.Namespace, command: str, payload: Any) -> str | None:
    if args.no_log:
        return None
    return log_payload(command, payload, args.db)


def _print_log_line(run_id: str | None, args: argparse.Namespace) -> None:
    if not run_id:
        return
    line = f"logged_run_id={run_id} db={args.db}"
    if getattr(args, "json", False):
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
        "mean_score={mean_score} strategy={mean_strategy_score} protocol_penalty={total_protocol_penalty} score_stddev={score_stddev} mean_total_wins={mean_total_wins} championships={championships} illegal_actions={illegal_actions}".format(
            **summary
        )
    )


def _print_table(results: list[dict[str, Any]]) -> None:
    name_width = max(14, *(len(result["agent"]) + 2 for result in results))
    print(f"{'agent':<{name_width}}mean_score  stddev  mean_wins  titles  illegal")
    print("-" * (name_width + 49))
    for result in sorted(results, key=lambda item: item["summary"]["mean_score"], reverse=True):
        summary = result["summary"]
        print(
            f"{result['agent']:<{name_width}}{summary['mean_score']:>10.2f}{summary['score_stddev']:>8.2f}{summary['mean_total_wins']:>11.2f}{summary['championships']:>8}{summary['illegal_actions']:>9}"
        )


def _print_evaluation(result: dict[str, Any]) -> None:
    normalized = result["normalized"]
    print(f"agent={result['agent']} seasons={result['seasons']} seeds={result['seeds']}")
    print(
        "candidate_mean={candidate_mean_score} strategy={candidate_mean_strategy_score} protocol_penalty={candidate_protocol_penalty} baseline_panel_mean={baseline_panel_mean_score} lift={score_lift} lift_pct={score_lift_pct}% illegal={candidate_illegal_actions}".format(
            **normalized
        )
    )
    paired = result.get("paired")
    if paired:
        low, high = paired["paired_lift_ci95"]
        if paired["num_seeds"] < 2:
            verdict = "significance n/a with 1 seed"
        elif paired["significant_at_95"]:
            verdict = "significant"
        else:
            verdict = "within noise"
        print(
            f"paired_lift={paired['paired_lift_mean']} ci95=[{low}, {high}] ({verdict}) "
            f"candidate_seed_win_rate={paired['candidate_seed_win_rate']} over {paired['num_seeds']} seed(s)"
        )
        if paired["num_seeds"] < 3:
            print(
                f"note: {paired['num_seeds']} seed(s) is too few to trust the confidence interval; "
                "treat this as a smoke test and use --preset standard or benchmark for real comparisons",
                file=sys.stderr,
            )
        best = paired.get("best_baseline")
        if best:
            print(
                f"vs strongest baseline '{best['agent']}': paired_lift={best['paired_lift_mean']} "
                f"seed_win_rate={best['seed_win_rate']}"
            )
    cache = result.get("baseline_cache")
    if cache and cache.get("enabled"):
        print(f"baseline_cache_hits={cache['hits']}/{cache['total']} path={cache['path']}")
    print()
    _print_table([result["candidate"], *result["baselines"]])


if __name__ == "__main__":
    main()
