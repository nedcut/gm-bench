from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.estimate_publication_cost import RUNTIME_NOTE_COMPLETE, RUNTIME_STATUS_COMPLETE, estimate


def _committed_inputs() -> tuple[dict, dict, dict]:
    models = json.loads(Path("config/sota_v2_models.json").read_text())
    lane = json.loads(Path("config/sota_v2_lane.json").read_text())
    pricing = json.loads(Path("config/openrouter_pricing_snapshot.json").read_text())
    return models, lane, pricing


def _v3_inputs() -> tuple[dict, dict, dict]:
    models = json.loads(Path("config/sota_v3_models.json").read_text())
    lane = json.loads(Path("config/sota_v3_lane.json").read_text())
    pricing = json.loads(Path("config/sota_v3_pricing_snapshot.json").read_text())
    return models, lane, pricing


def test_fixed_panel_and_smoke_call_counts() -> None:
    result = estimate(*_committed_inputs())

    assert len(result["models"]) == 10
    assert result["calls"] == {
        "model_count": 10,
        "panel_decisions_per_model": 480,
        "panel_calls": 4_800,
        "smoke_runs": 10,
        "smoke_decisions_per_run": 4,
        "smoke_calls": 40,
        "total_calls": 4_840,
    }


def test_v3_cost_plan_uses_registered_private_seed_count() -> None:
    result = estimate(*_v3_inputs())

    assert result["assumptions"]["panel_seed_count"] == 15
    assert result["assumptions"]["panel_repeats"] == 1
    assert result["calls"]["panel_decisions_per_model"] == 300
    assert result["calls"]["panel_calls"] == 2_400
    assert result["calls"]["total_calls"] == 2_432
    assert result["costs_usd"]["total_unrounded"] == pytest.approx(79.1216257024)
    assert result["costs_usd"]["total_with_1_2x_contingency"] == pytest.approx(94.94595084288)


def test_costs_sum_unrounded_rows_before_contingency() -> None:
    result = estimate(*_committed_inputs())
    rows = result["models"]
    costs = result["costs_usd"]
    exact_panel = sum(row["panel_cost_usd"] for row in rows)
    exact_smoke = sum(row["smoke_cost_usd"] for row in rows)

    assert costs["panel"] == pytest.approx(exact_panel)
    assert costs["smoke"] == pytest.approx(exact_smoke)
    assert costs["total_unrounded"] == pytest.approx(exact_panel + exact_smoke)
    cents_first_total = sum(round(row["panel_cost_usd"], 2) for row in rows) + sum(
        round(row["smoke_cost_usd"], 2) for row in rows
    )
    assert costs["total_unrounded"] != pytest.approx(cents_first_total)
    assert costs["total_with_1_2x_contingency"] == pytest.approx(costs["total_unrounded"] * 1.2)


def test_runtime_is_complete_once_every_registered_model_has_a_smoke_observation() -> None:
    result = estimate(*_committed_inputs())
    runtime = result["runtime"]

    assert runtime["status"] == RUNTIME_STATUS_COMPLETE == "complete-from-accepted-smokes"
    assert runtime["note"] == RUNTIME_NOTE_COMPLETE
    assert "4,096" in runtime["observation_source"]
    assert "2026-07-17" in runtime["observation_source"]
    model_names = {row["model"] for row in result["models"]}
    assert set(runtime["observed_api_seconds_per_decision_by_model"]) == model_names
    rows_with_latency = {
        row["model"]: row["observed_api_seconds_per_decision"]
        for row in result["models"]
        if "observed_api_seconds_per_decision" in row
    }
    assert rows_with_latency == runtime["observed_api_seconds_per_decision_by_model"]


def test_model_specific_reasoning_and_long_context_rates_are_applied() -> None:
    models, lane, pricing = _committed_inputs()
    models = copy.deepcopy(models)
    lane = copy.deepcopy(lane)
    pricing = copy.deepcopy(pricing)
    model_name = models["models"][0]["model"]

    lane["output_token_cap"] = 20
    models["output_token_cap"] = 20
    pricing["planning_assumptions"]["input_tokens_per_decision"] = 100
    pricing["planning_assumptions"]["expected_output_tokens_per_decision"] = 20
    pricing["planning_assumptions"]["expected_internal_reasoning_tokens_per_decision"] = 30
    pricing["models"][model_name] = {
        "prompt": 0.01,
        "completion": 0.02,
        "internal_reasoning": 0.03,
        "long_context_override": {
            "min_prompt_tokens": 100,
            "prompt": 0.04,
            "completion": 0.05,
        },
    }

    result = estimate(models, lane, pricing)
    row = next(item for item in result["models"] if item["model"] == model_name)

    assert row["cost_per_decision_usd"] == pytest.approx(100 * 0.04 + 20 * 0.05 + 30 * 0.03)
    assert row["applied_prompt_rate_usd"] == pytest.approx(0.04)
    assert row["applied_completion_rate_usd"] == pytest.approx(0.05)
    assert row["internal_reasoning_tokens_per_decision"] == 30
    assert row["applied_internal_reasoning_rate_usd"] == pytest.approx(0.03)


def test_internal_reasoning_price_requires_an_explicit_token_assumption() -> None:
    models, lane, pricing = _committed_inputs()
    pricing = copy.deepcopy(pricing)
    model_name = models["models"][0]["model"]
    pricing["models"][model_name]["internal_reasoning"] = 0.03

    with pytest.raises(ValueError, match="expected_internal_reasoning_tokens_per_decision"):
        estimate(models, lane, pricing)
