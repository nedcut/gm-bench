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
from gm_bench.protocol import MAX_INTERACTION_ROUNDS, PHASES, V6_PAID_CALLS_PER_DECISION  # noqa: E402

RUNTIME_STATUS_PENDING = "pending-smoke-telemetry"
RUNTIME_STATUS_COMPLETE = "complete-from-accepted-smokes"
RUNTIME_NOTE_PENDING = (
    "Regenerate this artifact from accepted smoke telemetry before approving the full panel; "
    "latency is reported only for models with committed observations."
)
RUNTIME_NOTE_COMPLETE = (
    "Runtime observations are sourced from every currently registered model's accepted smoke; "
    "recheck before paid full-panel runs if pricing, routes, or prompts change."
)
PRIVATE_PANEL_CONTRACTS = frozenset({"sota-v3", "sota-v4", "sota-v5"})
# Lanes planned before the v6 execution rules, where one decision could buy up
# to MAX_INTERACTION_ROUNDS provider calls. Their committed plans are frozen
# evidence and must keep regenerating exactly, so they keep the old maximum and
# the old field name. Every later lane is priced at one paid call per decision.
PRE_V6_CALL_CONTRACTS = frozenset({"sota-v2", "sota-v3", "sota-v4"})


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
    reasoning_tokens_value = assumptions.get("expected_internal_reasoning_tokens_per_decision")
    if int(models_config["output_token_cap"]) != int(lane_config["output_token_cap"]):
        raise ValueError("model registry and lane output-token caps must match")
    if output_tokens != int(lane_config["output_token_cap"]):
        raise ValueError("planning output tokens must match the fixed lane cap")

    leaderboard = PRESETS["leaderboard"]
    smoke = PRESETS["smoke"]
    repeats = int(models_config["repeats"])
    panel_seed_count = len(leaderboard["seeds"])
    contract = lane_config.get("contract")
    if contract in PRIVATE_PANEL_CONTRACTS:
        seed_panel = lane_config.get("seed_panel")
        if not isinstance(seed_panel, dict):
            raise ValueError(f"{contract} fixed-panel estimate requires seed_panel metadata")
        panel_seed_count = seed_panel.get("count")
        if not isinstance(panel_seed_count, int) or isinstance(panel_seed_count, bool) or panel_seed_count < 2:
            raise ValueError(f"{contract} fixed-panel estimate requires a positive seed_panel.count")
    # v6 gives a paying agent one call per decision phase, so the protocol
    # maximum is that call plus any configured repair -- not the five
    # interaction rounds of the pre-v6 lane, which only unpaid in-process
    # policies still get.
    pre_v6_lane = contract in PRE_V6_CALL_CONTRACTS
    calls_per_decision_limit = MAX_INTERACTION_ROUNDS if pre_v6_lane else V6_PAID_CALLS_PER_DECISION
    panel_decisions_per_model = panel_seed_count * int(leaderboard["seasons"]) * len(PHASES) * repeats
    smoke_decisions_per_run = len(smoke["seeds"]) * int(smoke["seasons"]) * len(PHASES)
    model_count = len(models)
    panel_calls = model_count * panel_decisions_per_model
    smoke_calls = model_count * smoke_decisions_per_run

    runtime_observations = pricing.get("runtime_observations") or {}
    runtime_by_model = runtime_observations.get("api_seconds_per_decision") or {}
    rows: list[dict[str, Any]] = []
    panel_costs: list[Decimal] = []
    smoke_costs: list[Decimal] = []
    protocol_max_panel_costs: list[Decimal] = []
    protocol_max_smoke_costs: list[Decimal] = []
    protocol_max_panel_calls = 0
    protocol_max_smoke_calls = 0
    observed_latency: dict[str, float] = {}
    for model in models:
        model_name = model["model"]
        rates = pricing["models"].get(model_name)
        if not rates:
            raise ValueError(f"missing pricing for {model_name}")
        applied_rates = rates
        long_context_override = rates.get("long_context_override")
        if long_context_override:
            threshold = int(long_context_override["min_prompt_tokens"])
            if input_tokens >= threshold:
                applied_rates = long_context_override

        reasoning_rate_key = None
        reasoning_rate = None
        for candidate_rates in (applied_rates, rates):
            reasoning_rate_key = next(
                (
                    key
                    for key, value in candidate_rates.items()
                    if "reasoning" in key and isinstance(value, int | float) and not isinstance(value, bool)
                ),
                None,
            )
            if reasoning_rate_key is not None:
                reasoning_rate = candidate_rates[reasoning_rate_key]
                break
        reasoning_enabled = (
            model.get("reasoning_policy") == "mandatory-minimum"
            or (model.get("fixed_options") or {}).get("OPENROUTER_REASONING_ENABLED") == "true"
        )
        if (
            reasoning_rate is None
            and reasoning_enabled
            and (reasoning_tokens_value is not None or contract in PRIVATE_PANEL_CONTRACTS)
        ):
            reasoning_rate_key = "completion"
            reasoning_rate = applied_rates["completion"]
        reasoning_tokens = 0
        if reasoning_rate is not None:
            if (
                not isinstance(reasoning_tokens_value, int)
                or isinstance(reasoning_tokens_value, bool)
                or reasoning_tokens_value < 0
            ):
                raise ValueError(
                    "planning_assumptions.expected_internal_reasoning_tokens_per_decision "
                    f"must be a non-negative integer when {model_name} has internal-reasoning pricing"
                )
            reasoning_tokens = reasoning_tokens_value

        per_decision_cost = (
            input_tokens * _decimal(applied_rates["prompt"])
            + output_tokens * _decimal(applied_rates["completion"])
            + reasoning_tokens * _decimal(reasoning_rate or 0)
        )
        panel_cost = panel_decisions_per_model * per_decision_cost
        smoke_cost = smoke_decisions_per_run * per_decision_cost
        fixed_options = {
            **(models_config.get("shared_fixed_options") or {}),
            **(model.get("fixed_options") or {}),
        }
        repair_attempts = int(fixed_options.get("GM_BENCH_PROTOCOL_REPAIR_ATTEMPTS", 0))
        if repair_attempts < 0:
            raise ValueError("GM_BENCH_PROTOCOL_REPAIR_ATTEMPTS must be non-negative")
        maximum_calls_per_decision = calls_per_decision_limit * (1 + repair_attempts)
        maximum_panel_calls = panel_decisions_per_model * maximum_calls_per_decision
        maximum_smoke_calls = smoke_decisions_per_run * maximum_calls_per_decision
        protocol_max_panel_cost = panel_cost * maximum_calls_per_decision
        protocol_max_smoke_cost = smoke_cost * maximum_calls_per_decision
        panel_costs.append(panel_cost)
        smoke_costs.append(smoke_cost)
        protocol_max_panel_costs.append(protocol_max_panel_cost)
        protocol_max_smoke_costs.append(protocol_max_smoke_cost)
        protocol_max_panel_calls += maximum_panel_calls
        protocol_max_smoke_calls += maximum_smoke_calls
        row = {
            "experiment_id": model["id"],
            "model": model_name,
            "cost_per_decision_usd": float(per_decision_cost),
            "panel_calls": panel_decisions_per_model,
            "panel_cost_usd": float(panel_cost),
            "smoke_calls": smoke_decisions_per_run,
            "smoke_cost_usd": float(smoke_cost),
            "maximum_api_calls_per_decision": maximum_calls_per_decision,
            "protocol_maximum_panel_calls": maximum_panel_calls,
            "protocol_maximum_panel_cost_usd": float(protocol_max_panel_cost),
            "protocol_maximum_smoke_calls": maximum_smoke_calls,
            "protocol_maximum_smoke_cost_usd": float(protocol_max_smoke_cost),
            "applied_prompt_rate_usd": float(_decimal(applied_rates["prompt"])),
            "applied_completion_rate_usd": float(_decimal(applied_rates["completion"])),
            "internal_reasoning_tokens_per_decision": reasoning_tokens,
            "applied_internal_reasoning_rate_usd": float(_decimal(reasoning_rate or 0)),
        }
        if reasoning_rate_key is not None:
            row["internal_reasoning_billing_basis"] = reasoning_rate_key
        runtime_seconds = runtime_by_model.get(model_name)
        if isinstance(runtime_seconds, int | float) and runtime_seconds > 0:
            row["observed_api_seconds_per_decision"] = runtime_seconds
            observed_latency[model_name] = runtime_seconds
        rows.append(row)

    panel_cost = sum(panel_costs, Decimal())
    smoke_cost = sum(smoke_costs, Decimal())
    total_cost = panel_cost + smoke_cost
    protocol_max_panel_cost = sum(protocol_max_panel_costs, Decimal())
    protocol_max_smoke_cost = sum(protocol_max_smoke_costs, Decimal())
    protocol_max_total_cost = protocol_max_panel_cost + protocol_max_smoke_cost
    contingency = _decimal(assumptions["cost_contingency_multiplier"])
    # "Complete" only once every currently registered model (not just a subset
    # left over from a prior registry) has an observation; otherwise stay
    # pending so a partial refresh can't be mistaken for full coverage.
    runtime_complete = bool(models) and {model["model"] for model in models} <= set(observed_latency)
    runtime_status = RUNTIME_STATUS_COMPLETE if runtime_complete else RUNTIME_STATUS_PENDING
    runtime_note = RUNTIME_NOTE_COMPLETE if runtime_complete else RUNTIME_NOTE_PENDING
    return {
        "schema_version": 3,
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
            "internal_reasoning_tokens_per_decision": reasoning_tokens_value,
            "cost_contingency_multiplier": float(contingency),
            "rates_are_per_token": bool(pricing["rates_are_per_token"]),
            "panel_preset": "leaderboard",
            "panel_seed_count": panel_seed_count,
            "panel_seasons": int(leaderboard["seasons"]),
            "panel_repeats": repeats,
            "phase_count": len(PHASES),
            "smoke_preset": "smoke",
            "smoke_seed_count": len(smoke["seeds"]),
            "smoke_seasons": int(smoke["seasons"]),
            "serial_workers": 1,
            "planning_forecast_call_semantics": (
                "One response budget per decision window. This is a planning forecast, not a worst-case call count."
            ),
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
        "protocol_maximum": {
            **(
                {
                    "max_interaction_rounds_per_decision": MAX_INTERACTION_ROUNDS,
                    "description": (
                        "Maximum provider-call multiplicity allowed by the protocol, including every "
                        "configured repair. Token costs still use the committed per-call planning token "
                        "bounds; the publication runner's dynamic pre-call guard is the operator-ceiling "
                        "enforcement mechanism."
                    ),
                }
                if pre_v6_lane
                else {
                    "paid_calls_per_decision": V6_PAID_CALLS_PER_DECISION,
                    # Kept for comparison with pre-v6 plans, which budgeted five
                    # rounds per decision. It no longer bounds a paid lane.
                    "pre_v6_max_interaction_rounds_per_decision": MAX_INTERACTION_ROUNDS,
                    "description": (
                        "Maximum provider-call multiplicity allowed by the v6 protocol: one paid call per "
                        "decision phase plus every configured repair. Token costs still use the committed "
                        "per-call planning token bounds; the publication runner's dynamic pre-call guard is "
                        "the operator-ceiling enforcement mechanism."
                    ),
                }
            ),
            "panel_calls": protocol_max_panel_calls,
            "smoke_calls": protocol_max_smoke_calls,
            "total_calls": protocol_max_panel_calls + protocol_max_smoke_calls,
            "costs_usd": {
                "panel": float(protocol_max_panel_cost),
                "smoke": float(protocol_max_smoke_cost),
                "total_unrounded": float(protocol_max_total_cost),
                "total_with_contingency": float(protocol_max_total_cost * contingency),
            },
        },
        "models": rows,
        "costs_usd": {
            "panel": float(panel_cost),
            "smoke": float(smoke_cost),
            "total_unrounded": float(total_cost),
            "total_with_1_2x_contingency": float(total_cost * contingency),
        },
        "runtime": {
            "status": runtime_status,
            "note": runtime_note,
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
