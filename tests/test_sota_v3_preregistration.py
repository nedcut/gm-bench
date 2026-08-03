"""Fail-closed checks for the provisional sota-v3 publication lane."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.run_publication_matrix as publication_runner
from gm_bench.contract import BENCHMARK_VERSION, contract_fingerprint
from gm_bench.publication import (
    SMOKE_MANIFEST_FORMAT,
    exact_sign_flip_feasibility,
    publication_execution_issues,
    v3_preregistration_coherence_issues,
)

CONFIG = Path("config")


def _read(name: str) -> dict:
    payload = json.loads((CONFIG / name).read_text())
    assert isinstance(payload, dict)
    return payload


def test_v3_lane_pins_current_contract_and_freezes_a_powered_allocation() -> None:
    lane = _read("sota_v3_lane.json")

    assert lane["contract"] == BENCHMARK_VERSION == "sota-v3"
    assert lane["contract_fingerprint"] == contract_fingerprint()
    assert lane["mechanics_status"] == "frozen-for-sota-v3-panel"
    assert "requires a new contract fingerprint" in lane["mechanics_change_policy"]
    assert lane["headline_lane"] == "api"
    assert lane["observation_profile"] == "compact"
    assert lane["session"] is False
    assert lane["preset"] == "leaderboard"
    assert lane["execution_profile_authority"] == "lane"
    assert lane["provider"] == "openrouter"
    # One repeat, not three: a candidate-minus-reference lift keeps its full seed
    # component, so at a fixed episode budget repeats only shrink within-seed
    # noise while seeds buy independent draws of what actually varies.
    assert lane["repeats"] == 1
    assert lane["panel_design_status"] == "frozen"
    candidate = lane["statistical_panel_design"]
    assert candidate["status"] == "frozen"
    assert candidate["historical_lift_variances"]["shared_seed"] == pytest.approx(3770.478399)
    assert candidate["evaluated_seed_range"] == [9, 16]
    assert candidate["evaluated_repeat_range"] == [1, 3]
    # The planning effect points the way the frozen sota-v2 evidence does: every
    # eligible model trailed pick-trader on every seed. A positive target would
    # power a reversal nothing in the evidence supports.
    assert candidate["claim_direction"] == "trails-reference"
    assert candidate["target_effect_score_points"] == -100
    selected = candidate["selected_allocation"]
    assert selected["seed_count"] == 16
    assert selected["repeats"] == 1
    assert selected["episodes_per_model"] == selected["seed_count"] * selected["repeats"] == 16
    feasibility = exact_sign_flip_feasibility(
        selected["seed_count"],
        candidate["holm_family_size"],
    )
    assert selected["minimum_exact_two_sided_sign_flip_p_value"] == feasibility["minimum_two_sided_p_value"]
    assert selected["holm_first_step_threshold_at_alpha_0_05"] == feasibility["holm_first_step_threshold"]
    assert selected["exact_sign_flip_holm_feasible"] is feasibility["feasible"] is True
    # The selection rule is a Wilson *lower* bound clearing the target, so the
    # allocation is only frozen if the conservative-sensitivity interval does.
    assert selected["sensitivity_power_wilson_ci95"][0] >= candidate["target_familywise_all_reject_power"]
    assert lane["seed_panel"] == {
        "status": "pending-authorized-generation",
        "name": None,
        "count": 16,
        "sha256": None,
    }
    assert lane["seed_panel"]["count"] == selected["seed_count"]
    # Seed identity stays unfrozen until a salted commitment hash is recorded.
    assert lane["seed_panel"]["sha256"] is None
    assert any("private panel" in blocker.lower() for blocker in lane["blockers"])
    assert lane["reference_agent"] == "pick-trader"
    assert lane["protocol_repair_attempts"] == 1
    assert lane["strict_fallback_required"] is True
    assert lane["model_registry"] == "config/sota_v3_models.json"
    assert lane["smoke_manifest"] == "config/sota_v3_smoke_manifest.json"
    assert lane["publication_protocol"] == "config/sota_v3_publication_protocol.json"
    assert lane["pricing_snapshot"] == "config/sota_v3_pricing_snapshot.json"
    assert lane["minimum_headline_models"] >= 8


def test_v3_registry_is_truthfully_provisional_and_contains_no_unverified_routes() -> None:
    lane = _read("sota_v3_lane.json")
    registry = _read("sota_v3_models.json")

    assert registry["contract"] == lane["contract"]
    assert registry["contract_fingerprint"] == lane["contract_fingerprint"]
    # route-preflight-ready is strictly weaker than frozen: it clears the
    # zero-call preflight readiness check and nothing else.  The registry is
    # still not frozen, so every paid phase stays locked.
    assert registry["selection_status"] == "route-preflight-ready"
    assert registry["selection_frozen_at_utc"] is None
    assert registry["catalog_snapshot_status"] == "frozen-public-metadata-only"
    assert registry["catalog_checked_at_utc"]
    assert len(registry["models"]) == len(registry["required_smokes"]) == 10
    assert set(registry["required_smokes"]) == {model["id"] for model in registry["models"]}
    assert registry["repeats"] == lane["repeats"] == 1
    assert registry["output_token_cap"] == lane["output_token_cap"] == 4096
    assert registry["output_budget_status"] == lane["output_budget_status"] == "provisional-pre-smoke-validation"
    assert registry["spend_authorized"] is False
    assert registry["panel_execution_authorized"] is False
    assert registry["unresolved_decisions"]
    assert registry["provider_policy"] == "openrouter-only"
    assert registry["shared_fixed_options"]["OPENROUTER_JSON_MODE"] == "true"
    assert registry["public_metadata_limitations"]
    assert any("privacy" in decision for decision in registry["unresolved_decisions"])


def test_v3_protocol_and_pricing_are_separate_and_fail_closed() -> None:
    lane = _read("sota_v3_lane.json")
    protocol = _read("sota_v3_publication_protocol.json")
    pricing = _read("sota_v3_pricing_snapshot.json")

    assert protocol["contract"] == pricing["contract"] == lane["contract"]
    assert protocol["contract_fingerprint"] == pricing["contract_fingerprint"] == lane["contract_fingerprint"]
    assert protocol["status"] == "provisional-pre-smoke"
    assert protocol["statistical_analysis_plan"]["status"] == "frozen"
    assert protocol["statistical_analysis_plan"]["analysis_mode"] == "reference-only"
    assert protocol["statistical_analysis_plan"]["inference_method"] == "exact-enumeration-sign-flip"
    assert protocol["statistical_analysis_plan"]["unit_of_inference"] == "seed"
    assert protocol["statistical_analysis_plan"]["primary_contrast"] == "paired lift versus pick-trader"
    assert protocol["statistical_analysis_plan"]["reference_agent"] == lane["reference_agent"] == "pick-trader"
    assert protocol["statistical_analysis_plan"]["multiplicity_method"] == "holm-bonferroni"
    assert protocol["statistical_analysis_plan"]["alpha"] == 0.05
    assert protocol["statistical_analysis_plan"]["holm_family_size"] == 10
    assert protocol["statistical_analysis_plan"]["power_model"]["historical_shared_seed_variance"] == pytest.approx(
        3770.478399
    )
    assert protocol["statistical_analysis_plan"]["power_model"]["selected_sensitivity_power"] == 0.8488
    assert protocol["statistical_analysis_plan"]["power_model"]["selected_allocation"] == "16 seeds x 1 repeat"
    assert protocol["statistical_analysis_plan"]["claim_direction"] == "trails-reference"
    assert protocol["statistical_analysis_plan"]["target_effect_score_points"] == -100
    # The lane and the protocol carry separate copies of the design; they must agree.
    assert (
        protocol["statistical_analysis_plan"]["target_effect_score_points"]
        == lane["statistical_panel_design"]["target_effect_score_points"]
    )
    assert protocol["panel_design"]["status"] == lane["panel_design_status"]
    assert protocol["budget_policy"]["spend_authorized"] is False
    assert pricing["status"] == "catalog-frozen-public-metadata-only"
    assert pricing["checked_at_utc"]
    assert len(pricing["models"]) == 10
    assert pricing["spend_authorized"] is False


def test_v3_preregistration_fails_closed_before_smoke_or_panel_spend() -> None:
    lane = _read("sota_v3_lane.json")
    registry = _read("sota_v3_models.json")
    manifest = _read("sota_v3_smoke_manifest.json")

    # The design amendment freezes an allocation; it authorizes nothing. Both
    # gates are allowlists against the literal "frozen", so a status that merely
    # records progress still locks provider execution.
    assert lane["preregistration_status"] == "provisional-pre-smoke"
    assert lane["preregistration_status"] != "frozen"
    assert lane["panel_design_status"] == "frozen"
    assert lane["output_budget_status"] == "provisional-pre-smoke-validation"
    assert lane["output_token_cap"] == 4096
    assert lane["cap_pressure_threshold_tokens"] == 3072
    assert lane["fallback_output_token_cap"] == 8192
    assert "invalidate every v3 smoke" in lane["output_policy_amendment_rule"]
    assert lane["reasoning_policy"] == "catalog-pinned-pending-live-route-verification"
    assert lane["spend_authorized"] is False
    assert lane["route_preflight_authorized"] is False
    assert lane["smoke_execution_authorized"] is False
    assert lane["panel_execution_authorized"] is False
    assert lane["publication_authorized"] is False
    assert lane["blockers"]

    assert manifest["format"] == SMOKE_MANIFEST_FORMAT
    assert manifest["contract"] == lane["contract"]
    assert manifest["contract_fingerprint"] == lane["contract_fingerprint"]
    assert manifest["status"] == "not-started"
    assert manifest["accepted_for_panel"] is False
    assert manifest["entries"] == {}

    # A selected cohort without a frozen seed commitment or smokes is incomplete.
    assert len(registry["models"]) == lane["minimum_headline_models"]
    smoke_gate_complete = (
        bool(registry["models"])
        and set(registry["required_smokes"]) == {model["id"] for model in registry["models"]}
        and set(registry["required_smokes"]) == set(manifest["entries"])
        and manifest["accepted_for_panel"] is True
    )
    assert smoke_gate_complete is False


@pytest.mark.parametrize("invalid_cap", [None, "4096", True, 0])
def test_v3_preregistration_reports_invalid_caps_without_crashing(invalid_cap: object) -> None:
    lane = _read("sota_v3_lane.json")
    lane["output_token_cap"] = invalid_cap

    issues = v3_preregistration_coherence_issues(
        lane,
        _read("sota_v3_models.json"),
        _read("sota_v3_publication_protocol.json"),
        _read("sota_v3_pricing_snapshot.json"),
        _read("sota_v3_smoke_manifest.json"),
    )

    assert "sota-v3 provisional output_token_cap must be a positive integer" in issues
    assert "sota-v3 cap-pressure threshold must be between zero and the provisional cap" in issues
    assert "sota-v3 fallback output cap must exceed the provisional cap" in issues


def test_exact_sign_flip_holm_feasibility_uses_seed_count_not_episode_count() -> None:
    eight_seeds = exact_sign_flip_feasibility(8, 8)
    assert eight_seeds["minimum_two_sided_p_value"] == 2 / 2**8
    assert eight_seeds["holm_first_step_threshold"] == pytest.approx(0.05 / 8)
    assert eight_seeds["feasible"] is False

    nine_seeds = exact_sign_flip_feasibility(9, 8)
    assert nine_seeds["minimum_two_sided_p_value"] == 2 / 2**9
    assert nine_seeds["feasible"] is True


def test_blocked_v3_state_cannot_drift_into_partial_authorization() -> None:
    lane = _read("sota_v3_lane.json")
    registry = _read("sota_v3_models.json")
    manifest = _read("sota_v3_smoke_manifest.json")

    incomplete = (
        lane["preregistration_status"] != "frozen"
        or registry["selection_status"] != "frozen"
        or not registry["models"]
        or manifest["accepted_for_panel"] is not True
        or set(registry["required_smokes"]) != set(manifest["entries"])
    )
    assert incomplete
    assert not any(
        (
            lane["spend_authorized"],
            lane["smoke_execution_authorized"],
            lane["panel_execution_authorized"],
            lane["publication_authorized"],
            registry["spend_authorized"],
            registry["panel_execution_authorized"],
        )
    )


@pytest.mark.parametrize("mode", ["--dry-run", "--preflight-only"])
def test_runner_rejects_provisional_v3_smoke_before_provider_access(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mode: str,
) -> None:
    provider_access: list[str] = []
    monkeypatch.setattr(
        publication_runner,
        "_validate_openrouter_endpoint",
        lambda _cell, _env: provider_access.append("endpoint"),
    )
    monkeypatch.setattr(
        publication_runner.subprocess,
        "run",
        lambda *_args, **_kwargs: provider_access.append("subprocess"),
    )

    with pytest.raises(SystemExit) as exc_info:
        publication_runner.main(["smoke", "--contract", "sota-v3", mode])

    assert exc_info.value.code == 2
    assert "sota-v3 lane is provisional-pre-smoke; provider execution is locked" in capsys.readouterr().err
    assert provider_access == []


def test_runner_keeps_historical_v2_blocked_under_current_source(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    provider_access: list[str] = []
    monkeypatch.setattr(
        publication_runner,
        "_validate_openrouter_endpoint",
        lambda _cell, _env: provider_access.append("endpoint"),
    )
    monkeypatch.setattr(
        publication_runner.subprocess,
        "run",
        lambda *_args, **_kwargs: provider_access.append("subprocess"),
    )

    with pytest.raises(SystemExit) as exc_info:
        publication_runner.main(
            [
                "smoke",
                "--contract",
                "sota-v2",
                "--max-spend-usd",
                "1",
            ]
        )

    assert exc_info.value.code == 2
    assert "frozen historical evidence ('sota-v2'/'sota-v2')" in capsys.readouterr().err
    assert provider_access == []


@pytest.mark.parametrize("mode", ["--dry-run", "--preflight-only"])
def test_runner_requires_explicit_contract_before_v2_preflight_can_run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mode: str,
) -> None:
    provider_access: list[str] = []
    monkeypatch.setattr(
        publication_runner,
        "_validate_openrouter_endpoint",
        lambda _cell, _env: provider_access.append("endpoint"),
    )
    monkeypatch.setattr(
        publication_runner.subprocess,
        "run",
        lambda *_args, **_kwargs: provider_access.append("subprocess"),
    )

    with pytest.raises(SystemExit) as exc_info:
        publication_runner.main(["smoke", mode])

    assert exc_info.value.code == 2
    assert "smoke requires an explicit --contract" in capsys.readouterr().err
    assert provider_access == []


def test_route_preflight_readiness_unlocks_nothing_that_costs_money() -> None:
    """`route-preflight-ready` must buy exactly one thing: the zero-call probe.

    This is the whole safety argument for making the flip before route
    preflight has run, so it is asserted rather than described.  The registry
    is deliberately *not* `frozen`; every paid phase must remain as locked as
    it was while the registry was `provisional-blocked`.
    """
    lane = _read("sota_v3_lane.json")
    registry = _read("sota_v3_models.json")
    protocol = _read("sota_v3_publication_protocol.json")
    pricing = _read("sota_v3_pricing_snapshot.json")
    manifest = _read("sota_v3_smoke_manifest.json")

    def issues(reg: dict, phase: str) -> list[str]:
        return publication_execution_issues(lane, reg, manifest, phase=phase, protocol=protocol, pricing=pricing)

    # The owner's separate zero-call authorization is the only thing left.
    assert issues(registry, "route-preflight") == [
        "zero-call route preflight is locked while route_preflight_authorized is false"
    ]

    blocked = dict(registry, selection_status="provisional-blocked")
    for phase in ("smoke", "panel"):
        assert issues(registry, phase) == issues(blocked, phase)
        assert "provider execution is locked until the model registry is frozen" in issues(registry, phase)
