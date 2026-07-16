#!/usr/bin/env python3
"""Audit output-budget sweep coverage and emit publication data.

This command never calls a model. Feed it completed result artifacts; it groups
strict sota-v2 API rows by model and configured output cap and refuses to claim
saturation until every selected model has every planned cap.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gm_bench.official import OUTPUT_BUDGET_SWEEP_POLICY, validate_leaderboard_payload  # noqa: E402

CAP_OPTION_NAMES = {
    "OPENAI_MAX_TOKENS",
    "ANTHROPIC_MAX_TOKENS",
    "GEMINI_MAX_OUTPUT_TOKENS",
    "OPENROUTER_MAX_TOKENS",
}


def _model_specs(config: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    specs: list[dict[str, Any]] = []
    errors: list[str] = []
    seen_ids: set[str] = set()
    seen_identities: set[tuple[str, str]] = set()
    for index, raw in enumerate(config.get("models") or []):
        if not isinstance(raw, dict):
            errors.append(f"models[{index}] must be an object with id/provider/model provenance")
            continue
        spec = dict(raw)
        experiment_id = str(spec.get("id") or "").strip()
        provider = str(spec.get("provider") or "").strip()
        model = str(spec.get("model") or "").strip()
        if not experiment_id or not provider or not model:
            errors.append(f"models[{index}] requires non-empty id, provider, and model")
            continue
        if experiment_id in seen_ids:
            errors.append(f"duplicate experiment id: {experiment_id}")
        if (provider, model) in seen_identities:
            errors.append(f"duplicate provider/model identity: {provider}:{model}")
        fixed_options = spec.get("fixed_options") or {}
        absent_options = spec.get("absent_options") or []
        if not isinstance(fixed_options, dict) or not isinstance(absent_options, list):
            errors.append(f"models[{index}] fixed_options must be an object and absent_options must be a list")
            continue
        if provider == "openrouter":
            endpoint_name = str(spec.get("endpoint_name") or "").strip()
            expected_option = str(fixed_options.get("OPENROUTER_EXPECTED_ENDPOINT_NAME") or "").strip()
            if not endpoint_name or expected_option != endpoint_name:
                errors.append(
                    f"models[{index}] must freeze endpoint_name and matching "
                    "OPENROUTER_EXPECTED_ENDPOINT_NAME provenance"
                )
        overlap = set(fixed_options).intersection(str(value) for value in absent_options)
        if overlap:
            errors.append(f"models[{index}] options cannot be both fixed and absent: {sorted(overlap)!r}")
        seen_ids.add(experiment_id)
        seen_identities.add((provider, model))
        specs.append(spec)
    return specs, errors


def analyze(config: dict[str, Any], payloads: list[dict[str, Any]]) -> dict[str, Any]:
    caps = config["output_token_caps"]
    retired = str(config.get("status") or "").startswith("retired")
    specs, config_errors = _model_specs(config)
    specs_by_identity = {(str(spec["provider"]), str(spec["model"])): spec for spec in specs}
    points: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for payload in payloads:
        info = payload.get("run_info") or {}
        contract = info.get("benchmark_contract") or {}
        transport = info.get("transport")
        provider = str(info.get("provider") or "")
        model = str(info.get("model") or "")
        spec = specs_by_identity.get((provider, model))
        if spec is None:
            continue
        artifact_sha256 = _sha(payload)
        reasons: list[str] = []
        report = validate_leaderboard_payload(payload, policy=OUTPUT_BUDGET_SWEEP_POLICY)
        if not report.ok:
            reasons.append("artifact does not pass output-budget-sweep validation")
        if contract.get("benchmark_version") != config.get("contract"):
            reasons.append("benchmark contract does not match sweep config")
        if transport != spec.get("transport"):
            reasons.append(f"transport does not match pre-registered value {spec.get('transport')!r}")
        if info.get("profile") != config.get("profile"):
            reasons.append("observation profile does not match sweep config")
        if info.get("preset") != config.get("preset"):
            reasons.append("preset does not match sweep config")
        candidate = payload.get("candidate") or {}
        if int(candidate.get("repeats", 1) or 1) != int(config.get("repeats", 1)):
            reasons.append("repeat count does not match sweep config")
        options = info.get("provider_options") or {}
        for key, expected in (spec.get("fixed_options") or {}).items():
            if str(options.get(key, "")) != str(expected):
                reasons.append(f"provider option {key} does not match pre-registered value")
        for key in spec.get("absent_options") or []:
            if options.get(str(key)) not in (None, ""):
                reasons.append(f"provider option {key} must be absent for this experiment")
        cap_options = [(key, options[key]) for key in CAP_OPTION_NAMES if options.get(key) not in (None, "")]
        if len(cap_options) > 1:
            reasons.append("multiple output-cap options are recorded")
        raw_cap = cap_options[0][1] if len(cap_options) == 1 else None
        # Distinguish "provider recorded no max" from "cell parse failed" so an
        # uncapped cell with a numeric provider max is rejected symmetrically.
        provider_cap_absent = len(cap_options) == 0
        effective_cap = None if provider_cap_absent else _parse_cap(raw_cap, reasons, "provider output cap")
        cell_label = options.get("GM_BENCH_OUTPUT_BUDGET_CELL")
        if cell_label in (None, ""):
            reasons.append("missing GM_BENCH_OUTPUT_BUDGET_CELL provenance")
        cap = _parse_cap(cell_label, reasons, "output-budget cell")
        if not provider_cap_absent and effective_cap != cap:
            reasons.append("output-budget cell does not match the provider output cap")
        if provider_cap_absent and cap is not None:
            reasons.append("output-budget cell is capped but the provider recorded no output max")
        summary = (payload.get("candidate") or {}).get("summary") or {}
        usage = summary.get("usage") or {}
        decisions = int(summary.get("decisions") or 0)
        expected_upstream = str(spec.get("upstream_provider") or "").strip()
        observed_upstreams = sorted({str(value) for value in usage.get("upstream_providers") or [] if value})
        if expected_upstream and [value.casefold() for value in observed_upstreams] != [expected_upstream.casefold()]:
            reasons.append("observed upstream provider does not match the pre-registered route")
        if cap not in caps:
            reasons.append("output cap is not in the planned sweep")
        if decisions <= 0:
            reasons.append("candidate has no decision points")
        if not isinstance(summary.get("mean_score"), int | float):
            reasons.append("candidate summary does not report a numeric mean_score")
        for key in ("input_tokens", "output_tokens"):
            if key not in usage:
                reasons.append(f"candidate usage does not report {key}")
        if config.get("require_complete_cost", True):
            if usage.get("cost_usd") is None:
                reasons.append("candidate usage does not report a numeric cost")
            if int(usage.get("cost_decisions") or 0) != decisions:
                reasons.append("candidate cost telemetry does not cover every decision")
        if reasons:
            rejected.append(
                {
                    "experiment_id": spec["id"],
                    "provider": provider,
                    "model": model,
                    "artifact_sha256": artifact_sha256,
                    "reasons": reasons,
                }
            )
            continue
        paired = payload.get("paired") or {}
        points.append(
            {
                "experiment_id": spec["id"],
                "model": model,
                "provider": provider,
                "upstream_provider": observed_upstreams[0] if observed_upstreams else None,
                "output_token_cap": cap,
                "effective_provider_output_token_cap": effective_cap,
                "mean_score": summary.get("mean_score"),
                "input_tokens_per_decision": _per_decision(usage, "input_tokens", decisions),
                "output_tokens_per_decision": _per_decision(usage, "output_tokens", decisions),
                "cost_usd": usage.get("cost_usd"),
                "cost_per_decision_usd": round(float(usage.get("cost_usd")) / decisions, 6) if decisions else None,
                "api_latency_s_per_decision": round(float(usage.get("api_latency_ms", 0)) / decisions / 1000, 3)
                if decisions
                else None,
                "protocol_repair_attempts": int(usage.get("protocol_repair_attempts") or 0),
                "decision_failure_rate": summary.get("decision_failure_rate"),
                "score_lift": (payload.get("normalized") or {}).get("score_lift"),
                "sign_flip_p_value": paired.get("sign_flip_p_value"),
                "artifact_sha256": artifact_sha256,
                "raw_artifact_sha256": (payload.get("publication") or {}).get("raw_artifact_sha256"),
            }
        )
    experiment_ids = sorted(str(spec["id"]) for spec in specs)
    present = {(point["experiment_id"], point["output_token_cap"]) for point in points}
    duplicate_cells = sorted(
        [
            {"experiment_id": experiment_id, "output_token_cap": cap}
            for experiment_id, cap in present
            if sum(1 for point in points if (point["experiment_id"], point["output_token_cap"]) == (experiment_id, cap))
            > 1
        ],
        key=lambda row: (row["experiment_id"], row["output_token_cap"] is None, row["output_token_cap"] or 0),
    )
    missing = (
        []
        if retired
        else [
            {"experiment_id": experiment_id, "output_token_cap": cap}
            for experiment_id in experiment_ids
            for cap in caps
            if (experiment_id, cap) not in present
        ]
    )
    complete = (
        not retired
        and bool(specs)
        and not config_errors
        and len(specs) == int(config["decision_rule"]["required_models"])
        and not missing
        and not duplicate_cells
        and not rejected
    )
    if retired:
        reason = "four-cap sweep retired before replacement official cells; fixed safety ceiling governs publication"
    elif complete:
        reason = "sweep complete; inspect curves and freeze the lane cap before ranking"
    elif not specs:
        reason = "no sweep models selected; no output-budget conclusion is permitted"
    elif config_errors:
        reason = "sweep configuration is invalid; no output-budget conclusion is permitted"
    elif rejected:
        reason = "one or more artifacts were rejected; no output-budget conclusion is permitted"
    elif duplicate_cells:
        reason = "duplicate model-cap cells must be resolved before interpreting the sweep"
    else:
        reason = "missing planned model-cap cells; no output-budget conclusion is permitted"
    recommendation = _decision_recommendation(config, points) if complete else None
    return {
        "schema_version": 1,
        "status": "retired" if retired else ("complete-needs-interpretation" if complete else "incomplete"),
        "publishable_ranking": False,
        "reason": reason,
        "planned_caps": caps,
        "models": specs,
        "config_errors": config_errors,
        "missing": missing,
        "duplicate_cells": duplicate_cells,
        "rejected_artifacts": rejected,
        "points": sorted(
            points,
            key=lambda row: (
                row["experiment_id"],
                row["output_token_cap"] is None,
                row["output_token_cap"] or 0,
            ),
        ),
        "decision_recommendation": recommendation,
    }


def _decision_recommendation(config: dict[str, Any], points: list[dict[str, Any]]) -> dict[str, Any]:
    rule = config["decision_rule"]
    caps = sorted(int(cap) for cap in config["output_token_caps"])
    by_cell = {(point["experiment_id"], int(point["output_token_cap"])): point for point in points}
    experiment_ids = sorted({str(point["experiment_id"]) for point in points})
    absolute = float(rule["material_gain_score_points"])
    relative = float(rule["material_gain_relative"])
    comparisons: list[dict[str, Any]] = []
    for cap in caps[:-1]:
        model_rows = []
        material_models = 0
        for experiment_id in experiment_ids:
            lower = float(by_cell[(experiment_id, cap)]["mean_score"])
            threshold = max(absolute, abs(lower) * relative)
            gains = {
                str(higher): round(float(by_cell[(experiment_id, higher)]["mean_score"]) - lower, 6)
                for higher in caps
                if higher > cap
            }
            material = any(gain >= threshold for gain in gains.values())
            material_models += int(material)
            model_rows.append(
                {
                    "experiment_id": experiment_id,
                    "lower_cap_mean_score": lower,
                    "material_gain_threshold": round(threshold, 6),
                    "gains_to_higher_caps": gains,
                    "material_gain_observed": material,
                }
            )
        comparisons.append({"output_token_cap": cap, "material_models": material_models, "models": model_rows})
        if material_models == 0:
            return {
                "output_budget_status": "frozen-saturation",
                "output_token_cap": cap,
                "rule": "lowest cap with no material gain for any selected model at any higher tested cap",
                "comparisons": comparisons,
            }
    fallback = int(rule["non_saturation_output_token_cap"])
    return {
        "output_budget_status": "frozen-fixed-budget",
        "output_token_cap": fallback,
        "rule": "no lower cap saturated; freeze the pre-registered highest common cap and publish curves",
        "comparisons": comparisons,
    }


def _per_decision(usage: dict[str, Any], key: str, decisions: int) -> float | None:
    return round(float(usage.get(key, 0)) / decisions, 1) if decisions else None


def _parse_cap(value: Any, reasons: list[str], label: str) -> int | None:
    if value in (None, "", "uncapped"):
        return None
    try:
        cap = int(value)
    except (TypeError, ValueError):
        reasons.append(f"{label} is not an integer or uncapped")
        return None
    if cap < 1:
        reasons.append(f"{label} must be positive")
        return None
    return cap


def _sha(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifacts", nargs="*", type=Path)
    parser.add_argument("--config", type=Path, default=Path("config/output_budget_sweep.json"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        config = json.loads(args.config.read_text())
        payloads = [json.loads(path.read_text()) for path in args.artifacts]
    except (OSError, json.JSONDecodeError) as exc:
        sys.exit(f"analyze_output_budget: {exc}")
    result = analyze(config, payloads)
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
