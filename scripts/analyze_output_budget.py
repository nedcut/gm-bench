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

from gm_bench.official import SOTA_V2_POLICY, validate_leaderboard_payload  # noqa: E402

CAP_OPTION_NAMES = {
    "OPENAI_MAX_TOKENS",
    "ANTHROPIC_MAX_TOKENS",
    "GEMINI_MAX_OUTPUT_TOKENS",
    "OPENROUTER_MAX_TOKENS",
}


def analyze(config: dict[str, Any], payloads: list[dict[str, Any]]) -> dict[str, Any]:
    caps = config["output_token_caps"]
    wanted_models = set(config.get("models") or [])
    points: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for payload in payloads:
        info = payload.get("run_info") or {}
        contract = info.get("benchmark_contract") or {}
        transport = info.get("transport")
        model = str(info.get("model") or "")
        artifact_sha256 = _sha(payload)
        reasons: list[str] = []
        report = validate_leaderboard_payload(payload, policy=SOTA_V2_POLICY)
        if not report.ok:
            reasons.append("artifact does not pass sota-v2 validation")
        if contract.get("benchmark_version") != config.get("contract"):
            reasons.append("benchmark contract does not match sweep config")
        if transport not in {"direct-api", "gateway-api", "local-api"}:
            reasons.append("transport is not an API lane")
        if not wanted_models:
            # Empty models means "awaiting selection", not "discover from artifacts".
            # Still validate/reject each fed artifact so bad cells are visible.
            reasons.append("sweep config has no models selected")
        elif model not in wanted_models:
            continue
        candidate = payload.get("candidate") or {}
        if int(candidate.get("repeats", 1) or 1) != int(config.get("repeats", 1)):
            reasons.append("repeat count does not match sweep config")
        options = info.get("provider_options") or {}
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
        if cap not in caps:
            reasons.append("output cap is not in the planned sweep")
        if decisions <= 0:
            reasons.append("candidate has no decision points")
        for key in ("input_tokens", "output_tokens"):
            if key not in usage:
                reasons.append(f"candidate usage does not report {key}")
        if reasons:
            rejected.append({"model": model or None, "artifact_sha256": artifact_sha256, "reasons": reasons})
            continue
        points.append(
            {
                "model": model,
                "provider": info.get("provider"),
                "output_token_cap": cap,
                "effective_provider_output_token_cap": effective_cap,
                "mean_score": summary.get("mean_score"),
                "input_tokens_per_decision": _per_decision(usage, "input_tokens", decisions),
                "output_tokens_per_decision": _per_decision(usage, "output_tokens", decisions),
                "decision_failure_rate": summary.get("decision_failure_rate"),
                "artifact_sha256": artifact_sha256,
                "raw_artifact_sha256": (payload.get("publication") or {}).get("raw_artifact_sha256"),
            }
        )
    # Never invent models from artifacts: an empty config stays incomplete until
    # operators explicitly select the 2–3 sweep models.
    models = sorted(wanted_models)
    present = {(point["model"], point["output_token_cap"]) for point in points}
    duplicate_cells = sorted(
        [
            {"model": model, "output_token_cap": cap}
            for model, cap in present
            if sum(1 for point in points if (point["model"], point["output_token_cap"]) == (model, cap)) > 1
        ],
        key=lambda row: (row["model"], row["output_token_cap"] is None, row["output_token_cap"] or 0),
    )
    missing = [
        {"model": model, "output_token_cap": cap} for model in models for cap in caps if (model, cap) not in present
    ]
    complete = (
        bool(wanted_models)
        and len(models) >= int(config["decision_rule"]["minimum_models"])
        and not missing
        and not duplicate_cells
        and not rejected
    )
    if complete:
        reason = "sweep complete; inspect curves and freeze the lane cap before ranking"
    elif not wanted_models:
        reason = "no sweep models selected; no output-budget conclusion is permitted"
    elif rejected:
        reason = "one or more artifacts were rejected; no output-budget conclusion is permitted"
    elif duplicate_cells:
        reason = "duplicate model-cap cells must be resolved before interpreting the sweep"
    else:
        reason = "missing planned model-cap cells; no output-budget conclusion is permitted"
    return {
        "schema_version": 1,
        "status": "complete-needs-interpretation" if complete else "incomplete",
        "publishable_ranking": False,
        "reason": reason,
        "planned_caps": caps,
        "models": models,
        "missing": missing,
        "duplicate_cells": duplicate_cells,
        "rejected_artifacts": rejected,
        "points": sorted(
            points, key=lambda row: (row["model"], row["output_token_cap"] is None, row["output_token_cap"] or 0)
        ),
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
