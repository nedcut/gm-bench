#!/usr/bin/env python3
"""Generate a conservative, reproducible cost estimate for publication runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from gm_bench.benchmark_config import PRESETS
from gm_bench.protocol import PHASES


def _read(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain an object")
    return payload


def estimate(
    sweep: dict[str, Any], pricing: dict[str, Any], *, expected_output_tokens: int | None = None
) -> dict[str, Any]:
    assumptions = pricing["planning_assumptions"]
    input_tokens = int(assumptions["input_tokens_per_decision"])
    expected_output = int(expected_output_tokens or assumptions["expected_output_tokens_per_decision"])
    preset = PRESETS[str(sweep["preset"])]
    decisions = len(preset["seeds"]) * int(preset["seasons"]) * len(PHASES) * int(sweep["repeats"])
    runtime_observations = pricing.get("runtime_observations") or {}
    runtime_by_model = runtime_observations.get("api_seconds_per_decision") or {}
    rows: list[dict[str, Any]] = []
    for model in sweep["models"]:
        rates = pricing["models"].get(model["model"])
        if not rates:
            raise ValueError(f"missing pricing for {model['model']}")
        runtime_seconds = runtime_by_model.get(model["model"])
        if not isinstance(runtime_seconds, int | float) or runtime_seconds <= 0:
            raise ValueError(f"missing positive runtime observation for {model['model']}")
        for cap in sweep["output_token_caps"]:
            if not isinstance(cap, int) or cap < 1:
                raise ValueError("cost estimation requires every sweep cell to have a positive bounded cap")
            planning_output = min(cap, expected_output)
            prompt_cost = decisions * input_tokens * float(rates["prompt"])
            planning_completion_cost = decisions * planning_output * float(rates["completion"])
            ceiling_completion_cost = decisions * cap * float(rates["completion"])
            rows.append(
                {
                    "experiment_id": model["id"],
                    "model": model["model"],
                    "output_token_cap": cap,
                    "decisions": decisions,
                    "planning_output_tokens_per_decision": planning_output,
                    "planning_cost_usd": round(prompt_cost + planning_completion_cost, 2),
                    "token_ceiling_cost_usd": round(prompt_cost + ceiling_completion_cost, 2),
                    "observed_smoke_api_seconds_per_decision": runtime_seconds,
                    "projected_serial_api_hours": round(decisions * float(runtime_seconds) / 3600, 2),
                }
            )
    planning_total = sum(row["planning_cost_usd"] for row in rows)
    ceiling_total = sum(row["token_ceiling_cost_usd"] for row in rows)
    cost_contingency = float(assumptions["cost_contingency_multiplier"])
    runtime_contingency = float(assumptions["runtime_contingency_multiplier"])
    runtime_total_hours = sum(row["projected_serial_api_hours"] for row in rows)
    return {
        "schema_version": 1,
        "pricing_checked_at_utc": pricing["checked_at_utc"],
        "assumptions": {
            "input_tokens_per_decision": input_tokens,
            "expected_output_tokens_per_decision": expected_output,
            "decisions_per_cell": decisions,
            "serial_workers": 1,
            "cost_contingency_multiplier": cost_contingency,
            "runtime_contingency_multiplier": runtime_contingency,
            "runtime_observation_source": runtime_observations.get("source"),
            "runtime_observed_at_utc": runtime_observations.get("observed_at_utc"),
            "caveat": "Provider prices, actual tokens, and latency can change. Recheck before paid runs; the spend guard remains mandatory.",
        },
        "cells": rows,
        "planning_total_usd": round(planning_total, 2),
        "planning_total_with_contingency_usd": round(planning_total * cost_contingency, 2),
        "token_ceiling_total_usd": round(ceiling_total, 2),
        "token_ceiling_total_with_contingency_usd": round(ceiling_total * cost_contingency, 2),
        "projected_serial_api_hours": round(runtime_total_hours, 2),
        "projected_serial_api_hours_with_contingency": round(runtime_total_hours * runtime_contingency, 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sweep-config", type=Path, default=Path("config/output_budget_sweep.json"))
    parser.add_argument("--pricing", type=Path, default=Path("config/openrouter_pricing_snapshot.json"))
    parser.add_argument("--expected-output-tokens", type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.expected_output_tokens is not None and args.expected_output_tokens < 1:
        parser.error("--expected-output-tokens must be positive")
    result = estimate(
        _read(args.sweep_config),
        _read(args.pricing),
        expected_output_tokens=args.expected_output_tokens,
    )
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
