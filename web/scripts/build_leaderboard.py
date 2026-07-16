"""Build the public leaderboard dataset for the GM-Bench site.

Reads official ``results/leaderboard/*.json`` artifacts -- and *only* those. An
artifact's provenance is the directory it lives in, never a field inside it, so
neither ``results/diagnostics/`` nor the ``archive-v1/`` forensic set can reach
the published table. Official artifacts are either the saved output of

    python -m gm_bench model --provider <p> --model <m> --preset leaderboard --repeats 3 --json > results/leaderboard/<name>.json

or a redacted private-panel artifact from ``python -m gm_bench redact-result``.
Only rows on the current ``sota-v2`` contract are published; anything else is
skipped with a note on stderr.

It writes ``web/src/data/leaderboard.json`` with one row per model plus the
scripted-baseline reference panel. When no model results exist yet, the baseline
panel is read from the current-contract cache or recomputed deterministically so
the site never mixes historical model rows with stale reference scores.

Usage (from the repository root):

    python web/scripts/build_leaderboard.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from gm_bench.agents import AGENTS  # noqa: E402
from gm_bench.baseline_cache import cache_key, load_cache  # noqa: E402
from gm_bench.benchmark_config import PRESETS, PRIVATE_LEADERBOARD_PANEL_NAME  # noqa: E402
from gm_bench.official import REDACTED_SEEDS_SENTINEL, SOTA_V2_POLICY, validate_leaderboard_payload  # noqa: E402
from gm_bench.oracle import OracleAgent  # noqa: E402
from gm_bench.protocol import PHASES  # noqa: E402
from gm_bench.publication import mechanic_breakdown, smoke_manifest_issues  # noqa: E402
from gm_bench.runner import run_many  # noqa: E402

RESULTS_DIR = ROOT / "results" / "leaderboard"
OUTPUT_PATH = ROOT / "web" / "src" / "data" / "leaderboard.json"
MODEL_CONFIG_PATH = ROOT / "config" / "sota_v2_models.json"
PROTOCOL_CONFIG_PATH = ROOT / "config" / "publication_protocol.json"
LEADERBOARD = PRESETS["leaderboard"]
# Providers that run a model through a coding-agent CLI harness (own tool loop,
# own prompt scaffold, own retry/session behavior) rather than a direct API
# call. Score and cost are not comparable across lanes even for the same
# underlying model, so the lane must travel with every published row. This is
# a fallback for external `--agent-cmd` rows with no `run_info.transport`;
# built-in providers should always carry a transport (see gm_bench/providers.py).
CLI_HARNESS_PROVIDERS = {"codex", "claude", "cursor", "opencode"}


def _lane(provider: str, transport: str | None) -> str:
    if transport:
        return "cli-harness" if transport == "coding-harness" else "api"
    return "cli-harness" if provider in CLI_HARNESS_PROVIDERS else "api"


def _output_token_cap(run_info: dict[str, Any]) -> int | None:
    options = run_info.get("provider_options") or {}
    budget_cell = options.get("GM_BENCH_OUTPUT_BUDGET_CELL")
    if budget_cell not in (None, ""):
        if budget_cell == "uncapped":
            return None
        try:
            return int(budget_cell)
        except (TypeError, ValueError):
            return None
    names = (
        "OPENAI_MAX_TOKENS",
        "ANTHROPIC_MAX_TOKENS",
        "GEMINI_MAX_OUTPUT_TOKENS",
        "OPENROUTER_MAX_TOKENS",
    )
    values = [options[name] for name in names if options.get(name) not in (None, "")]
    if len(values) != 1:
        return None
    try:
        return int(values[0])
    except (TypeError, ValueError):
        return None


def _publication_identity_issues(payload: dict[str, Any], config: dict[str, Any]) -> list[str]:
    run_info = payload.get("run_info") or {}
    summary = (payload.get("candidate") or {}).get("summary") or {}
    usage = summary.get("usage") or {}
    provider = str(run_info.get("provider") or "")
    model = str(run_info.get("model") or "")
    registered = next(
        (
            spec
            for spec in config.get("models") or []
            if spec.get("provider") == provider and spec.get("model") == model
        ),
        None,
    )
    if registered is None:
        return [f"provider/model is not pre-registered in {MODEL_CONFIG_PATH.relative_to(ROOT)}"]
    issues: list[str] = []
    if run_info.get("transport") != registered.get("transport"):
        issues.append("transport does not match the pre-registered model lane")
    if run_info.get("profile") != config.get("profile"):
        issues.append("observation profile does not match the pre-registered model lane")
    if bool(run_info.get("session")) != bool(config.get("session")):
        issues.append("session condition does not match the pre-registered model lane")
    options = run_info.get("provider_options") or {}
    expected_options = {
        **(config.get("shared_fixed_options") or {}),
    }
    if registered.get("upstream_provider") not in (None, ""):
        expected_options["OPENROUTER_PROVIDER_ONLY"] = registered["upstream_provider"]
    if registered.get("endpoint_name") not in (None, ""):
        expected_options["OPENROUTER_EXPECTED_ENDPOINT_NAME"] = registered["endpoint_name"]
    for key, expected in expected_options.items():
        if str(options.get(key, "")) != str(expected):
            issues.append(f"provider option {key} does not match the pre-registered value")
    for key in config.get("shared_absent_options") or []:
        if options.get(str(key)) not in (None, ""):
            issues.append(f"provider option {key} must be absent for the headline lane")
    observed = sorted({str(value) for value in usage.get("upstream_providers") or [] if value})
    expected_upstream = str(registered.get("upstream_provider") or "")
    if expected_upstream and [value.casefold() for value in observed] != [expected_upstream.casefold()]:
        issues.append("observed upstream provider does not match the pre-registered route")
    decisions = int(summary.get("decisions") or 0)
    if usage.get("cost_usd") is None:
        issues.append("API headline rows require numeric cost telemetry")
    if int(usage.get("cost_decisions") or 0) != decisions:
        issues.append("cost telemetry must cover every decision")
    return issues


def model_row(payload: dict[str, Any], publication_config: dict[str, Any] | None = None) -> dict[str, Any]:
    summary = payload["candidate"]["summary"]
    usage = summary.get("usage") or {}
    paired = payload.get("paired") or {}
    normalized = payload.get("normalized") or {}
    run_info = payload.get("run_info") or {}
    contract = run_info.get("benchmark_contract") or {}
    seed_panel = run_info.get("seed_panel") or {}
    sota_report = _sota_report(payload)
    publication_issues = _publication_identity_issues(payload, publication_config) if publication_config else []
    decisions = summary.get("decisions", 0)
    agent = payload.get("agent", "unknown")
    provider, _, model_name = agent.partition(":")
    if not model_name:
        provider, model_name = usage.get("provider") or "unknown", agent
    episodes = len(payload["candidate"].get("episodes", [])) or _redacted_episode_count(payload)
    cost = usage.get("cost_usd")
    seeds = payload.get("seeds")
    if seeds == REDACTED_SEEDS_SENTINEL:
        seeds = None
    elif seed_panel.get("name") == PRIVATE_LEADERBOARD_PANEL_NAME:
        seeds = None
    return {
        "id": agent,
        "model": model_name,
        "provider": provider,
        "lane": _lane(provider, run_info.get("transport")),
        "output_token_cap": _output_token_cap(run_info),
        "mean_score": summary["mean_score"],
        "score_stddev": summary["score_stddev"],
        "mean_strategy_score": summary.get("mean_strategy_score"),
        "protocol_penalty": summary.get("total_protocol_penalty"),
        "paired_lift": paired.get("paired_lift_mean"),
        "ci95": paired.get("paired_lift_ci95"),
        "significant": paired.get("significant_at_95"),
        "seed_win_rate": paired.get("candidate_seed_win_rate"),
        "lift_vs_best_baseline": (paired.get("best_baseline") or {}).get("paired_lift_mean"),
        "fallback_rate": summary.get("decision_failure_rate", 0.0),
        "illegal_actions": summary.get("illegal_actions", 0),
        "total_tokens": usage.get("total_tokens", 0),
        "tokens_per_decision": round(usage.get("total_tokens", 0) / decisions, 1) if decisions else None,
        "input_tokens_per_decision": round(usage.get("input_tokens", 0) / decisions, 1) if decisions else None,
        "output_tokens_per_decision": round(usage.get("output_tokens", 0) / decisions, 1) if decisions else None,
        "protocol_repair_attempts": usage.get("protocol_repair_attempts", 0),
        "protocol_repairs_succeeded": usage.get("protocol_repairs_succeeded", 0),
        "mechanic_breakdown": (payload.get("publication") or {}).get("mechanic_breakdown")
        or mechanic_breakdown((payload.get("candidate") or {}).get("episodes", [])),
        "failed_queries": summary.get("failed_queries", 0),
        "cost_usd": cost,
        "cost_per_episode_usd": round(cost / episodes, 4) if cost is not None and episodes else None,
        "api_latency_s_per_decision": round(usage.get("api_latency_ms", 0.0) / 1000.0 / decisions, 2)
        if decisions
        else None,
        "harness_latency_s_per_decision": round(usage.get("harness_latency_ms", 0.0) / 1000.0 / decisions, 2)
        if decisions
        else None,
        "decisions_with_usage": usage.get("decisions_with_usage", 0),
        "decision_points": decisions,
        "session": bool(run_info.get("session", False)),
        "seeds": seeds,
        "seasons": payload.get("seasons"),
        "baseline_panel_mean_score": normalized.get("baseline_panel_mean_score"),
        "benchmark_version": contract.get("benchmark_version"),
        "contract_fingerprint": contract.get("contract_fingerprint"),
        "seed_panel": seed_panel.get("name"),
        "seed_panel_hash": seed_panel.get("sha256"),
        "sota_v2_eligible": bool(sota_report.get("ok")),
        "sota_v2_issues": [*sota_report.get("errors", []), *sota_report.get("warnings", [])],
        "publication_eligible": bool(sota_report.get("ok")) and not publication_issues,
        "publication_issues": publication_issues,
    }


def _sota_report(payload: dict[str, Any]) -> dict[str, Any]:
    """Always recompute eligibility; never trust embedded validation_reports."""

    return validate_leaderboard_payload(payload, policy=SOTA_V2_POLICY).to_dict()


def _redacted_episode_count(payload: dict[str, Any]) -> int:
    seed_panel = (payload.get("run_info") or {}).get("seed_panel") or {}
    candidate = payload.get("candidate") or {}
    count = seed_panel.get("count")
    repeats = candidate.get("repeats", 1)
    if isinstance(count, int):
        return count * int(repeats or 1)
    return 0


def baselines_from_cache() -> list[dict[str, Any]]:
    """Load baseline rows that have complete seed coverage in the cache.

    Partial cache hits are ignored so ``current_baselines()`` recomputes rather
    than publishing a mean over a subset of seeds.
    """
    cache = load_cache()
    rows = []
    seeds = list(LEADERBOARD["seeds"])
    for agent in LEADERBOARD["baselines"]:
        scores = []
        for seed in seeds:
            episode = cache.get(cache_key(agent, seed, LEADERBOARD["seasons"]))
            if episode is None:
                scores = []
                break
            scores.append(episode["final_score"])
        if len(scores) != len(seeds):
            continue
        mean = sum(scores) / len(scores)
        stddev = (sum((score - mean) ** 2 for score in scores) / len(scores)) ** 0.5
        rows.append({"agent": agent, "mean_score": round(mean, 3), "score_stddev": round(stddev, 3)})
    return sorted(rows, key=lambda row: row["mean_score"], reverse=True)


def current_baselines() -> list[dict[str, Any]]:
    rows = baselines_from_cache()
    cached_agents = {row["agent"] for row in rows}
    for agent_name in LEADERBOARD["baselines"]:
        if agent_name in cached_agents:
            continue
        result = run_many(
            AGENTS[agent_name](),
            seeds=list(LEADERBOARD["seeds"]),
            seasons=int(LEADERBOARD["seasons"]),
            workers=1,
        )
        rows.append(
            {
                "agent": agent_name,
                "mean_score": result["summary"]["mean_score"],
                "score_stddev": result["summary"]["score_stddev"],
            }
        )
    return sorted(rows, key=lambda row: row["mean_score"], reverse=True)


def select_model_payloads(
    artifacts: list[tuple[dict[str, Any], int, str]],
) -> list[dict[str, Any]]:
    """Choose one row per agent and contract, preferring canonical artifacts."""
    selected: dict[tuple[str, str], tuple[tuple[int, str, str], dict[str, Any]]] = {}
    for payload, source_priority, filename in artifacts:
        agent = str(payload.get("agent") or "")
        if not agent:
            continue
        contract = (payload.get("run_info") or {}).get("benchmark_contract") or {}
        benchmark_version = str(contract.get("benchmark_version") or "unknown")
        timestamp = str((payload.get("run_info") or {}).get("timestamp_utc") or "")
        priority = (int(source_priority), timestamp, filename)
        key = (agent, benchmark_version)
        current = selected.get(key)
        if current is None or priority > current[0]:
            selected[key] = (priority, payload)
    return [item[1] for item in selected.values()]


def _headline_identity(row: dict[str, Any]) -> Any:
    provider = row.get("provider")
    model = row.get("model")
    if provider and model:
        return (provider, model)
    return row.get("id")


def publication_gate(
    rows: list[dict[str, Any]],
    analysis: dict[str, Any],
    lane_config: dict[str, Any],
    model_config: dict[str, Any],
    *,
    smoke_issues: list[str] | None = None,
    protocol_minimum: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return only publishable rows plus an explicit gate report."""

    frozen_statuses = {"frozen-saturation", "frozen-fixed-budget"}
    frozen_cap = lane_config.get("output_token_cap")
    policy_basis = lane_config.get("output_policy_basis")
    fixed_safety_ceiling = policy_basis == "fixed-safety-ceiling"
    registry_frozen = model_config.get("selection_status") == "frozen"
    lane_frozen = (
        (fixed_safety_ceiling or analysis.get("status") == "complete-needs-interpretation")
        and lane_config.get("output_budget_status") in frozen_statuses
        and isinstance(frozen_cap, int)
        and frozen_cap > 0
    )
    candidates = [
        row
        for row in rows
        if row.get("lane") == "api" and row.get("publication_eligible") and row.get("output_token_cap") == frozen_cap
    ]
    identities = {_headline_identity(row) for row in candidates}
    unique_models = len(identities)
    duplicate_headline_rows = len(candidates) - unique_models
    minimum_models = max(int(lane_config.get("minimum_headline_models") or 0), protocol_minimum or 0)
    smoke_ok = smoke_issues is None or smoke_issues == []
    publishable = (
        lane_frozen
        and registry_frozen
        and smoke_ok
        and duplicate_headline_rows == 0
        and unique_models >= minimum_models
    )
    if smoke_issues is None:
        smoke_gate_issues: list[str] | None = None
    else:
        smoke_gate_issues = list(smoke_issues[:10])
    publication = {
        **analysis,
        "publishable_ranking": publishable,
        "frozen_output_token_cap": frozen_cap if lane_frozen else None,
        "output_policy_basis": policy_basis,
        "model_registry_frozen": registry_frozen,
        "eligible_headline_models": unique_models,
        "duplicate_headline_rows": duplicate_headline_rows,
        "minimum_headline_models": minimum_models,
        "smoke_gate_issues": smoke_gate_issues,
    }
    if not registry_frozen:
        publication["reason"] = "model registry remains provisional until every registered route passes its smoke"
    elif smoke_issues:
        publication["reason"] = f"pre-panel smoke evidence is incomplete: {smoke_issues[0]}"
    elif lane_frozen and duplicate_headline_rows > 0:
        publication["reason"] = (
            "frozen lane has duplicate eligible rows for one registered model; "
            f"{duplicate_headline_rows} duplicate row(s) among {len(candidates)} candidates"
        )
    elif lane_frozen and not publishable:
        publication["reason"] = (
            f"frozen lane has {unique_models} eligible headline models; at least {minimum_models} are required"
        )
    elif not publishable and analysis.get("status") == "complete-needs-interpretation":
        publication["reason"] = "sweep complete; inspect curves and freeze a fixed API-lane cap before ranking"
    return (candidates if publishable else []), publication


def main() -> None:
    # Published rows come from RESULTS_DIR only. Provenance is the directory an
    # artifact lives in, never a field inside it: selecting on benchmark_version
    # alone would promote a *diagnostic* sota-v2 run into the official table
    # without it ever clearing the official gate.
    artifacts: list[tuple[dict[str, Any], int, str]] = []
    if RESULTS_DIR.exists():
        for path in sorted(RESULTS_DIR.glob("*.json")):
            try:
                artifacts.append((json.loads(path.read_text()), 2, path.name))
            except json.JSONDecodeError:
                print(f"skipping unparseable {path}", file=sys.stderr)
    payloads = select_model_payloads(artifacts)
    model_config = json.loads(MODEL_CONFIG_PATH.read_text())
    rows = sorted(
        (model_row(payload, model_config) for payload in payloads),
        key=lambda row: row["mean_score"],
        reverse=True,
    )
    # The sota-v1 rows in ARCHIVE_DIR are retained as forensic evidence of the v1
    # scout-contract break, not as a ranking: the defect cost some candidates over
    # a thousand silently-rejected lookups and others none, so their scores are not
    # comparable to each other. See results/leaderboard/archive-v1/README.md.
    current_rows = [row for row in rows if row.get("benchmark_version") == "sota-v2"]
    analysis = json.loads((ROOT / "results" / "analysis" / "output-budget-sweep.json").read_text())
    lane_config = json.loads((ROOT / "config" / "sota_v2_lane.json").read_text())
    protocol = json.loads(PROTOCOL_CONFIG_PATH.read_text())
    protocol_minimum = int((protocol.get("exclusion_policy") or {}).get("minimum_headline_models") or 0)
    manifest_rel = str(lane_config.get("smoke_manifest") or "config/sota_v2_smoke_manifest.json")
    manifest_path = ROOT / manifest_rel
    manifest: dict[str, Any] | None = None
    if manifest_path.is_file():
        try:
            loaded = json.loads(manifest_path.read_text())
        except json.JSONDecodeError:
            loaded = None
        if isinstance(loaded, dict):
            manifest = loaded
    smoke_issues = smoke_manifest_issues(manifest, model_config, lane_config)
    models, publication = publication_gate(
        current_rows,
        analysis,
        lane_config,
        model_config,
        smoke_issues=smoke_issues,
        protocol_minimum=protocol_minimum,
    )
    publishable_ranking = bool(publication["publishable_ranking"])
    cli_harness_models = [row for row in current_rows if row.get("lane") == "cli-harness"]
    excluded_models = [
        {
            "id": row.get("id"),
            "issues": list(row.get("publication_issues") or []) + list(row.get("sota_v2_issues") or []),
        }
        for row in current_rows
        if row.get("lane") == "api" and not row.get("publication_eligible")
    ]
    skipped = [row for row in rows if row.get("benchmark_version") != "sota-v2"]
    for row in skipped:
        print(
            f"skipping {row.get('model')}: benchmark_version={row.get('benchmark_version')!r} is not sota-v2",
            file=sys.stderr,
        )
    baselines = current_baselines()
    oracle = run_many(OracleAgent(), seeds=list(LEADERBOARD["seeds"]), seasons=int(LEADERBOARD["seasons"]), workers=1)
    baseline_by_name = {row["agent"]: row["mean_score"] for row in baselines}
    headroom = {
        "oracle": oracle["summary"]["mean_score"],
        "pick_trader": baseline_by_name.get("pick-trader"),
        "best_model": max((row["mean_score"] for row in models), default=None) if publishable_ranking else None,
        "random": baseline_by_name.get("random"),
    }
    # Derived from the artifacts, never from the wall clock: the committed
    # leaderboard.json must be a pure function of the committed inputs, or the
    # CI reproducibility gate would go red every time the date rolls over. It is
    # also the more honest field -- the data was last updated when a run landed,
    # not when someone happened to rebuild the site.
    timestamps = [str((payload.get("run_info") or {}).get("timestamp_utc") or "") for payload in payloads]
    updated = max((stamp for stamp in timestamps if stamp), default="")[:10]
    dataset = {
        "updated": updated,
        "preset": {
            "name": "leaderboard",
            "seeds": LEADERBOARD["seeds"],
            "seasons": LEADERBOARD["seasons"],
            "decision_points_per_episode": LEADERBOARD["seasons"] * len(PHASES),
        },
        "baselines": baselines,
        "models": models,
        "cli_harness_models": cli_harness_models,
        "excluded_models": excluded_models,
        "publication": publication,
        "headroom": headroom,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(dataset, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUTPUT_PATH} ({len(models)} current model(s), {len(baselines)} baseline(s))")


if __name__ == "__main__":
    main()
