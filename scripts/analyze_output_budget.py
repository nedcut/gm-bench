#!/usr/bin/env python3
"""Audit output-budget sweep coverage and emit publication data.

This command never calls a model. Feed it completed result artifacts; it groups
strict sota-v2 API rows by model and configured output cap and refuses to claim
saturation until every selected model has every planned cap.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def analyze(config: dict[str, Any], payloads: list[dict[str, Any]]) -> dict[str, Any]:
    caps = config["output_token_caps"]
    wanted_models = set(config.get("models") or [])
    points: list[dict[str, Any]] = []
    for payload in payloads:
        info = payload.get("run_info") or {}
        contract = info.get("benchmark_contract") or {}
        transport = info.get("transport")
        if contract.get("benchmark_version") != config.get("contract"):
            continue
        if transport not in {"direct-api", "gateway-api", "local-api"}:
            continue
        model = str(info.get("model") or "")
        if wanted_models and model not in wanted_models:
            continue
        options = info.get("provider_options") or {}
        raw_cap = next((options[key] for key in options if key.endswith("MAX_TOKENS") and "REASONING" not in key), None)
        cap = int(raw_cap) if raw_cap not in (None, "", "uncapped") else None
        summary = (payload.get("candidate") or {}).get("summary") or {}
        usage = summary.get("usage") or {}
        decisions = int(summary.get("decisions") or 0)
        points.append(
            {
                "model": model,
                "provider": info.get("provider"),
                "output_token_cap": cap,
                "mean_score": summary.get("mean_score"),
                "input_tokens_per_decision": _per_decision(usage, "input_tokens", decisions),
                "output_tokens_per_decision": _per_decision(usage, "output_tokens", decisions),
                "decision_failure_rate": summary.get("decision_failure_rate"),
                "artifact_sha256": _sha(payload),
            }
        )
    models = sorted(wanted_models or {point["model"] for point in points})
    present = {(point["model"], point["output_token_cap"]) for point in points}
    missing = [
        {"model": model, "output_token_cap": cap} for model in models for cap in caps if (model, cap) not in present
    ]
    complete = len(models) >= int(config["decision_rule"]["minimum_models"]) and not missing
    return {
        "schema_version": 1,
        "status": "complete-needs-interpretation" if complete else "incomplete",
        "publishable_ranking": False,
        "reason": (
            "sweep complete; inspect curves and freeze the lane cap before ranking"
            if complete
            else "missing planned model-cap cells; no output-budget conclusion is permitted"
        ),
        "planned_caps": caps,
        "models": models,
        "missing": missing,
        "points": sorted(
            points, key=lambda row: (row["model"], row["output_token_cap"] is None, row["output_token_cap"] or 0)
        ),
    }


def _per_decision(usage: dict[str, Any], key: str, decisions: int) -> float | None:
    return round(float(usage.get(key, 0)) / decisions, 1) if decisions else None


def _sha(payload: dict[str, Any]) -> str:
    import hashlib

    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifacts", nargs="*", type=Path)
    parser.add_argument("--config", type=Path, default=Path("config/output_budget_sweep.json"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    payloads = [json.loads(path.read_text()) for path in args.artifacts]
    result = analyze(config, payloads)
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
