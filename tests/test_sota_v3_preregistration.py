"""Fail-closed checks for the provisional sota-v3 publication lane."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.run_publication_matrix as publication_runner
from gm_bench.contract import SOTA_V3_CONTRACT, contract_fingerprint
from gm_bench.publication import (
    SMOKE_MANIFEST_FORMAT,
    exact_sign_flip_feasibility,
    publication_execution_issues,
    v3_preregistration_coherence_issues,
    v3_route_acceptance_issues,
)
from scripts.sota_v3_rehearsal import v3_cross_file_coherence_issues

CONFIG = Path("config")


def _read(name: str) -> dict:
    payload = json.loads((CONFIG / name).read_text())
    assert isinstance(payload, dict)
    return payload


def test_v3_lane_pins_frozen_contract_and_freezes_a_powered_allocation() -> None:
    lane = _read("sota_v3_lane.json")

    assert lane["contract"] == SOTA_V3_CONTRACT["benchmark_version"] == "sota-v3"
    assert lane["contract_fingerprint"] == SOTA_V3_CONTRACT["contract_fingerprint"]
    # The lane is frozen at the fingerprint its panel was bought under. The
    # live engine has since moved (v6 draft lottery + pick identity), so the
    # lane is intentionally no longer runnable on main: old studies live in
    # tags and artifacts, and the frozen pin below is the audit anchor.
    assert lane["contract_fingerprint"] == "247e12fe5a7d4f5b"
    assert lane["contract_fingerprint"] != contract_fingerprint()
    assert lane["mechanics_status"] == "frozen-for-sota-v3-panel"
    assert "requires a new contract fingerprint" in lane["mechanics_change_policy"]
    assert lane["design_amendment"]["amendment_id"] == "sota-v3-design-amendment-4"
    assert lane["design_amendment"]["status"] == "pre-data"
    assert lane["design_amendment"]["record"] == "docs/PUBLISH_READINESS.md#decision-log"
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
    assert lane["seed_panel"]["status"] == "frozen"
    assert lane["seed_panel"]["name"] == "private-env"
    assert lane["seed_panel"]["count"] == 16
    assert len(lane["seed_panel"]["sha256"]) == 64
    assert len(lane["seed_panel"]["hiding_commitment_sha256"]) == 64
    assert lane["seed_panel"]["seed_values_included"] is False
    assert lane["seed_panel"]["count"] == selected["seed_count"]
    assert any("strict smoke" in blocker.lower() for blocker in lane["blockers"])
    assert lane["reference_agent"] == "pick-trader"
    assert lane["protocol_repair_attempts"] == 1
    assert lane["strict_fallback_required"] is True
    assert lane["model_registry"] == "config/sota_v3_models.json"
    assert lane["smoke_manifest"] == "config/sota_v3_smoke_manifest.json"
    assert lane["publication_protocol"] == "config/sota_v3_publication_protocol.json"
    assert lane["pricing_snapshot"] == "config/sota_v3_pricing_snapshot.json"
    assert lane["minimum_headline_models"] >= 8


def test_v3_registry_is_frozen_to_authenticated_routes_and_privacy_evidence() -> None:
    lane = _read("sota_v3_lane.json")
    registry = _read("sota_v3_models.json")

    assert registry["contract"] == lane["contract"]
    assert registry["contract_fingerprint"] == lane["contract_fingerprint"]
    assert registry["selection_status"] == "frozen"
    assert registry["selection_frozen_at_utc"]
    assert registry["catalog_snapshot_status"] == "frozen-public-metadata-only"
    assert registry["catalog_checked_at_utc"]
    assert len(registry["models"]) == len(registry["required_smokes"]) == 8
    assert set(registry["required_smokes"]) == {model["id"] for model in registry["models"]}
    assert registry["repeats"] == lane["repeats"] == 1
    assert registry["output_token_cap"] == lane["output_token_cap"] == 4096
    assert registry["output_budget_status"] == lane["output_budget_status"] == "frozen-native-reasoning-cap"
    assert registry["spend_authorized"] is True
    assert registry["panel_execution_authorized"] is False
    assert registry["exact_route_acceptance"]["status"] == "accepted"
    assert v3_route_acceptance_issues(registry) == []
    assert registry["provider_policy"] == "openrouter-only"
    assert registry["shared_fixed_options"]["OPENROUTER_JSON_MODE"] == "true"
    assert registry["public_metadata_limitations"]
    assert all("smoke" in decision for decision in registry["unresolved_decisions"])


def test_v3_protocol_and_pricing_are_separate_and_fail_closed() -> None:
    lane = _read("sota_v3_lane.json")
    protocol = _read("sota_v3_publication_protocol.json")
    pricing = _read("sota_v3_pricing_snapshot.json")

    assert protocol["contract"] == pricing["contract"] == lane["contract"]
    assert protocol["contract_fingerprint"] == pricing["contract_fingerprint"] == lane["contract_fingerprint"]
    assert protocol["status"] == "frozen"
    assert protocol["statistical_analysis_plan"]["status"] == "frozen"
    assert protocol["statistical_analysis_plan"]["analysis_mode"] == "reference-only"
    assert protocol["statistical_analysis_plan"]["inference_method"] == "exact-enumeration-sign-flip"
    assert protocol["statistical_analysis_plan"]["unit_of_inference"] == "seed"
    assert protocol["statistical_analysis_plan"]["primary_contrast"] == "paired lift versus pick-trader"
    assert protocol["statistical_analysis_plan"]["reference_agent"] == lane["reference_agent"] == "pick-trader"
    assert protocol["statistical_analysis_plan"]["multiplicity_method"] == "holm-bonferroni"
    assert protocol["statistical_analysis_plan"]["alpha"] == 0.05
    assert protocol["statistical_analysis_plan"]["holm_family_size"] == 8
    assert protocol["statistical_analysis_plan"]["power_model"]["historical_shared_seed_variance"] == pytest.approx(
        3770.478399
    )
    assert protocol["statistical_analysis_plan"]["power_model"]["selected_sensitivity_power"] == 0.8727
    assert protocol["statistical_analysis_plan"]["power_model"]["selected_allocation"] == "16 seeds x 1 repeat"
    assert protocol["statistical_analysis_plan"]["claim_direction"] == "trails-reference"
    assert protocol["statistical_analysis_plan"]["target_effect_score_points"] == -100
    # The lane and the protocol carry separate copies of the design; they must agree.
    assert (
        protocol["statistical_analysis_plan"]["target_effect_score_points"]
        == lane["statistical_panel_design"]["target_effect_score_points"]
    )
    assert protocol["panel_design"]["status"] == lane["panel_design_status"]
    assert protocol["budget_policy"]["spend_authorized"] is True
    assert pricing["status"] == "frozen"
    assert pricing["checked_at_utc"]
    assert len(pricing["models"]) == 8
    assert pricing["spend_authorized"] is True


def test_v3_preregistration_authorizes_smoke_but_keeps_panel_and_publication_locked() -> None:
    lane = _read("sota_v3_lane.json")
    registry = _read("sota_v3_models.json")
    manifest = _read("sota_v3_smoke_manifest.json")

    assert lane["preregistration_status"] == "frozen"
    assert lane["panel_design_status"] == "frozen"
    assert lane["output_budget_status"] == "frozen-native-reasoning-cap"
    assert lane["output_token_cap"] == 4096
    assert lane["cap_pressure_threshold_tokens"] == 3072
    assert lane["fallback_output_token_cap"] == 8192
    assert "abort sota-v3 under this contract" in lane["output_policy_amendment_rule"]
    assert lane["reasoning_policy"] == "disabled"
    assert lane["cap_pressure_action"] == "abort-sota-v3-and-repreregister"
    assert lane["max_cap_amendments"] == 0
    assert lane["spend_authorized"] is True
    # Granted 2026-08-03 for the completed zero-completion-call probe; it is the
    # one authorization that cannot reach a model, reserve spend, or write run
    # state, so it does not belong in the fail-closed set below.
    assert lane["route_preflight_authorized"] is True
    assert lane["smoke_execution_authorized"] is True
    assert lane["panel_execution_authorized"] is False
    assert lane["publication_authorized"] is False
    assert lane["blockers"]

    assert manifest["format"] == SMOKE_MANIFEST_FORMAT
    assert manifest["contract"] == lane["contract"]
    assert manifest["contract_fingerprint"] == lane["contract_fingerprint"]
    assert manifest["status"] == "in-progress"
    assert manifest["accepted_for_panel"] is False
    assert manifest["entries"]
    assert set(manifest["entries"]) < set(registry["required_smokes"])
    assert all(entry["accepted"] is True for entry in manifest["entries"].values())

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


def test_smoke_authorization_cannot_drift_into_panel_or_publication_authorization() -> None:
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
    assert lane["spend_authorized"] is lane["smoke_execution_authorized"] is True
    assert registry["spend_authorized"] is True
    assert lane["panel_execution_authorized"] is False
    assert lane["publication_authorized"] is False
    assert registry["panel_execution_authorized"] is False


@pytest.mark.parametrize("mode", ["--dry-run", "--preflight-only"])
def test_runner_keeps_historical_v3_blocked_before_provider_access(
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
    assert "frozen historical evidence ('sota-v3'/'sota-v3')" in capsys.readouterr().err
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


def test_smoke_readiness_unlocks_smoke_but_not_panel() -> None:
    lane = _read("sota_v3_lane.json")
    registry = _read("sota_v3_models.json")
    protocol = _read("sota_v3_publication_protocol.json")
    pricing = _read("sota_v3_pricing_snapshot.json")
    manifest = _read("sota_v3_smoke_manifest.json")

    def issues(reg: dict, phase: str) -> list[str]:
        return publication_execution_issues(lane, reg, manifest, phase=phase, protocol=protocol, pricing=pricing)

    assert issues(registry, "route-preflight") == []
    locked_lane = dict(lane, route_preflight_authorized=False)
    assert publication_execution_issues(
        locked_lane,
        registry,
        manifest,
        phase="route-preflight",
        protocol=protocol,
        pricing=pricing,
    ) == ["zero-call route preflight is locked while route_preflight_authorized is false"]

    assert issues(registry, "smoke") == []
    panel_issues = issues(registry, "panel")
    assert "panel execution is locked by the model registry" in panel_issues
    assert "sota-v3 smoke manifest is not accepted for panel execution" in panel_issues

    blocked = dict(registry, selection_status="provisional-blocked")
    assert "provider execution is locked until the model registry is frozen" in issues(blocked, "smoke")


def test_cap_pressure_rule_aborts_on_the_first_trigger() -> None:
    """Cap pressure requires a new preregistration, never an in-place edit."""
    protocol = _read("sota_v3_publication_protocol.json")
    lane = _read("sota_v3_lane.json")
    policy = protocol["output_policy"]

    expected_action = "abort-sota-v3-and-repreregister"
    assert lane["cap_pressure_action"] == policy["cap_pressure_action"] == expected_action
    assert policy["on_first_trigger"] == expected_action
    assert lane["max_cap_amendments"] == policy["max_cap_amendments"] == 0
    assert "No in-place cap amendment is permitted" in policy["amendment_rule"]
    assert "Scores and apparent model quality are never cap-selection inputs" in policy["amendment_rule"]

    # The wider cap remains a planning comparison only. It is never an
    # authorized fallback branch under this preregistration.
    cap = lane["output_token_cap"]
    fallback = policy["fallback_output_token_cap"]
    assert fallback > cap


def _cross_file_issues(
    *,
    lane: dict | None = None,
    registry: dict | None = None,
    protocol: dict | None = None,
    pricing: dict | None = None,
    manifest: dict | None = None,
    cost_estimate: dict | None = None,
) -> list[str]:
    return v3_cross_file_coherence_issues(
        lane or _read("sota_v3_lane.json"),
        registry or _read("sota_v3_models.json"),
        protocol or _read("sota_v3_publication_protocol.json"),
        pricing or _read("sota_v3_pricing_snapshot.json"),
        manifest or _read("sota_v3_smoke_manifest.json"),
        cost_estimate or json.loads(Path("results/analysis/sota-v3-pre-smoke-cost-estimate.json").read_text()),
    )


def test_v3_structured_records_are_cross_file_coherent() -> None:
    assert _cross_file_issues() == []


def test_v3_cross_file_coherence_catches_family_and_smoke_count_drift() -> None:
    protocol = _read("sota_v3_publication_protocol.json")
    protocol["statistical_analysis_plan"]["holm_family_size"] = 10
    registry = _read("sota_v3_models.json")
    registry["required_smokes"] = registry["required_smokes"][:-1]

    issues = _cross_file_issues(protocol=protocol, registry=registry)

    assert "sota-v3 protocol Holm family size must equal the registered model count" in issues
    assert "sota-v3 required smokes must match the registered models in order" in issues


def test_v3_cross_file_coherence_catches_reasoning_and_budget_drift() -> None:
    lane = _read("sota_v3_lane.json")
    lane["reasoning_policy"] = "catalog-pinned-pending-strict-smoke-behavior-verification"
    cost_estimate = json.loads(Path("results/analysis/sota-v3-pre-smoke-cost-estimate.json").read_text())
    cost_estimate["costs_usd"]["total_with_1_2x_contingency"] = 101.0

    issues = _cross_file_issues(lane=lane, cost_estimate=cost_estimate)

    assert "sota-v3 lane, protocol, and every registered route must be reasoning-disabled" in issues
    assert "sota-v3 generated planning forecast must fit under the operator ceiling" in issues


def test_v3_cross_file_coherence_catches_protocol_maximum_drift() -> None:
    cost_estimate = json.loads(Path("results/analysis/sota-v3-pre-smoke-cost-estimate.json").read_text())
    cost_estimate["protocol_maximum"]["total_calls"] -= 1

    issues = _cross_file_issues(cost_estimate=cost_estimate)

    assert "sota-v3 aggregate protocol-maximum total calls are inconsistent" in issues


def test_v3_cross_file_coherence_catches_in_place_cap_amendment() -> None:
    protocol = _read("sota_v3_publication_protocol.json")
    protocol["output_policy"]["max_cap_amendments"] = 1
    protocol["output_policy"]["on_first_trigger"] = "amend-and-resmoke"

    issues = _cross_file_issues(protocol=protocol)

    assert "sota-v3 first cap-pressure trigger must abort and require preregistration" in issues
    assert "sota-v3 cap policy must forbid in-place amendments" in issues
