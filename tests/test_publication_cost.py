from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.estimate_publication_cost import RUNTIME_NOTE, RUNTIME_STATUS, estimate


def _committed_inputs() -> tuple[dict, dict, dict]:
    models = json.loads(Path("config/sota_v2_models.json").read_text())
    lane = json.loads(Path("config/sota_v2_lane.json").read_text())
    pricing = json.loads(Path("config/openrouter_pricing_snapshot.json").read_text())
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


def test_runtime_is_pending_with_latency_only_where_observed() -> None:
    result = estimate(*_committed_inputs())
    runtime = result["runtime"]
    observed = {
        "openai/gpt-5.6-luna": 1.981,
        "minimax/minimax-m3": 2.546,
        "qwen/qwen3.5-9b": 11.622,
    }

    assert runtime["status"] == RUNTIME_STATUS == "pending-smoke-telemetry"
    assert runtime["note"] == RUNTIME_NOTE
    assert "before approving the full panel" in runtime["note"]
    assert runtime["observed_api_seconds_per_decision_by_model"] == observed
    rows_with_latency = {
        row["model"]: row["observed_api_seconds_per_decision"]
        for row in result["models"]
        if "observed_api_seconds_per_decision" in row
    }
    assert rows_with_latency == observed
