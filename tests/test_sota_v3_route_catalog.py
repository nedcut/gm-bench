"""Integrity checks for the zero-spend sota-v3 public route-catalog freeze."""

from __future__ import annotations

import json
from pathlib import Path

import scripts.run_publication_matrix as publication_runner
from gm_bench.publication import publication_execution_issues

CONFIG = Path("config")


def _read(name: str) -> dict:
    payload = json.loads((CONFIG / name).read_text())
    assert isinstance(payload, dict)
    return payload


def test_v3_catalog_freezes_exact_balanced_cohort_without_unlocking_execution() -> None:
    registry = _read("sota_v3_models.json")

    models = registry["models"]
    assert len(models) == 10
    assert len({model["id"] for model in models}) == 10
    assert len({(model["model"], model["endpoint_tag"]) for model in models}) == 10
    assert {model["cohort"] for model in models} == {"frontier-proprietary", "open-weight"}
    assert sum(model["cohort"] == "frontier-proprietary" for model in models) == 4
    assert sum(model["cohort"] == "open-weight" for model in models) == 6

    identities = {model["model"] for model in models}
    assert "openai/gpt-5.6-luna" in identities
    assert "openai/gpt-5.6-luna-pro" not in identities
    assert "deepseek/deepseek-v4-flash-0731" in identities
    assert "tencent/hy3" in identities
    # Evaluated for the tenth slot, ineligible at the frozen snapshot: no
    # healthy route advertises response_format under require-parameters.
    assert "thinkingmachines/inkling-small" not in identities
    assert "google/gemini-3.6-flash" in identities
    assert "google/gemini-3.5-flash" not in identities
    assert "mistralai/mistral-medium-3-5" in identities
    assert "meta/muse-spark-1.1" not in identities

    assert registry["catalog_snapshot_status"] == "frozen-public-metadata-only"
    assert registry["selection_status"] == "route-preflight-ready"
    assert registry["selection_frozen_at_utc"] is None
    assert registry["catalog_checked_at_utc"]
    assert set(registry["required_smokes"]) == {model["id"] for model in models}
    assert registry["output_token_cap"] == 4_096
    assert registry["output_budget_status"] == "provisional-pre-smoke-validation"
    acceptance = registry["exact_route_acceptance"]
    assert acceptance["status"] == "unresolved"
    assert set(acceptance["entries"]) == {model["id"] for model in models}
    for entry in acceptance["entries"].values():
        assert entry["authenticated"] is False
        assert entry["route_identity_sha256"] is None
        assert entry["privacy_acceptance"]["status"] == "unresolved"
        assert not any(
            entry["privacy_acceptance"][field]
            for field in (
                "data_collection_policy_accepted",
                "retention_policy_accepted",
                "training_use_policy_accepted",
                "zero_data_retention_policy_accepted",
            )
        )
    for key in (
        "spend_authorized",
        "route_preflight_authorized",
        "panel_execution_authorized",
        "publication_authorized",
    ):
        assert registry[key] is False, key


def test_v3_catalog_pins_routes_parameters_reasoning_and_exact_route_prices() -> None:
    registry = _read("sota_v3_models.json")
    pricing = _read("sota_v3_pricing_snapshot.json")
    rates = pricing["models"]

    for model in registry["models"]:
        assert model["upstream_provider_slug"] == model["endpoint_tag"]
        assert model["endpoint_name"].endswith(model["canonical_slug"])
        assert model["catalog_route_status"] == 0
        assert model["catalog_uptime_last_30m"] > 0
        assert {"reasoning", "max_tokens", "response_format"} <= set(model["catalog_supported_parameters"])
        assert model["reasoning_policy"] in {
            "disabled",
            "mandatory-minimum",
        }

        route_rate = rates[model["model"]]
        assert route_rate["provider_slug"] == model["endpoint_tag"]
        assert route_rate["endpoint_name"] == model["endpoint_name"]
        assert route_rate["prompt"] >= 0
        assert route_rate["completion"] >= 0

        reasoning = model["catalog_reasoning"]
        if reasoning.get("mandatory"):
            assert model["reasoning_policy"] == "mandatory-minimum"
            assert model["fixed_options"]["OPENROUTER_REASONING_ENABLED"] == "true"
            assert model["reasoning_effort"] == reasoning["supported_efforts"][-1]
        else:
            assert model["reasoning_policy"] == "disabled"
            assert model["fixed_options"]["OPENROUTER_REASONING_ENABLED"] == "false"
            assert "OPENROUTER_REASONING_EFFORT" in model["absent_options"]

    grok = next(model for model in registry["models"] if model["model"] == "x-ai/grok-4.5")
    assert grok["endpoint_tag"] == "xai/zdr"
    assert pricing["status"] == "catalog-frozen-public-metadata-only"
    assert pricing["checked_at_utc"] == registry["catalog_checked_at_utc"]
    assert pricing["spend_authorized"] is False
    assert pricing["route_preflight_authorized"] is False
    assert pricing["smoke_execution_authorized"] is False
    assert pricing["panel_execution_authorized"] is False
    assert pricing["publication_authorized"] is False
    assert pricing["runtime_observations"]["source"] is None
    assumptions = pricing["planning_assumptions"]
    assert assumptions["input_tokens_per_decision"] == 8_000
    assert assumptions["expected_output_tokens_per_decision"] == 4_096
    assert assumptions["expected_internal_reasoning_tokens_per_decision"] == 4_096
    assert assumptions["cost_contingency_multiplier"] == 1.2
    assert assumptions["runtime_contingency_multiplier"] == 1.2
    assert "pre-smoke" in assumptions["basis"]


def test_selected_catalog_models_match_runner_exact_route_shape() -> None:
    registry = _read("sota_v3_models.json")

    # Exercise the runner's executable enum and exact-route schema directly,
    # without weakening or bypassing the separate authorization gates.
    publication_runner._validate_models(
        registry["models"],
        expected_provider=registry["provider"],
    )


def test_completed_route_preflight_cannot_unlock_any_paid_phase() -> None:
    """The zero-call phase is open; every phase that spends money is not.

    `route_preflight_authorized` was granted on 2026-08-03 and the preflight
    has run, so this no longer asserts that *nothing* is unlocked.  It asserts
    the distinction the lane is built on: opening the zero-completion-call
    probe must leave the paid gates exactly where they were.
    """
    lane = _read("sota_v3_lane.json")
    registry = _read("sota_v3_models.json")
    protocol = _read("sota_v3_publication_protocol.json")
    pricing = _read("sota_v3_pricing_snapshot.json")
    manifest = _read("sota_v3_smoke_manifest.json")

    # Granted: the phase that provably cannot call a model or reserve spend.
    assert lane["route_preflight_authorized"] is True
    # Not granted: everything that can.
    assert lane["spend_authorized"] is False
    assert lane["smoke_execution_authorized"] is False
    assert lane["panel_execution_authorized"] is False
    assert lane["publication_authorized"] is False
    assert protocol["budget_policy"]["spend_authorized"] is False
    assert protocol["publication_authorized"] is False
    assert manifest["accepted_for_panel"] is False
    assert pricing["route_preflight_authorized"] is False

    for phase in ("smoke", "panel"):
        issues = publication_execution_issues(
            lane,
            registry,
            manifest,
            phase=phase,
            protocol=protocol,
            pricing=pricing,
        )
        assert issues, f"completed route preflight unexpectedly unlocked {phase}"

    # Preflight is deliberately clear now; a passing probe is not a licence to
    # spend, so the registry must still be unfrozen and acceptance unresolved.
    assert (
        publication_execution_issues(
            lane,
            registry,
            manifest,
            phase="route-preflight",
            protocol=protocol,
            pricing=pricing,
        )
        == []
    )
    assert registry["selection_status"] == "route-preflight-ready"
    assert registry["selection_frozen_at_utc"] is None

    smoke_issues = publication_execution_issues(
        lane,
        registry,
        manifest,
        phase="smoke",
        protocol=protocol,
        pricing=pricing,
    )
    assert "sota-v3 exact-route acceptance status is not accepted" in smoke_issues
    assert any("lacks authenticated route verification" in issue for issue in smoke_issues)
    assert any("privacy acceptance is unresolved" in issue for issue in smoke_issues)
