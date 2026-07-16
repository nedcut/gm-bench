#!/usr/bin/env python3
"""Generate the fixed-panel publication cost estimate from committed inputs."""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gm_bench.benchmark_config import PRESETS  # noqa: E402
from gm_bench.protocol import PHASES  # noqa: E402

RUNTIME_STATUS = "pending-smoke-telemetry"
RUNTIME_NOTE = (
    "Regenerate this artifact from accepted smoke telemetry before approving the full panel; "
    "latency is reported only for models with committed observations."
)


def _read(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain an object")
    return payload


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def estimate(
    models_config: dict[str, Any],
    lane_config: dict[str, Any],
    pricing: dict[str, Any],
) -> dict[str, Any]:
    """Estimate the registered fixed panel and its required smoke gate."""
    models = models_config["models"]
    if not isinstance(models, list) or not models:
        raise ValueError("models config must register at least one model")
    if models_config.get("preset") != "leaderboard":
        raise ValueError("fixed-panel estimate requires the leaderboard preset")
    if models_config.get("contract") != lane_config.get("contract"):
        raise ValueError("model registry and lane contract must match")

    assumptions = pricing["planning_assumptions"]
    input_tokens = int(assumptions["input_tokens_per_decision"])
    output_tokens = int(assumptions["expected_output_tokens_per_decision"])
    if int(models_config["output_token_cap"]) != int(lane_config["output_token_cap"]):
        raise ValueError("model registry and lane output-token caps must match")
    if output_tokens != int(lane_config["output_token_cap"]):
        raise ValueError("planning output tokens must match the fixed lane cap")

    leaderboard = PRESETS["leaderboard"]
    smoke = PRESETS["smoke"]
    repeats = int(models_config["repeats"])
    panel_decisions_per_model = len(leaderboard["seeds"]) * int(leaderboard["seasons"]) * len(PHASES) * repeats
    smoke_decisions_per_run = len(smoke["seeds"]) * int(smoke["seasons"]) * len(PHASES)
    model_count = len(models)
    panel_calls = model_count * panel_decisions_per_model
    smoke_calls = model_count * smoke_decisions_per_run

    runtime_observations = pricing.get("runtime_observations") or {}
    runtime_by_model = runtime_observations.get("api_seconds_per_decision") or {}
    rows: list[dict[str, Any]] = []
    panel_costs: list[Decimal] = []
    smoke_costs: list[Decimal] = []
    observed_latency: dict[str, float] = {}
    for model in models:
        model_name = model["model"]
        rates = pricing["models"].get(model_name)
        if not rates:
            raise ValueError(f"missing pricing for {model_name}")
        per_decision_cost = input_tokens * _decimal(rates["prompt"]) + output_tokens * _decimal(rates["completion"])
        panel_cost = panel_decisions_per_model * per_decision_cost
        smoke_cost = smoke_decisions_per_run * per_decision_cost
        panel_costs.append(panel_cost)
        smoke_costs.append(smoke_cost)
        row = {
            "experiment_id": model["id"],
            "model": model_name,
            "cost_per_decision_usd": float(per_decision_cost),
            "panel_calls": panel_decisions_per_model,
            "panel_cost_usd": float(panel_cost),
            "smoke_calls": smoke_decisions_per_run,
            "smoke_cost_usd": float(smoke_cost),
        }
        runtime_seconds = runtime_by_model.get(model_name)
        if isinstance(runtime_seconds, int | float) and runtime_seconds > 0:
            row["observed_api_seconds_per_decision"] = runtime_seconds
            observed_latency[model_name] = runtime_seconds
        rows.append(row)

    panel_cost = sum(panel_costs, Decimal())
    smoke_cost = sum(smoke_costs, Decimal())
    total_cost = panel_cost + smoke_cost
    contingency = _decimal(assumptions["cost_contingency_multiplier"])
    return {
        "schema_version": 2,
        "supersedes": {
            "artifact": "retired 12-cell output-budget sweep estimate",
            "description": (
                "Replaces the four-cap, three-model sweep estimate with the registered "
                f"{len(models)}-model fixed {lane_config['output_token_cap']:,}-token panel and its required smoke gate."
            ),
        },
        "pricing_checked_at_utc": pricing["checked_at_utc"],
        "assumptions": {
            "input_tokens_per_decision": input_tokens,
            "output_tokens_per_decision": output_tokens,
            "cost_contingency_multiplier": float(contingency),
            "rates_are_per_token": bool(pricing["rates_are_per_token"]),
            "panel_preset": "leaderboard",
            "panel_seed_count": len(leaderboard["seeds"]),
            "panel_seasons": int(leaderboard["seasons"]),
            "panel_repeats": repeats,
            "phase_count": len(PHASES),
            "smoke_preset": "smoke",
            "smoke_seed_count": len(smoke["seeds"]),
            "smoke_seasons": int(smoke["seasons"]),
            "serial_workers": 1,
            "caveat": (
                "Provider prices and actual token usage can change. Recheck before paid "
                "runs; the operator spend guard remains mandatory."
            ),
        },
        "calls": {
            "model_count": model_count,
            "panel_decisions_per_model": panel_decisions_per_model,
            "panel_calls": panel_calls,
            "smoke_runs": model_count,
            "smoke_decisions_per_run": smoke_decisions_per_run,
            "smoke_calls": smoke_calls,
            "total_calls": panel_calls + smoke_calls,
        },
        "models": rows,
        "costs_usd": {
            "panel": float(panel_cost),
            "smoke": float(smoke_cost),
            "total_unrounded": float(total_cost),
            "total_with_1_2x_contingency": float(total_cost * contingency),
        },
        "runtime": {
            "status": RUNTIME_STATUS,
            "note": RUNTIME_NOTE,
            "observation_source": runtime_observations.get("source"),
            "observed_at_utc": runtime_observations.get("observed_at_utc"),
            "observed_api_seconds_per_decision_by_model": observed_latency,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models-config", type=Path, default=Path("config/sota_v2_models.json"))
    parser.add_argument("--lane-config", type=Path, default=Path("config/sota_v2_lane.json"))
    parser.add_argument("--pricing", type=Path, default=Path("config/openrouter_pricing_snapshot.json"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = estimate(
        _read(args.models_config),
        _read(args.lane_config),
        _read(args.pricing),
    )
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered)
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
