"""Zero-spend end-to-end rehearsal for the future sota-v3 evidence lane.

The rehearsal creates deterministic synthetic raw and compact artifacts in a
temporary directory, validates them under the live sota-v3 policy, proves
selected mutations fail closed, and runs the public leaderboard builder in an
isolated repository copy.  No model/provider is invoked and no file under
``results/leaderboard`` is written.

Run from the repository root:

    python3 scripts/sota_v3_rehearsal.py

Pass ``--skip-web-build`` when Bun is unavailable.  The Python site-data
builder still runs and must reproduce the checked-in frozen sota-v2 dataset.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import io
import json
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gm_bench.benchmark_config import PRESETS, seed_panel_metadata  # noqa: E402
from gm_bench.contract import SOTA_V2_CONTRACT, SOTA_V3_CONTRACT  # noqa: E402
from gm_bench.official import (  # noqa: E402
    POLICIES,
    SOTA_V2_POLICY,
    SOTA_V3_POLICY,
    validate_leaderboard_payload,
)
from gm_bench.protocol import MAX_INTERACTION_ROUNDS  # noqa: E402
from gm_bench.publication import (  # noqa: E402
    canonical_sha256,
    compact_result,
    publication_execution_issues,
    raw_artifact_link_issues,
    v3_preregistration_coherence_issues,
)
from gm_bench.runner import _paired_analysis, _precise_mean_score, summarize_episodes  # noqa: E402
from gm_bench.scoring import ACTIVE_SCORE_SCALE, SCORE_COMPONENT_KEYS  # noqa: E402
from scripts.analyze_publication_panel import analyze  # noqa: E402
from web.scripts import build_leaderboard  # noqa: E402


def _score_components(strategy_score: float) -> dict[str, float]:
    components = {name: 0.0 for name in SCORE_COMPONENT_KEYS}
    components["recent_wins"] = round(strategy_score / ACTIVE_SCORE_SCALE.recent_win, 6)
    components["recent_wins_contribution"] = strategy_score
    return components


def synthetic_raw_artifact() -> dict[str, Any]:
    """Build deterministic, internally consistent evidence without a model call."""
    preset = PRESETS["leaderboard"]
    seeds = list(preset["seeds"])
    seasons = int(preset["seasons"])
    repeats = 3
    candidate_episodes = []
    for seed_index, seed in enumerate(seeds):
        seed_center = 330.0 + (4.0 * seed_index)
        for repeat, repeat_offset in enumerate((-6.0, 0.0, 6.0), start=1):
            score = seed_center + repeat_offset
            candidate_episodes.append(
                {
                    "seed": seed,
                    "repeat": repeat,
                    "seasons": seasons,
                    "final_score": score,
                    "strategy_score": score,
                    "protocol_penalty": 0.0,
                    "score_components": _score_components(score),
                    "wins": 110 + seed_index,
                    "championships": seed_index % 2,
                    "illegal_actions": 0,
                    "decisions": seasons * 4,
                    "failed_decisions": 0,
                    "usage": {
                        "decisions_with_usage": seasons * 4,
                        "cost_decisions": seasons * 4,
                        "cost_usd": 0.0,
                        "provider": "openrouter",
                        "model": "synthetic-v3",
                        "upstream_provider": "SyntheticProvider",
                        "upstream_providers": ["SyntheticProvider"],
                    },
                }
            )
    candidate = {
        "agent": "rehearsal:synthetic-v3",
        "seeds": seeds,
        "seasons": seasons,
        "repeats": repeats,
        "episodes": candidate_episodes,
        "summary": summarize_episodes(candidate_episodes),
    }
    baselines = []
    for baseline_index, name in enumerate(preset["baselines"]):
        episodes = []
        for seed_index, seed in enumerate(seeds):
            score = 300.0 + (2.0 * seed_index) if name == "pick-trader" else 100.0 + baseline_index + seed_index
            episodes.append(
                {
                    "seed": seed,
                    "seasons": seasons,
                    "final_score": score,
                    "strategy_score": score,
                    "protocol_penalty": 0.0,
                    "score_components": _score_components(score),
                    "wins": 80 + seed_index,
                    "championships": seed_index % 2,
                    "illegal_actions": 0,
                    "decisions": seasons * 4,
                    "failed_decisions": 0,
                }
            )
        baselines.append(
            {
                "agent": name,
                "seeds": seeds,
                "seasons": seasons,
                "episodes": episodes,
                "summary": summarize_episodes(episodes),
            }
        )
    candidate_mean = _precise_mean_score(candidate)
    baseline_mean = sum(_precise_mean_score(baseline) for baseline in baselines) / len(baselines)
    payload = {
        "agent": "rehearsal:synthetic-v3",
        "seeds": seeds,
        "seasons": seasons,
        "candidate": candidate,
        "baselines": baselines,
        "normalized": {
            "candidate_mean_score": round(candidate_mean, 3),
            "baseline_panel_mean_score": round(baseline_mean, 3),
            "score_lift": round(candidate_mean - baseline_mean, 3),
            "score_lift_pct": round(((candidate_mean / baseline_mean) - 1.0) * 100.0, 2),
            "candidate_illegal_actions": 0,
            "baseline_illegal_actions": 0,
        },
        "paired": _paired_analysis(seeds, candidate, baselines),
        "run_info": {
            "command": "model",
            "agent": "rehearsal:synthetic-v3",
            "provider": "openrouter",
            "model": "synthetic-v3",
            "transport": "gateway-api",
            "preset": "leaderboard",
            "profile": "compact",
            "gm_bench_version": "0.0.0+rehearsal",
            "evidence_class": "synthetic-non-evidence",
            "benchmark_contract": SOTA_V3_CONTRACT,
            "scaffold_fingerprint": SOTA_V3_POLICY.expected_scaffold_fingerprints["openrouter"],
            "seed_panel": seed_panel_metadata(seeds, "leaderboard"),
            "protocol_repair_attempts": 1,
            "strict_fallback": True,
            "provider_options": {
                "GM_BENCH_PROTOCOL_REPAIR_ATTEMPTS": "1",
                "GM_AGENT_STRICT": "1",
                "GM_BENCH_OUTPUT_BUDGET_CELL": "4096",
                "OPENROUTER_ALLOW_FALLBACKS": "false",
                "OPENROUTER_REQUIRE_PARAMETERS": "true",
                "OPENROUTER_DATA_COLLECTION": "deny",
                "OPENROUTER_REASONING_ENABLED": "false",
                "OPENROUTER_PROVIDER_ONLY": "synthetic/fp8",
                "OPENROUTER_EXPECTED_UPSTREAM_PROVIDER": "SyntheticProvider",
                "OPENROUTER_EXPECTED_ENDPOINT_NAME": "SyntheticProvider | synthetic-v3",
                "OPENROUTER_MAX_TOKENS": "4096",
            },
        },
    }
    return payload


def synthetic_analysis_registry() -> dict[str, Any]:
    """Return a frozen synthetic registry used only inside the rehearsal."""
    return {
        "schema_version": 1,
        "contract": "sota-v3",
        "contract_fingerprint": SOTA_V3_CONTRACT["contract_fingerprint"],
        "provider": "openrouter",
        "profile": "compact",
        "preset": "leaderboard",
        "repeats": 3,
        "selection_status": "frozen",
        "output_token_cap": 4096,
        "shared_fixed_options": {
            "OPENROUTER_ALLOW_FALLBACKS": "false",
            "OPENROUTER_REQUIRE_PARAMETERS": "true",
            "OPENROUTER_DATA_COLLECTION": "deny",
            "GM_BENCH_PROTOCOL_REPAIR_ATTEMPTS": "1",
        },
        "shared_absent_options": [],
        "models": [
            {
                "id": "synthetic-v3",
                "provider": "openrouter",
                "model": "synthetic-v3",
                "transport": "gateway-api",
                "upstream_provider": "SyntheticProvider",
                "upstream_provider_slug": "synthetic/fp8",
                "endpoint_tag": "synthetic/fp8",
                "endpoint_name": "SyntheticProvider | synthetic-v3",
                "fixed_options": {"OPENROUTER_REASONING_ENABLED": "false"},
                "absent_options": [],
            }
        ],
    }


def synthetic_analysis_lane(raw: dict[str, Any]) -> dict[str, Any]:
    """Freeze the synthetic artifact's seed identity inside the rehearsal only."""
    return {
        "contract": "sota-v3",
        "contract_fingerprint": raw["run_info"]["benchmark_contract"]["contract_fingerprint"],
        "reference_agent": "pick-trader",
        "seed_panel": {
            "status": "frozen",
            **raw["run_info"]["seed_panel"],
        },
    }


def synthetic_analysis_protocol() -> dict[str, Any]:
    return {
        "contract": "sota-v3",
        "contract_fingerprint": SOTA_V3_CONTRACT["contract_fingerprint"],
        "statistical_analysis_plan": {
            "status": "frozen",
            "analysis_mode": "reference-only",
            "unit_of_inference": "seed",
            "primary_contrast": "paired lift versus pick-trader",
            "reference_agent": "pick-trader",
            "multiplicity_method": "holm-bonferroni",
            "alpha": 0.05,
            "inference_method": "exact-enumeration-sign-flip",
            "holm_family_size": 1,
        },
    }


def _require_valid(payload: dict[str, Any]) -> None:
    report = validate_leaderboard_payload(payload, policy=SOTA_V3_POLICY)
    if not report.ok:
        raise AssertionError(f"synthetic sota-v3 artifact failed validation: {report.errors}")


def _require_failure(name: str, payload: dict[str, Any], expected_text: str) -> dict[str, Any]:
    report = validate_leaderboard_payload(payload, policy=SOTA_V3_POLICY)
    if report.ok or not any(expected_text in error for error in report.errors):
        raise AssertionError(
            f"mutation {name!r} did not fail as expected; wanted {expected_text!r}, got {report.errors!r}"
        )
    return {"name": name, "status": "rejected", "matched": expected_text}


def _exercise_mutations(raw: dict[str, Any], compact: dict[str, Any]) -> list[dict[str, Any]]:
    wrong_contract = copy.deepcopy(compact)
    wrong_contract["run_info"]["benchmark_contract"] = SOTA_V2_CONTRACT

    soft_fallback = copy.deepcopy(compact)
    soft_fallback["run_info"]["strict_fallback"] = False
    soft_fallback["run_info"]["provider_options"]["GM_AGENT_STRICT"] = "0"

    stale_scaffold = copy.deepcopy(compact)
    stale_scaffold["run_info"]["scaffold_fingerprint"] = "0" * 16

    tampered_score = copy.deepcopy(compact)
    tampered_score["candidate"]["episodes"][0]["final_score"] = 9999.0

    unknown_version = copy.deepcopy(compact)
    unknown_version["run_info"]["benchmark_contract"]["benchmark_version"] = "sota-v999"
    declared_version = unknown_version["run_info"]["benchmark_contract"]["benchmark_version"]
    if declared_version in POLICIES:
        raise AssertionError("unknown benchmark version unexpectedly dispatched to a validation policy")

    changed_raw = copy.deepcopy(raw)
    changed_raw["run_info"]["rehearsal_mutation"] = True
    link_issues = raw_artifact_link_issues(compact, [changed_raw])
    expected_link_issue = "publication.raw_artifact_sha256 does not match any supplied raw artifact"
    if expected_link_issue not in link_issues:
        raise AssertionError(f"repository raw-link verifier did not reject changed evidence: {link_issues!r}")

    unregistered_row = build_leaderboard.model_row(
        compact,
        {
            "models": [
                {
                    "id": "registered-rehearsal",
                    "provider": "openai",
                    "model": "different-registered-model",
                }
            ]
        },
    )
    identity_issue = next(
        (issue for issue in unregistered_row["publication_issues"] if "provider/model is not pre-registered" in issue),
        None,
    )
    if identity_issue is None:
        raise AssertionError("shared row-ingestion policy accepted an unregistered provider/model route")

    return [
        _require_failure("wrong-contract", wrong_contract, "run_info.benchmark_contract"),
        _require_failure("soft-fallback", soft_fallback, "strict failure handling"),
        _require_failure("stale-scaffold", stale_scaffold, "does not match current scaffold"),
        {
            "name": "unknown-version-dispatch",
            "status": "rejected",
            "matched": f"no policy registered for {declared_version}",
        },
        {
            "name": "unregistered-route",
            "status": "rejected",
            "matched": identity_issue,
        },
        _require_failure("tampered-compact-score", tampered_score, "episode-derived"),
        {
            "name": "raw-link-mismatch",
            "status": "rejected",
            "matched": expected_link_issue,
        },
    ]


@contextlib.contextmanager
def _isolated_builder_globals(staging: Path):
    names = (
        "ROOT",
        "RESULTS_DIR",
        "OUTPUT_PATH",
        "MODEL_CONFIG_PATH",
        "PROTOCOL_CONFIG_PATH",
        "PANEL_ANALYSIS_PATH",
    )
    original = {name: getattr(build_leaderboard, name) for name in names}
    build_leaderboard.ROOT = staging
    build_leaderboard.RESULTS_DIR = staging / "results" / "leaderboard"
    build_leaderboard.OUTPUT_PATH = staging / "web" / "src" / "data" / "leaderboard.json"
    build_leaderboard.MODEL_CONFIG_PATH = staging / "config" / "sota_v2_models.json"
    build_leaderboard.PROTOCOL_CONFIG_PATH = staging / "config" / "publication_protocol.json"
    build_leaderboard.PANEL_ANALYSIS_PATH = staging / "results" / "analysis" / "publication-panel-analysis.json"
    try:
        yield
    finally:
        for name, value in original.items():
            setattr(build_leaderboard, name, value)


def _stage_site_inputs(staging: Path, compact: dict[str, Any], *, contract: str = "sota-v3") -> None:
    shutil.copytree(ROOT / "config", staging / "config")
    shutil.copytree(ROOT / "results" / "leaderboard", staging / "results" / "leaderboard")
    shutil.copytree(ROOT / "results" / "analysis", staging / "results" / "analysis")
    shutil.copytree(
        ROOT / "web",
        staging / "web",
        ignore=shutil.ignore_patterns("dist", "node_modules"),
    )
    source_modules = ROOT / "web" / "node_modules"
    if source_modules.is_dir():
        (staging / "web" / "node_modules").symlink_to(source_modules, target_is_directory=True)
    (staging / "results" / "leaderboard" / f"synthetic-{contract}.json").write_text(
        json.dumps(compact, indent=2, sort_keys=True) + "\n"
    )


def _exercise_site_builder(
    staging: Path,
    compact: dict[str, Any],
    *,
    excluded_contract: str = "sota-v3",
    model_label: str = "synthetic-v3",
) -> dict[str, Any]:
    _stage_site_inputs(staging, compact, contract=excluded_contract)
    model_config = json.loads((staging / "config" / "sota_v2_models.json").read_text())
    transformed = build_leaderboard.model_row(compact, model_config)
    if transformed["benchmark_version"] != excluded_contract:
        raise AssertionError(f"shared row-ingestion logic lost the artifact's {excluded_contract} identity")
    if transformed["artifact_sha256"] != canonical_sha256(compact):
        raise AssertionError("shared row-ingestion logic did not preserve the compact artifact identity")
    stdout = io.StringIO()
    stderr = io.StringIO()
    with (
        _isolated_builder_globals(staging),
        contextlib.redirect_stdout(stdout),
        contextlib.redirect_stderr(stderr),
    ):
        build_leaderboard.main()
    generated_path = staging / "web" / "src" / "data" / "leaderboard.json"
    generated = json.loads(generated_path.read_text())
    frozen = json.loads((ROOT / "web" / "src" / "data" / "leaderboard.json").read_text())
    if generated != frozen:
        raise AssertionError("isolated site-data build changed the frozen sota-v2 dataset")
    if generated["contract"]["benchmark_version"] != "sota-v2":
        raise AssertionError("isolated site-data build did not remain on sota-v2")
    if not any(model_label in line and "not sota-v2" in line for line in stderr.getvalue().splitlines()):
        raise AssertionError(
            f"site-data build did not explicitly report excluding the synthetic {excluded_contract} artifact"
        )
    version_key = (
        excluded_contract.replace("sota-", "")
        if excluded_contract == "sota-v3"
        else excluded_contract.replace("-", "_")
    )
    return {
        "status": "passed",
        "contract": generated["contract"]["benchmark_version"],
        f"synthetic_{version_key}_excluded": True,
        "matches_checked_in_dataset": True,
        "shared_row_ingestion": "passed",
        f"public_{version_key}_strategy_selected": False,
    }


def execution_authorization_issues(
    lane: dict[str, Any],
    *,
    mode: str,
    registry: dict[str, Any] | None = None,
    manifest: dict[str, Any] | None = None,
    protocol: dict[str, Any] | None = None,
    pricing: dict[str, Any] | None = None,
) -> list[str]:
    """Expose the runner's shared authorization gate in rehearsal output."""
    if mode == "synthetic":
        return []
    return publication_execution_issues(
        lane,
        registry or {},
        manifest,
        phase=mode,
        protocol=protocol,
        pricing=pricing,
    )


def v3_cross_file_coherence_issues(
    lane: dict[str, Any],
    registry: dict[str, Any],
    protocol: dict[str, Any],
    pricing: dict[str, Any],
    manifest: dict[str, Any],
    cost_estimate: dict[str, Any],
) -> list[str]:
    """Check duplicated preregistration facts at the rehearsal boundary.

    The production gate validates the executable contract.  This second layer
    covers the human-facing planning records that previously drifted to ten
    models, ten smokes, pending reasoning, and a stale reservation while the
    executable registry had already moved to eight reasoning-disabled routes.
    """

    issues: list[str] = []
    models = [model for model in registry.get("models") or [] if isinstance(model, dict)]
    model_ids = [str(model.get("id") or "") for model in models]
    model_slugs = [str(model.get("model") or "") for model in models]
    model_count = len(models)
    design = lane.get("statistical_panel_design") or {}
    selected = design.get("selected_allocation") or {}
    analysis_plan = protocol.get("statistical_analysis_plan") or {}
    protocol_panel = protocol.get("panel_design") or {}
    evaluated_grid = protocol_panel.get("evaluated_grid") or {}
    output_policy = protocol.get("output_policy") or {}
    budget_policy = protocol.get("budget_policy") or {}
    cost_calls = cost_estimate.get("calls") or {}
    cost_assumptions = cost_estimate.get("assumptions") or {}
    cost_models = [row for row in cost_estimate.get("models") or [] if isinstance(row, dict)]
    protocol_maximum = cost_estimate.get("protocol_maximum") or {}

    if not model_ids or any(not model_id for model_id in model_ids) or len(set(model_ids)) != model_count:
        issues.append("sota-v3 registered model ids must be non-empty and unique")
    if any(not slug for slug in model_slugs) or len(set(model_slugs)) != model_count:
        issues.append("sota-v3 registered model slugs must be non-empty and unique")

    declared_counts = {
        "lane minimum_headline_models": lane.get("minimum_headline_models"),
        "lane Holm family size": design.get("holm_family_size"),
        "protocol Holm family size": analysis_plan.get("holm_family_size"),
        "protocol evaluated-grid Holm family size": evaluated_grid.get("holm_family_size"),
        "cost model count": cost_calls.get("model_count"),
    }
    for label, declared in declared_counts.items():
        if declared != model_count:
            issues.append(f"sota-v3 {label} must equal the registered model count")

    if registry.get("required_smokes") != model_ids:
        issues.append("sota-v3 required smokes must match the registered models in order")
    if cost_calls.get("smoke_runs") != len(registry.get("required_smokes") or []):
        issues.append("sota-v3 cost smoke-run count must match required smokes")
    if set(pricing.get("models") or {}) != set(model_slugs):
        issues.append("sota-v3 pricing routes must exactly match the registered model slugs")
    cost_routes = {(str(row.get("experiment_id") or ""), str(row.get("model") or "")) for row in cost_models}
    if cost_routes != set(zip(model_ids, model_slugs, strict=True)):
        issues.append("sota-v3 cost routes must exactly match the registered ids and model slugs")
    if cost_estimate.get("schema_version") != 3:
        issues.append("sota-v3 cost artifact must use schema version 3")
    forecast_semantics = cost_assumptions.get("planning_forecast_call_semantics")
    if not isinstance(forecast_semantics, str) or "planning forecast" not in forecast_semantics.lower():
        issues.append("sota-v3 cost artifact must label the one-response planning forecast")

    reasoning_values = {
        lane.get("reasoning_policy"),
        output_policy.get("reasoning_policy"),
        *(model.get("reasoning_policy") for model in models),
    }
    if reasoning_values != {"disabled"}:
        issues.append("sota-v3 lane, protocol, and every registered route must be reasoning-disabled")
    if any(model.get("fixed_options", {}).get("OPENROUTER_REASONING_ENABLED") != "false" for model in models):
        issues.append("sota-v3 every registered route must send reasoning.enabled=false")
    if any(row.get("internal_reasoning_tokens_per_decision") != 0 for row in cost_models):
        issues.append("sota-v3 reasoning-disabled cost rows must reserve zero internal reasoning tokens")

    expected_protocol_panel_calls = 0
    expected_protocol_smoke_calls = 0
    models_by_id = {str(model.get("id") or ""): model for model in models}
    shared_fixed_options = registry.get("shared_fixed_options") or {}
    for row in cost_models:
        model = models_by_id.get(str(row.get("experiment_id") or ""), {})
        fixed_options = {**shared_fixed_options, **(model.get("fixed_options") or {})}
        try:
            repair_attempts = int(fixed_options.get("GM_BENCH_PROTOCOL_REPAIR_ATTEMPTS", 0))
        except (TypeError, ValueError):
            issues.append("sota-v3 repair attempts must be an integer")
            repair_attempts = 0
        if repair_attempts < 0:
            issues.append("sota-v3 repair attempts must be non-negative")
            repair_attempts = 0
        expected_calls_per_decision = MAX_INTERACTION_ROUNDS * (1 + repair_attempts)
        panel_calls = row.get("panel_calls")
        smoke_calls = row.get("smoke_calls")
        if row.get("maximum_api_calls_per_decision") != expected_calls_per_decision:
            issues.append("sota-v3 protocol-maximum calls per decision must include every round and repair")
        if not isinstance(panel_calls, int) or row.get("protocol_maximum_panel_calls") != (
            panel_calls * expected_calls_per_decision
        ):
            issues.append("sota-v3 protocol-maximum panel calls are inconsistent")
        else:
            expected_protocol_panel_calls += panel_calls * expected_calls_per_decision
        if not isinstance(smoke_calls, int) or row.get("protocol_maximum_smoke_calls") != (
            smoke_calls * expected_calls_per_decision
        ):
            issues.append("sota-v3 protocol-maximum smoke calls are inconsistent")
        else:
            expected_protocol_smoke_calls += smoke_calls * expected_calls_per_decision
    if protocol_maximum.get("max_interaction_rounds_per_decision") != MAX_INTERACTION_ROUNDS:
        issues.append("sota-v3 protocol maximum must use the runtime interaction-round limit")
    if protocol_maximum.get("panel_calls") != expected_protocol_panel_calls:
        issues.append("sota-v3 aggregate protocol-maximum panel calls are inconsistent")
    if protocol_maximum.get("smoke_calls") != expected_protocol_smoke_calls:
        issues.append("sota-v3 aggregate protocol-maximum smoke calls are inconsistent")
    if protocol_maximum.get("total_calls") != expected_protocol_panel_calls + expected_protocol_smoke_calls:
        issues.append("sota-v3 aggregate protocol-maximum total calls are inconsistent")

    for field in ("output_token_cap", "cap_pressure_threshold_tokens", "fallback_output_token_cap"):
        if output_policy.get(field) != lane.get(field):
            issues.append(f"sota-v3 protocol {field} must match the lane")
    expected_cap_action = "abort-sota-v3-and-repreregister"
    if lane.get("cap_pressure_action") != expected_cap_action:
        issues.append("sota-v3 lane cap pressure must abort and require preregistration")
    if output_policy.get("cap_pressure_action") != expected_cap_action:
        issues.append("sota-v3 protocol cap pressure must abort and require preregistration")
    if output_policy.get("on_first_trigger") != expected_cap_action:
        issues.append("sota-v3 first cap-pressure trigger must abort and require preregistration")
    if lane.get("max_cap_amendments") != 0 or output_policy.get("max_cap_amendments") != 0:
        issues.append("sota-v3 cap policy must forbid in-place amendments")

    seed_panel = lane.get("seed_panel") or {}
    expected_panel_facts = {
        "panel_seed_count": seed_panel.get("count"),
        "panel_repeats": lane.get("repeats"),
        "panel_preset": lane.get("preset"),
        "output_tokens_per_decision": lane.get("output_token_cap"),
    }
    for cost_key, expected in expected_panel_facts.items():
        if cost_assumptions.get(cost_key) != expected:
            issues.append(f"sota-v3 cost assumption {cost_key} must match the frozen lane")
    if selected.get("seed_count") != seed_panel.get("count") or selected.get("repeats") != lane.get("repeats"):
        issues.append("sota-v3 selected allocation must match the frozen seed panel and repeats")

    reserved = (cost_estimate.get("costs_usd") or {}).get("total_with_1_2x_contingency")
    ceiling = budget_policy.get("operator_ceiling_usd")
    forecast_is_valid = (
        isinstance(reserved, int | float)
        and not isinstance(reserved, bool)
        and math.isfinite(float(reserved))
        and reserved >= 0
    )
    ceiling_is_valid = (
        isinstance(ceiling, int | float)
        and not isinstance(ceiling, bool)
        and math.isfinite(float(ceiling))
        and ceiling > 0
    )
    if not forecast_is_valid or not ceiling_is_valid or reserved > ceiling:
        issues.append("sota-v3 generated planning forecast must fit under the operator ceiling")
    if budget_policy.get("spend_enforcement") != "dynamic-pre-provider-call":
        issues.append("sota-v3 spend ceiling must be enforced before every provider call")
    protocol_maximum_cost = (protocol_maximum.get("costs_usd") or {}).get("total_with_contingency")
    if (
        not isinstance(protocol_maximum_cost, int | float)
        or isinstance(protocol_maximum_cost, bool)
        or not math.isfinite(float(protocol_maximum_cost))
        or not isinstance(reserved, int | float)
        or isinstance(reserved, bool)
        or protocol_maximum_cost < reserved
    ):
        issues.append("sota-v3 protocol-maximum cost must be finite and no lower than the planning forecast")

    if manifest.get("status") == "not-started" and manifest.get("entries") != {}:
        issues.append("sota-v3 not-started smoke manifest must be empty")
    return list(dict.fromkeys(issues))


def _live_v3_readiness() -> dict[str, Any]:
    lane = json.loads((ROOT / "config" / "sota_v3_lane.json").read_text())
    registry = json.loads((ROOT / "config" / "sota_v3_models.json").read_text())
    manifest = json.loads((ROOT / "config" / "sota_v3_smoke_manifest.json").read_text())
    protocol = json.loads((ROOT / "config" / "sota_v3_publication_protocol.json").read_text())
    pricing = json.loads((ROOT / "config" / "sota_v3_pricing_snapshot.json").read_text())
    cost_estimate = json.loads((ROOT / "results" / "analysis" / "sota-v3-pre-smoke-cost-estimate.json").read_text())
    coherence_issues = v3_preregistration_coherence_issues(
        lane,
        registry,
        protocol,
        pricing,
        manifest,
    )
    coherence_issues.extend(
        v3_cross_file_coherence_issues(
            lane,
            registry,
            protocol,
            pricing,
            manifest,
            cost_estimate,
        )
    )
    return {
        "coherence_issues": list(dict.fromkeys(coherence_issues)),
        "synthetic_validation_issues": execution_authorization_issues(
            lane,
            mode="synthetic",
            registry=registry,
            manifest=manifest,
        ),
        "smoke_execution_issues": execution_authorization_issues(
            lane,
            mode="smoke",
            registry=registry,
            manifest=manifest,
            protocol=protocol,
            pricing=pricing,
        ),
        "panel_execution_issues": execution_authorization_issues(
            lane,
            mode="panel",
            registry=registry,
            manifest=manifest,
            protocol=protocol,
            pricing=pricing,
        ),
    }


def _ensure_web_dependencies(staging: Path, bun: str) -> dict[str, Any]:
    """Resolve ``staging/web/node_modules`` before the build runs.

    ``_stage_site_inputs`` symlinks ``ROOT/web/node_modules`` only when it
    already exists.  In a working tree it does, which is why this step has
    always passed.  On a clean checkout it does not, ``bun run build`` exits
    127 because ``vite`` is absent, and ``check=True`` aborts the whole
    rehearsal on an unhandled ``CalledProcessError``.  That is precisely the
    run PUBLISH_READINESS.md requires at the candidate SHA before any spend,
    so the gate currently cannot pass in the environment it was written for.

    Return a dict recorded under ``web_build.dependencies`` in the report.

    The policy is to install.  A gate that needs an undocumented manual prep
    step is a gate that passes for the wrong reason, which is the failure this
    harness exists to catch.  ``--frozen-lockfile`` keeps the committed
    ``bun.lock`` authoritative, so the fetch resolves pinned versions and
    cannot silently drift the built site.  "Zero spend" here means no provider
    or model call; a package fetch costs nothing and touches no contract
    source, so it does not weaken that guarantee.
    """
    modules = staging / "web" / "node_modules"
    if modules.exists():
        return {
            "status": "reused",
            "source": "working-tree-symlink" if modules.is_symlink() else "staged-directory",
        }
    completed = subprocess.run(
        [bun, "install", "--frozen-lockfile"],
        cwd=staging / "web",
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"`{bun} install --frozen-lockfile` failed in {staging / 'web'} "
            f"(exit {completed.returncode}); the staged site cannot be built.\n"
            f"{completed.stderr.strip()}"
        )
    # Bun reports the install summary on stderr when attached to a TTY and is
    # otherwise quiet, so fall back to stdout rather than record an empty tail.
    summary = (completed.stderr.strip() or completed.stdout.strip()).splitlines()
    return {
        "status": "installed",
        "command": f"{bun} install --frozen-lockfile",
        "output": summary[-1:] or ["<installer produced no summary output>"],
    }


def _run_web_build(staging: Path) -> dict[str, Any]:
    bun = shutil.which("bun")
    if bun is None:
        candidate = Path.home() / ".bun" / "bin" / "bun"
        bun = str(candidate) if candidate.is_file() else None
    if bun is None:
        raise RuntimeError("Bun is not installed; rerun with --skip-web-build")
    dependencies = _ensure_web_dependencies(staging, bun)
    completed = subprocess.run(
        [bun, "run", "build"],
        cwd=staging / "web",
        check=True,
        capture_output=True,
        text=True,
    )
    return {
        "status": "passed",
        "command": f"{bun} run build",
        "dependencies": dependencies,
        "output": completed.stdout.strip().splitlines()[-1:],
    }


def run_rehearsal(workdir: Path, *, run_web_build: bool, mode: str = "synthetic") -> dict[str, Any]:
    if mode != "synthetic":
        raise ValueError(
            "this zero-spend harness only implements synthetic mode; panel execution belongs to the "
            "publication runner and must independently clear both authorization locks"
        )
    workdir.mkdir(parents=True, exist_ok=True)
    raw = synthetic_raw_artifact()
    _require_valid(raw)
    compact = compact_result(raw)
    _require_valid(compact)
    raw_hash = canonical_sha256(raw)
    if compact["publication"]["raw_artifact_sha256"] != raw_hash:
        raise AssertionError("compact artifact does not hash-link to its raw evidence")

    raw_path = workdir / "synthetic-sota-v3.raw.json"
    compact_path = workdir / "synthetic-sota-v3.compact.json"
    raw_path.write_text(json.dumps(raw, indent=2, sort_keys=True) + "\n")
    compact_path.write_text(json.dumps(compact, indent=2, sort_keys=True) + "\n")

    wrong_policy = validate_leaderboard_payload(compact, policy=SOTA_V2_POLICY)
    if wrong_policy.ok:
        raise AssertionError("sota-v2 policy unexpectedly accepted a sota-v3 artifact")
    analysis = analyze(
        synthetic_analysis_registry(),
        [compact],
        raw_payloads=[raw],
        lane=synthetic_analysis_lane(raw),
        protocol=synthetic_analysis_protocol(),
    )
    if (
        analysis["status"] != "complete"
        or analysis["eligible_model_count"] != 1
        or analysis["publication_ready"] is not True
    ):
        raise AssertionError(f"sota-v3 analysis rehearsal failed: {analysis!r}")
    analyzed = analysis["models"][0]
    if analyzed["bootstrap_ci95"][0] == analyzed["bootstrap_ci95"][1]:
        raise AssertionError("analysis rehearsal remained degenerate; expected a non-zero lift interval")

    live_v3_readiness = _live_v3_readiness()
    if live_v3_readiness["coherence_issues"]:
        raise AssertionError(
            "live sota-v3 preregistration records contradict each other: "
            + "; ".join(live_v3_readiness["coherence_issues"])
        )

    site_staging = Path(tempfile.mkdtemp(prefix="site-staging-", dir=workdir))
    result = {
        "status": "passed",
        "mode": mode,
        "evidence_class": "synthetic-non-evidence",
        "spend_usd": 0.0,
        "workdir": str(workdir),
        "artifacts": {
            "raw": str(raw_path),
            "compact": str(compact_path),
            "canonical_raw_sha256": raw_hash,
        },
        "policy_selection": {
            "sota_v3": "accepted",
            "sota_v2": "rejected",
        },
        "analysis": {
            "status": analysis["status"],
            "eligible_model_count": analysis["eligible_model_count"],
            "holm_family_size": analysis["holm_family_size"],
            "analysis_mode": analysis["analysis_mode"],
            "mean_lift": analyzed["mean_lift"],
            "bootstrap_ci95": analyzed["bootstrap_ci95"],
            "model_tiering": analysis["model_tiering"],
        },
        "mutations": _exercise_mutations(raw, compact),
        "site_data_build": _exercise_site_builder(site_staging, compact),
        "live_v3_readiness": live_v3_readiness,
        "web_build": _run_web_build(site_staging) if run_web_build else {"status": "skipped"},
    }
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workdir",
        type=Path,
        help="disposable output directory (default: a new system temporary directory)",
    )
    parser.add_argument("--skip-web-build", action="store_true", help="skip `bun run build`")
    parser.add_argument(
        "--mode",
        choices=("synthetic",),
        default="synthetic",
        help="zero-spend validation mode; this harness cannot execute a panel",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.workdir is None:
        with tempfile.TemporaryDirectory(prefix="gm-bench-sota-v3-rehearsal-") as temporary:
            result = run_rehearsal(Path(temporary), run_web_build=not args.skip_web_build, mode=args.mode)
            result["workdir"] = "<temporary-directory-removed>"
            for artifact in result["artifacts"]:
                result["artifacts"][artifact] = (
                    "<temporary-directory-removed>"
                    if artifact != "canonical_raw_sha256"
                    else result["artifacts"][artifact]
                )
    else:
        result = run_rehearsal(args.workdir.resolve(), run_web_build=not args.skip_web_build, mode=args.mode)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
