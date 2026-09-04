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

    assert result["assumptions"]["panel_seed_count"] == 16
    assert result["assumptions"]["panel_repeats"] == 1
    assert result["calls"]["panel_decisions_per_model"] == 320
    assert result["calls"]["panel_calls"] == 2_560
    assert result["calls"]["total_calls"] == 2_592
    # `calls` is the one-response-per-window planning forecast. The pre-v6
    # protocol could actually make five interaction calls, each with one repair,
    # so this frozen plan exposes that 10x maximum instead of presenting 2,592
    # as a worst-case API-call count. (The v6 lane is priced at one paid call
    # per decision instead; see test_v6_lane_prices_one_paid_call_per_decision.)
    assert result["protocol_maximum"]["max_interaction_rounds_per_decision"] == 5
    assert result["protocol_maximum"]["total_calls"] == 25_920
    # Recosted 2026-08-06 for amendment-3, which withdrew Gemini 3.6 Flash and
    # Grok 4.5 -- the only two mandatory-reasoning routes -- leaving eight
    # uniformly reasoning-disabled models. The call count falls 3,240 -> 2,592
    # and, because the withdrawn pair were also the two priciest rows (they
    # billed internal reasoning at the completion rate on top of output), the
    # reservation falls further than the call count alone implies: $127.29 ->
    # $73.40 against a ceiling lowered $150 -> $100.
    assert result["costs_usd"]["total_unrounded"] == pytest.approx(61.169375232)
    assert result["costs_usd"]["total_with_1_2x_contingency"] == pytest.approx(73.4032502784)
    assert result["protocol_maximum"]["costs_usd"]["total_with_contingency"] == pytest.approx(734.032502784)
    # The cohort is now uniformly reasoning-disabled; no row may bill internal
    # reasoning. This is the cost-side statement of the amendment's whole point.
    assert [row["model"] for row in result["models"] if row["internal_reasoning_tokens_per_decision"]] == []


def test_v6_lane_prices_one_paid_call_per_decision() -> None:
    """The v6 lane's worst case is 20 calls a seed, not 100.

    Pricing the v6 panel off MAX_INTERACTION_ROUNDS reserved five times the
    calls the protocol can now make, which is not a conservative plan so much as
    a wrong one: it hides how much of the ceiling the real lane uses.
    """
    models = json.loads(Path("config/sota_v5_models.json").read_text())
    lane = json.loads(Path("config/sota_v5_lane.json").read_text())
    pricing = json.loads(Path("config/sota_v5_pricing_snapshot.json").read_text())
    result = estimate(models, lane, pricing)

    assert result["protocol_maximum"]["paid_calls_per_decision"] == 1
    # The pre-v6 figure survives, labelled, so an older plan stays readable.
    assert result["protocol_maximum"]["pre_v6_max_interaction_rounds_per_decision"] == 5
    # 20 calls per five-season seed across the 29-seed v6 panel. The registry
    # now configures zero protocol repairs, so the plan and the protocol
    # maximum are the same number: v6 buys no retry, and there is nothing left
    # to multiply by.
    assert result["calls"]["panel_decisions_per_model"] == 580
    assert result["calls"]["panel_calls"] == 16 * 580
    assert result["protocol_maximum"]["total_calls"] == result["calls"]["total_calls"]


def test_v4_cost_plan_uses_the_frozen_private_seed_count() -> None:
    models, lane, pricing = _v3_inputs()
    models = copy.deepcopy(models)
    lane = copy.deepcopy(lane)
    models["contract"] = "sota-v4"
    lane["contract"] = "sota-v4"
    lane["seed_panel"]["count"] = 12

    result = estimate(models, lane, pricing)

    assert result["assumptions"]["panel_seed_count"] == 12
    assert result["calls"]["panel_decisions_per_model"] == 240


def test_v4_cost_plan_requires_private_panel_metadata() -> None:
    models, lane, pricing = _v3_inputs()
    models = copy.deepcopy(models)
    lane = copy.deepcopy(lane)
    models["contract"] = "sota-v4"
    lane["contract"] = "sota-v4"
    lane.pop("seed_panel")

    with pytest.raises(ValueError, match="sota-v4 fixed-panel estimate requires seed_panel metadata"):
        estimate(models, lane, pricing)


def test_the_committed_plan_fits_under_the_committed_ceiling() -> None:
    """The planning forecast and hard cap must not drift apart silently.

    These are two committed numbers in two different files, and on 2026-08-04
    they crossed: pinning undiscounted list rates moved the reservation to
    $127.29 against a $120.00 ceiling, so the committed plan could not reasonably
    run.  Nothing caught it, because nothing compared them.

    Adding a model, substituting a route onto a pricier host, or a provider
    ending a discount all move the forecast. Any of them silently breaching
    the ceiling should fail here, at zero cost, rather than at the point
    someone tries to authorize a run.
    """
    protocol = json.loads(Path("config/sota_v3_publication_protocol.json").read_text())
    ceiling = protocol["budget_policy"]["operator_ceiling_usd"]
    forecast = estimate(*_v3_inputs())["costs_usd"]["total_with_1_2x_contingency"]

    assert isinstance(ceiling, (int, float)) and ceiling > 0
    assert forecast <= ceiling, (
        f"the committed planning forecast ${forecast:.2f} exceeds the committed operator ceiling "
        f"${ceiling:.2f}; raise the ceiling deliberately or reduce the plan"
    )


def test_the_committed_cost_artifact_matches_the_committed_configs() -> None:
    """A stale cost artifact is a reservation nobody recomputed.

    The runner reserves per cell from the pricing snapshot, but the artifact is
    what the readiness docs and the ceiling decision quote.  If someone edits a
    price or a route without regenerating it, the number people reason about
    stops describing the plan they would actually run.
    """
    committed = json.loads(Path("results/analysis/sota-v3-pre-smoke-cost-estimate.json").read_text())
    recomputed = estimate(*_v3_inputs())

    assert committed["costs_usd"] == pytest.approx(recomputed["costs_usd"])
    assert committed["calls"] == recomputed["calls"]
    # The timestamp is what tells a reader which snapshot the number describes,
    # so a stale one is its own defect even when the totals happen to agree.
    assert committed["pricing_checked_at_utc"] == recomputed["pricing_checked_at_utc"]
    committed_rows = {row["experiment_id"]: row for row in committed["models"]}
    recomputed_rows = {row["experiment_id"]: row for row in recomputed["models"]}
    assert set(committed_rows) == set(recomputed_rows)
    for experiment_id, row in recomputed_rows.items():
        assert committed_rows[experiment_id]["model"] == row["model"]
        assert committed_rows[experiment_id]["cost_per_decision_usd"] == pytest.approx(row["cost_per_decision_usd"])


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
    assert row["internal_reasoning_billing_basis"] == "internal_reasoning"


def test_v3_luna_uses_the_pinned_long_context_price_tier() -> None:
    models, lane, pricing = _v3_inputs()
    models = copy.deepcopy(models)
    pricing = copy.deepcopy(pricing)
    model_name = "openai/gpt-5.6-luna"
    models["models"] = [model for model in models["models"] if model["model"] == model_name]
    pricing["planning_assumptions"]["input_tokens_per_decision"] = 272_000

    result = estimate(models, lane, pricing)
    row = result["models"][0]

    assert row["model"] == model_name
    assert row["applied_prompt_rate_usd"] == pytest.approx(2e-7)
    assert row["applied_completion_rate_usd"] == pytest.approx(9e-7)


def test_internal_reasoning_price_requires_an_explicit_token_assumption() -> None:
    models, lane, pricing = _committed_inputs()
    pricing = copy.deepcopy(pricing)
    model_name = models["models"][0]["model"]
    pricing["models"][model_name]["internal_reasoning"] = 0.03

    with pytest.raises(ValueError, match="expected_internal_reasoning_tokens_per_decision"):
        estimate(models, lane, pricing)


def test_v3_reasoning_enabled_route_requires_an_explicit_token_assumption() -> None:
    """A reasoning-enabled route may never be costed as if reasoning were free.

    This used to pin the real Grok 4.5 row, but amendment-3 withdrew both
    mandatory-reasoning routes, which would have quietly turned the test
    vacuous -- the filter would select nothing and the guard would stop being
    exercised at all. The unpriced-reasoning trap is a property of the
    estimator, not of whoever happens to be in the cohort this month, so the
    route is synthetic and the test survives any future lineup change.
    """
    models, lane, pricing = _v3_inputs()
    models = copy.deepcopy(models)
    pricing = copy.deepcopy(pricing)
    reasoning_route = copy.deepcopy(models["models"][0])
    reasoning_route["reasoning_policy"] = "mandatory-minimum"
    reasoning_route["reasoning_effort"] = "minimal"
    models["models"] = [reasoning_route]
    pricing["planning_assumptions"].pop("expected_internal_reasoning_tokens_per_decision")

    with pytest.raises(ValueError, match="expected_internal_reasoning_tokens_per_decision"):
        estimate(models, lane, pricing)
