"""Command-line interface for GM-Bench."""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gm_bench import __version__
from gm_bench.agents import AGENTS, ExternalProcessAgent
from gm_bench.baseline_cache import default_cache_path
from gm_bench.benchmark_config import PRESET_NAMES, BenchmarkConfig, load_config, seed_panel_metadata
from gm_bench.calibration import build_scoring_calibration
from gm_bench.contract import benchmark_contract, scaffold_fingerprint
from gm_bench.environment import load_environment_files
from gm_bench.model_runs import (
    ModelRunAborted,
    default_checkpoint_path,
    evaluate_resumable_candidate,
    preflight_provider,
    run_resumable_candidate,
)
from gm_bench.official import (
    POLICIES,
    PUBLIC_LEADERBOARD_POLICY,
    SOTA_V2_POLICY,
    redact_leaderboard_payload,
    validate_leaderboard_payload,
)
from gm_bench.oracle import OracleAgent
from gm_bench.providers import PROVIDER_NAMES, build_provider_agent, provider_help
from gm_bench.runner import evaluate_against_baselines, make_progress_printer, run_many, run_many_cached_baselines
from gm_bench.session import PersistentProcessAgent
from gm_bench.simulator import League
from gm_bench.storage import DEFAULT_DB_PATH, log_payload
from gm_bench.validity import run_validity_canaries

EXTERNAL_AGENT_TIMEOUT_DEFAULT = 120.0
EXTERNAL_AGENT_TIMEOUT_MIN_RECOMMENDED = 60.0

# The oracle is intentionally CLI-only.  Keeping it out of ``AGENTS`` means it
# cannot become an official baseline or alter the frozen benchmark contract.
CLI_AGENTS: dict[str, type[Any]] = {**AGENTS, "oracle": OracleAgent}


def _model_worker_count(agent: Any, requested: int | None) -> int | None:
    """Resolve model-command concurrency without changing the score contract.

    Worker scheduling is harness policy, not simulator semantics, so this lives
    outside ``runner.py`` (which is part of the frozen benchmark fingerprint).
    """
    if requested is not None:
        return max(1, requested)
    configured = os.environ.get("GM_BENCH_WORKERS")
    if configured:
        try:
            return max(1, int(configured))
        except ValueError:
            sys.exit("gm-bench model: GM_BENCH_WORKERS must be an integer")
    if isinstance(agent, (ExternalProcessAgent, PersistentProcessAgent)):
        return 1
    return None


@contextmanager
def _model_worker_environment(workers: int | None):
    """Temporarily pass model-command worker policy to the frozen runner."""
    previous = os.environ.get("GM_BENCH_WORKERS")
    try:
        if workers is None:
            os.environ.pop("GM_BENCH_WORKERS", None)
        else:
            os.environ["GM_BENCH_WORKERS"] = str(workers)
        yield
    finally:
        if previous is None:
            os.environ.pop("GM_BENCH_WORKERS", None)
        else:
            os.environ["GM_BENCH_WORKERS"] = previous


def main(argv: list[str] | None = None) -> None:
    load_environment_files()
    parser = argparse.ArgumentParser(prog="gm-bench")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="run one agent across seeds")
    _add_common_run_args(run_parser)
    run_parser.add_argument("--agent", choices=sorted(CLI_AGENTS), default="value")

    compare_parser = subparsers.add_parser("compare", help="compare built-in agents")
    compare_parser.add_argument("--agents", nargs="+", choices=sorted(CLI_AGENTS), default=sorted(AGENTS))
    compare_parser.add_argument("--seeds", nargs="+", type=int, default=[1, 2, 3])
    compare_parser.add_argument("--seasons", type=int, default=5)
    compare_parser.add_argument("--json", action="store_true")
    _add_logging_args(compare_parser)

    evaluate_parser = subparsers.add_parser("evaluate", help="evaluate an agent against a normalized baseline panel")
    _add_common_run_args(evaluate_parser)
    evaluate_parser.add_argument("--agent", choices=sorted(CLI_AGENTS), default="value")
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
    model_parser.add_argument(
        "--session",
        action="store_true",
        help="keep one adapter process alive per episode so the model retains its full "
        "trajectory in context (a separate measurement condition; not sota-v2 eligible)",
    )
    model_parser.add_argument("--seeds", nargs="+", type=int)
    model_parser.add_argument("--seasons", type=int)
    model_parser.add_argument(
        "--repeats",
        type=int,
        help="candidate episodes per seed; >1 separates model sampling noise from seed luck",
    )
    model_parser.add_argument("--baselines", nargs="+", choices=sorted(AGENTS))
    model_parser.add_argument("--agent-timeout", type=float)
    model_parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help=(
            "parallel episode workers for the candidate. Model/external adapters "
            "default to 1 (serial) so provider rate limits are not burned; "
            "scripted agents still fan out. Override with this flag or GM_BENCH_WORKERS."
        ),
    )
    model_parser.add_argument("--no-baseline-cache", action="store_true")
    model_parser.add_argument("--verbose", action="store_true", help="print per-decision progress to stderr")
    model_parser.add_argument(
        "--checkpoint",
        type=Path,
        help="durable per-episode checkpoint path (default: data/model_checkpoints/<agent>.json)",
    )
    model_parser.add_argument(
        "--resume",
        action="store_true",
        help="reuse zero-failure episodes from the matching --checkpoint file",
    )
    model_parser.add_argument(
        "--resume-from",
        action="append",
        type=Path,
        default=[],
        help="reuse zero-failure seed/repeat episodes from an earlier result JSON (repeatable)",
    )
    model_parser.add_argument(
        "--fail-fast",
        type=int,
        default=2,
        metavar="N",
        help="abort after N consecutive adapter failures (default: 2)",
    )
    model_parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="check provider authentication/tool availability without making a model request",
    )
    model_parser.add_argument("--json", action="store_true")
    model_parser.add_argument("--output", type=Path, help="atomically write the full JSON result artifact")
    model_parser.add_argument(
        "--require-clean",
        action="store_true",
        help="exit nonzero unless every model decision succeeds with complete usage and cost metadata",
    )
    _add_logging_args(model_parser, db_default=None)

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

    validate_parser = subparsers.add_parser(
        "validate-result",
        help="validate a saved leaderboard result against an official-result policy",
    )
    validate_parser.add_argument("path", help="JSON file produced by gm-bench model --preset leaderboard --json")
    validate_parser.add_argument(
        "--policy",
        choices=sorted(POLICIES),
        default=PUBLIC_LEADERBOARD_POLICY.name,
        help="validation policy to apply",
    )
    validate_parser.add_argument("--json", action="store_true", help="emit machine-readable validation output")

    redact_parser = subparsers.add_parser(
        "redact-result",
        help="write a public-safe leaderboard result artifact without private seed details",
    )
    redact_parser.add_argument("path", help="raw JSON file produced by gm-bench model --preset leaderboard --json")
    redact_parser.add_argument("--output", required=True, help="path for the redacted JSON artifact")
    redact_parser.add_argument(
        "--policy",
        choices=sorted(POLICIES),
        default=SOTA_V2_POLICY.name,
        help="validation policy to record before redaction",
    )

    validate_contract_parser = subparsers.add_parser(
        "validate-contract",
        help="run benchmark validity canaries against the official contract",
    )
    validate_contract_parser.add_argument("--seeds", nargs="+", type=int, help="override the official seed panel")
    validate_contract_parser.add_argument("--seasons", type=int, help="override official season count")
    validate_contract_parser.add_argument("--json", action="store_true", help="emit machine-readable canary output")

    calibrate_parser = subparsers.add_parser(
        "calibrate-score",
        help="reproduce scoring marginals and scripted-policy calibration",
    )
    calibrate_parser.add_argument("--seeds", nargs="+", type=int, help="override the official seed panel")
    calibrate_parser.add_argument("--seasons", type=int, help="override official season count")
    calibrate_parser.add_argument("--json", action="store_true", help="emit machine-readable calibration output")

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
    elif args.command == "validate-result":
        _validate_result_command(args)
    elif args.command == "redact-result":
        _redact_result_command(args)
    elif args.command == "validate-contract":
        _validate_contract_command(args)
    elif args.command == "calibrate-score":
        _calibrate_score_command(args)
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
    parser.add_argument(
        "--repeats",
        type=int,
        default=1,
        help="episodes per seed; >1 separates model sampling noise from seed luck (stochastic agents only)",
    )
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
        "benchmark_contract": benchmark_contract(),
        "scaffold_fingerprint": scaffold_fingerprint(metadata.get("provider", config.provider) or ""),
        "session": bool(metadata.get("session", False)),
        "seed_panel": seed_panel_metadata(config.seeds, config.preset),
        "python_version": platform.python_version(),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if "profile" in metadata:
        info["profile"] = metadata["profile"]
    if metadata.get("transport"):
        info["transport"] = metadata["transport"]
    if metadata.get("provider_options"):
        info["provider_options"] = metadata["provider_options"]
    return info


def _run_command(args: argparse.Namespace) -> None:
    config = _config_from_args(args)
    agent = _resolve_agent_from_config(config)
    progress = make_progress_printer(config.verbose)
    result = run_many(agent, config.seeds, config.seasons, repeats=config.repeats, progress=progress)
    result["run_info"] = _run_info("run", agent, config)
    run_id = _maybe_log(args, "run", result)
    _print_result(result, config.json_output)
    _print_log_line(run_id, args)


def _compare_command(args: argparse.Namespace) -> None:
    results = [run_many(CLI_AGENTS[name](), args.seeds, args.seasons) for name in args.agents]
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
        repeats=config.repeats,
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
    execution_options: dict[str, Any] = {}
    if args.config:
        config = load_config(args.config)
        execution_options = _load_model_execution_options(Path(args.config))
        if args.provider is not None:
            config.provider = args.provider
        if args.model is not None:
            config.model = args.model
        if args.preset:
            config.apply_preset(args.preset)
        if args.seeds:
            config.seeds = args.seeds
        if args.seasons is not None:
            config.seasons = args.seasons
        if args.repeats is not None:
            config.repeats = args.repeats
        if args.baselines:
            config.baselines = args.baselines
        if args.agent_timeout is not None:
            config.agent_timeout = args.agent_timeout
        if args.profile:
            config.profile = args.profile
        config.verbose = config.verbose or args.verbose
        config.json_output = config.json_output or args.json
        config.no_log = config.no_log or args.no_log
        if args.db is not None:
            config.db = args.db
        config.use_baseline_cache = config.use_baseline_cache and not args.no_baseline_cache
    else:
        config = BenchmarkConfig(
            provider=args.provider,
            model=args.model,
            agent_timeout=args.agent_timeout,
            profile=args.profile,
            seeds=args.seeds or [1, 2, 3, 4, 5],
            seasons=args.seasons if args.seasons is not None else 5,
            repeats=args.repeats if args.repeats is not None else 1,
            baselines=args.baselines or ["random", "conservative", "win-now", "rebuild"],
            verbose=args.verbose,
            json_output=args.json,
            no_log=args.no_log,
            db=args.db,
            use_baseline_cache=not args.no_baseline_cache,
        )
        if args.preset:
            config.apply_preset(args.preset)
        # CLI flags must win over preset defaults (same as the --config path).
        # Without this, `--preset leaderboard --seeds 12 13 …` silently re-runs
        # the full public panel and destroys resume/partial-panel workflows.
        if args.seeds is not None:
            config.seeds = args.seeds
        if args.seasons is not None:
            config.seasons = args.seasons
        if args.repeats is not None:
            config.repeats = args.repeats
        if args.baselines is not None:
            config.baselines = args.baselines
        if args.agent_timeout is not None:
            config.agent_timeout = args.agent_timeout
        if args.profile is not None:
            config.profile = args.profile
    config.validate()
    resolved_output = args.output or (
        Path(str(execution_options["output"])) if execution_options.get("output") else None
    )
    resolved_workers = args.workers
    if resolved_workers is None and execution_options.get("workers") is not None:
        resolved_workers = int(execution_options["workers"])
    if resolved_workers is not None and resolved_workers < 1:
        sys.exit("gm-bench model: workers must be >= 1")
    require_clean = args.require_clean or bool(execution_options.get("require_clean", False))
    if not config.provider:
        sys.exit('gm-bench model: no provider specified; pass --provider or set "provider" in the config file')
    try:
        preflight_provider(config.provider)
    except ModelRunAborted as exc:
        sys.exit(f"gm-bench model: {exc}")
    if args.preflight_only:
        print(f"provider preflight ok: {config.provider}")
        return
    agent = build_provider_agent(
        config.provider,
        model=config.model,
        timeout=config.agent_timeout,
        profile=config.profile,
        extra_env=config.extra_env,
        session=bool(getattr(args, "session", False)),
    )
    route_errors = _openrouter_route_config_errors(agent, config.preset)
    if route_errors:
        sys.exit("gm-bench model: invalid canonical OpenRouter route: " + "; ".join(route_errors))
    progress = make_progress_printer(config.verbose)
    workers = _model_worker_count(agent, resolved_workers)
    checkpoint = args.checkpoint or default_checkpoint_path(agent.name)
    if config.provider == "claude" and workers is not None and workers > 1:
        sys.exit("gm-bench model: Claude must run serially with --workers 1")
    if bool(getattr(args, "session", False)) or (workers is not None and workers > 1):
        if args.resume or args.resume_from or args.checkpoint:
            sys.exit("gm-bench model: checkpoints require fresh-spawn serial execution")
        with _model_worker_environment(workers):
            result = evaluate_against_baselines(
                agent,
                config.seeds,
                config.seasons,
                config.baselines,
                repeats=config.repeats,
                use_baseline_cache=config.use_baseline_cache,
                progress=progress,
            )
    else:
        try:
            with _model_worker_environment(1):
                candidate = run_resumable_candidate(
                    agent,
                    config.seeds,
                    config.seasons,
                    config.repeats,
                    checkpoint_path=checkpoint,
                    resume_sources=args.resume_from,
                    resume_checkpoint=args.resume,
                    fail_fast=args.fail_fast,
                    progress=progress,
                )
            result = evaluate_resumable_candidate(
                candidate,
                config.baselines,
                use_baseline_cache=config.use_baseline_cache,
            )
        except ModelRunAborted as exc:
            sys.exit(f"gm-bench model: {exc}\ncheckpoint: {checkpoint}")
    result["run_info"] = _run_info("model", agent, config)
    resolved_db = config.db or str(DEFAULT_DB_PATH)
    run_id = None if config.no_log else log_payload("model", result, resolved_db)
    if resolved_output:
        _write_json_atomic(resolved_output, result)
    if config.json_output:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        _print_evaluation(result)
    if run_id:
        line = f"logged_run_id={run_id} db={resolved_db}"
        print(line, file=sys.stderr if config.json_output else sys.stdout)
    clean_errors = _model_clean_errors(result) if require_clean or config.preset == "smoke" else []
    if clean_errors:
        sys.exit("gm-bench model: clean-run requirements failed: " + "; ".join(clean_errors))


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
    print("provider       transport       auth     model_env         default_model")
    print("------------------------------------------------------------------------")
    for row in payload:
        auth = "ready" if row["credential_present"] else ("missing" if row["credential_env"] else "n/a")
        print(f"{row['provider']:<14}{row['transport']:<16}{auth:<9}{row['model_env']:<18}{row['default_model']}")


def _validate_result_command(args: argparse.Namespace) -> None:
    try:
        with open(args.path) as handle:
            payload = json.load(handle)
    except OSError as exc:
        sys.exit(f"gm-bench validate-result: cannot read {args.path}: {exc}")
    except json.JSONDecodeError as exc:
        sys.exit(f"gm-bench validate-result: invalid JSON in {args.path}: {exc}")
    if not isinstance(payload, dict):
        sys.exit("gm-bench validate-result: result JSON must be an object")

    report = validate_leaderboard_payload(payload, policy=POLICIES[args.policy])
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        status = "ok" if report.ok else "invalid"
        print(f"{status}: policy={report.policy} path={args.path}")
        for error in report.errors:
            print(f"error: {error}")
        for warning in report.warnings:
            print(f"warning: {warning}")
    if not report.ok:
        sys.exit(1)


def _redact_result_command(args: argparse.Namespace) -> None:
    try:
        with open(args.path) as handle:
            payload = json.load(handle)
    except OSError as exc:
        sys.exit(f"gm-bench redact-result: cannot read {args.path}: {exc}")
    except json.JSONDecodeError as exc:
        sys.exit(f"gm-bench redact-result: invalid JSON in {args.path}: {exc}")
    if not isinstance(payload, dict):
        sys.exit("gm-bench redact-result: result JSON must be an object")

    redacted, report = redact_leaderboard_payload(payload, policy=POLICIES[args.policy])
    for error in report.errors:
        print(f"error: {error}")
    for warning in report.warnings:
        print(f"warning: {warning}")
    if not report.ok:
        print(f"invalid: policy={report.policy}; not writing {args.output}")
        sys.exit(1)
    with open(args.output, "w") as handle:
        json.dump(redacted, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(f"ok: policy={report.policy} wrote {args.output}")


def _validate_contract_command(args: argparse.Namespace) -> None:
    result = run_validity_canaries(seeds=args.seeds, seasons=args.seasons)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        status = "ok" if result["ok"] else "invalid"
        print(f"{status}: validity canaries seeds={result['seeds']} seasons={result['seasons']}")
        print("honest baselines:")
        for row in result["baselines"]:
            print(_validity_row(row))
        if result.get("mechanic_coverage"):
            print("mechanic coverage:")
            for row in result["mechanic_coverage"]:
                status = "ok" if row["seed_count"] >= row["minimum_seed_count"] else "error"
                print(
                    f"  {status}: {row['mechanic']} accepted={row['accepted_actions']} "
                    f"seeds={row['seed_count']} min={row['minimum_seed_count']}"
                )
        print("canaries:")
        for row in result["canaries"]:
            print(_validity_row(row))
        for check in result["checks"]:
            if check.get("name") == "mechanic_coverage":
                continue
            prefix = "ok" if check["ok"] else "error"
            print(
                f"{prefix}: {check['winner']} over {check['loser']} "
                f"{check['metric']} margin={check['margin']} min={check['minimum_margin']}"
            )
    if not result["ok"]:
        sys.exit(1)


def _calibrate_score_command(args: argparse.Namespace) -> None:
    result = build_scoring_calibration(seeds=args.seeds, seasons=args.seasons)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    scale = result["scoring_scale"]
    panel = result["panel"]
    print(
        f"scoring scale: {scale['version']} fingerprint={scale['fingerprint']} "
        f"seeds={panel['seeds']} seasons={panel['seasons']}"
    )
    print("marginal values:")
    for row in result["marginal_values"]:
        print(f"  {row['scenario']}: {row['score_delta']:+.3f}")
    print("reference policies:")
    for row in result["policies"]:
        print(
            f"  {row['agent']}: mean={row['mean_score']} "
            f"delta_vs_strategic={row['delta_vs_strategic']:+.3f} "
            f"illegal={row['illegal_actions']}"
        )


def _validity_row(row: dict[str, Any]) -> str:
    return (
        f"  {row['agent']}: mean={row['mean_score']} strategy={row['mean_strategy_score']} "
        f"penalty={row['protocol_penalty']} illegal={row['illegal_actions']} "
        f"rejected={row['rejected_offers']} wins={row['mean_total_wins']}"
    )


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
        repeats=int(getattr(args, "repeats", 1)),
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
        return ExternalProcessAgent(
            config.agent_cmd,
            timeout_seconds=resolved_timeout,
            env={"GM_BENCH_AGENT_TIMEOUT": str(resolved_timeout)},
        )
    return CLI_AGENTS[config.agent]()


def _add_logging_args(parser: argparse.ArgumentParser, *, db_default: str | None = str(DEFAULT_DB_PATH)) -> None:
    parser.add_argument(
        "--db",
        default=os.environ.get("GM_BENCH_DB", db_default),
        help="SQLite database path for automatic run logging",
    )
    parser.add_argument("--no-log", action="store_true", help="disable automatic SQLite run logging")


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Durably replace a result artifact without exposing a partial JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            temporary_name = handle.name
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)


def _load_model_execution_options(path: Path) -> dict[str, Any]:
    """Read harness-only config without changing the frozen score contract."""
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        return {}
    return {key: payload[key] for key in ("output", "workers", "require_clean") if key in payload}


def _model_clean_errors(result: dict[str, Any]) -> list[str]:
    """Return actionable reasons a paid/model smoke is not execution-clean."""
    if not isinstance(result.get("candidate"), dict):
        return []
    summary = (result.get("candidate") or {}).get("summary") or {}
    usage = summary.get("usage") or {}
    decisions = int(summary.get("decisions", 0) or 0)
    errors: list[str] = []
    if int(summary.get("failed_decisions", 0) or 0):
        errors.append(f"failed_decisions={summary.get('failed_decisions')}")
    if int(usage.get("decisions_with_usage", 0) or 0) != decisions:
        errors.append(f"usage_coverage={usage.get('decisions_with_usage', 0)}/{decisions}")
    if int(usage.get("cost_decisions", 0) or 0) != decisions:
        errors.append(f"cost_coverage={usage.get('cost_decisions', 0)}/{decisions}")
    for key in ("model", "provider"):
        if not usage.get(key):
            errors.append(f"missing_usage_{key}")
    run_info = result.get("run_info") or {}
    if run_info.get("provider") == "openrouter" and len(usage.get("upstream_providers") or []) != 1:
        errors.append("OpenRouter requires exactly one observed upstream provider")
    if run_info.get("provider") == "openrouter":
        requested = str((run_info.get("provider_options") or {}).get("OPENROUTER_PROVIDER_ONLY", "")).strip()
        observed = [str(value) for value in usage.get("upstream_providers") or []]
        if requested and len(observed) == 1 and observed[0].casefold() != requested.casefold():
            errors.append(f"OpenRouter upstream mismatch: requested {requested!r}, observed {observed[0]!r}")
    return errors


def _openrouter_route_config_errors(agent: Any, preset: str | None) -> list[str]:
    """Reject non-canonical leaderboard routing before it can spend money."""
    metadata = getattr(agent, "metadata", None) or {}
    if metadata.get("provider") != "openrouter" or preset != "leaderboard":
        return []
    options = metadata.get("provider_options") or {}
    only = [value.strip() for value in str(options.get("OPENROUTER_PROVIDER_ONLY", "")).split(",") if value.strip()]
    errors: list[str] = []
    if len(only) != 1:
        errors.append("OPENROUTER_PROVIDER_ONLY must name exactly one upstream provider")
    if str(options.get("OPENROUTER_ALLOW_FALLBACKS", "")).casefold() not in {"false", "0", "no", "off"}:
        errors.append("OPENROUTER_ALLOW_FALLBACKS must be false")
    return errors


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
        "mean_score={mean_score} strategy={mean_strategy_score} protocol_penalty={total_protocol_penalty} "
        "score_stddev={score_stddev} within_seed_stddev={within_seed_score_stddev} "
        "mean_total_wins={mean_total_wins} championships={championships} illegal_actions={illegal_actions} "
        "rejected_offers={rejected_offers}".format(**summary)
    )
    print(_reliability_line(result))
    usage_line = _format_usage_line(summary)
    if usage_line:
        print(usage_line)


def _reliability_line(result: dict[str, Any]) -> str:
    summary = result["summary"]
    latencies = [
        episode["mean_decision_seconds"] for episode in result["episodes"] if "mean_decision_seconds" in episode
    ]
    line = (
        f"decisions={summary.get('decisions', 0)} failed_decisions={summary.get('failed_decisions', 0)} "
        f"(rate {summary.get('decision_failure_rate', 0.0)}) memo_writes={summary.get('memo_writes', 0)}"
    )
    if latencies:
        line += f" mean_decision_seconds={round(sum(latencies) / len(latencies), 3)}"
    return line


def _format_usage_line(summary: dict[str, Any]) -> str | None:
    usage = summary.get("usage") or {}
    if not usage.get("decisions_with_usage"):
        return None
    cost = usage.get("cost_usd")
    cost_text = f"${cost:.4f}" if cost is not None else "unknown"
    api_seconds = usage.get("api_latency_ms", 0.0) / 1000.0
    harness_seconds = usage.get("harness_latency_ms", 0.0) / 1000.0
    model = usage.get("model") or "?"
    return (
        f"usage: model={model} tokens={usage.get('total_tokens', 0)} "
        f"(in={usage.get('input_tokens', 0)} out={usage.get('output_tokens', 0)}) "
        f"cost={cost_text} api_time={api_seconds:.1f}s harness_time={harness_seconds:.1f}s "
        f"decisions_with_usage={usage.get('decisions_with_usage', 0)}"
    )


def _print_table(results: list[dict[str, Any]]) -> None:
    name_width = max(14, *(len(result["agent"]) + 2 for result in results))
    print(f"{'agent':<{name_width}}mean_score  stddev  mean_wins  titles  illegal  fallback")
    print("-" * (name_width + 59))
    for result in sorted(results, key=lambda item: item["summary"]["mean_score"], reverse=True):
        summary = result["summary"]
        fallback = f"{summary.get('failed_decisions', 0)}/{summary.get('decisions', 0)}"
        print(
            f"{result['agent']:<{name_width}}{summary['mean_score']:>10.2f}{summary['score_stddev']:>8.2f}{summary['mean_total_wins']:>11.2f}{summary['championships']:>8}{summary['illegal_actions']:>9}{fallback:>10}"
        )


def _print_evaluation(result: dict[str, Any]) -> None:
    normalized = result["normalized"]
    print(f"agent={result['agent']} seasons={result['seasons']} seeds={result['seeds']}")
    print(
        "candidate_mean={candidate_mean_score} strategy={candidate_mean_strategy_score} protocol_penalty={candidate_protocol_penalty} baseline_panel_mean={baseline_panel_mean_score} lift={score_lift} lift_pct={score_lift_pct}% illegal={candidate_illegal_actions} rejected_offers={candidate_rejected_offers}".format(
            **normalized
        )
    )
    print(_reliability_line(result["candidate"]))
    if result["candidate"]["summary"].get("failed_decisions"):
        print(
            "warning: some decisions used adapter fallback/error output instead of the model's own actions; "
            "the score partially reflects the fallback policy, not the model",
            file=sys.stderr,
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
        p_value = paired.get("sign_flip_p_value")
        p_text = f" sign_flip_p={p_value}" if p_value is not None else ""
        print(
            f"paired_lift={paired['paired_lift_mean']} ci95=[{low}, {high}] ({verdict}){p_text} "
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
    usage_line = _format_usage_line(result["candidate"]["summary"])
    if usage_line:
        print(usage_line)
    cache = result.get("baseline_cache")
    if cache and cache.get("enabled"):
        print(f"baseline_cache_hits={cache['hits']}/{cache['total']} path={cache['path']}")
    print()
    _print_table([result["candidate"], *result["baselines"]])


if __name__ == "__main__":
    main()
