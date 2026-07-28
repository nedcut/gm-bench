"""Fail-closed checks for the provisional sota-v3 publication lane."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.run_publication_matrix as publication_runner
from gm_bench.contract import BENCHMARK_VERSION, contract_fingerprint
from gm_bench.publication import SMOKE_MANIFEST_FORMAT, exact_sign_flip_feasibility

CONFIG = Path("config")


def _read(name: str) -> dict:
    payload = json.loads((CONFIG / name).read_text())
    assert isinstance(payload, dict)
    return payload


def test_v3_lane_pins_current_contract_and_blocks_underpowered_grid() -> None:
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
    assert lane["repeats"] == 3
    assert lane["panel_design_status"] == "blocked-no-qualifying-allocation"
    candidate = lane["statistical_panel_design"]
    assert candidate["status"] == "blocked-no-qualifying-allocation"
    assert candidate["historical_lift_variances"]["shared_seed"] == pytest.approx(3770.478399)
    assert candidate["evaluated_seed_range"] == [9, 20]
    assert candidate["evaluated_repeat_range"] == [1, 3]
    best = candidate["best_tested_allocation"]
    assert best["seed_count"] == 20
    assert best["episodes_per_model"] == best["seed_count"] * best["repeats"] == 60
    feasibility = exact_sign_flip_feasibility(
        best["seed_count"],
        candidate["holm_family_size"],
    )
    assert best["minimum_exact_two_sided_sign_flip_p_value"] == feasibility["minimum_two_sided_p_value"]
    assert best["holm_first_step_threshold_at_alpha_0_05"] == feasibility["holm_first_step_threshold"]
    assert best["exact_sign_flip_holm_feasible"] is feasibility["feasible"] is True
    assert best["sensitivity_power_wilson_ci95"][1] < candidate["target_familywise_all_reject_power"]
    assert lane["seed_panel"] == {
        "status": "blocked-pending-allocation",
        "name": None,
        "count": None,
        "sha256": None,
    }
    assert any("no allocation" in blocker.lower() for blocker in lane["blockers"])
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
    assert registry["selection_status"] == "provisional-blocked"
    assert registry["selection_frozen_at_utc"] is None
    assert registry["catalog_snapshot_status"] == "frozen-public-metadata-only"
    assert registry["catalog_checked_at_utc"]
    assert len(registry["models"]) == len(registry["required_smokes"]) == 8
    assert set(registry["required_smokes"]) == {model["id"] for model in registry["models"]}
    assert registry["output_token_cap"] is None
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
    assert protocol["status"] == "provisional-blocked"
    assert protocol["statistical_analysis_plan"]["status"] == "blocked-power-design"
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
    assert protocol["statistical_analysis_plan"]["power_model"]["best_tested_sensitivity_power"] == 0.2154
    assert protocol["budget_policy"]["spend_authorized"] is False
    assert pricing["status"] == "catalog-frozen-public-metadata-only"
    assert pricing["checked_at_utc"]
    assert len(pricing["models"]) == 8
    assert pricing["spend_authorized"] is False


def test_v3_preregistration_fails_closed_before_smoke_or_panel_spend() -> None:
    lane = _read("sota_v3_lane.json")
    registry = _read("sota_v3_models.json")
    manifest = _read("sota_v3_smoke_manifest.json")

    assert lane["preregistration_status"] == "provisional-blocked"
    assert lane["panel_design_status"] == "blocked-no-qualifying-allocation"
    assert lane["output_budget_status"] == "blocked-pending-registered-model-smokes"
    assert lane["output_token_cap"] is None
    assert lane["reasoning_policy"] == "pending-live-route-verification"
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
        or lane["output_token_cap"] is None
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
        lambda _cell: provider_access.append("endpoint"),
    )
    monkeypatch.setattr(
        publication_runner.subprocess,
        "run",
        lambda *_args, **_kwargs: provider_access.append("subprocess"),
    )

    with pytest.raises(SystemExit) as exc_info:
        publication_runner.main(["smoke", "--contract", "sota-v3", mode])

    assert exc_info.value.code == 2
    assert "sota-v3 lane is provisional-blocked; provider execution is locked" in capsys.readouterr().err
    assert provider_access == []


def test_runner_keeps_historical_v2_blocked_under_current_source(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    provider_access: list[str] = []
    monkeypatch.setattr(
        publication_runner,
        "_validate_openrouter_endpoint",
        lambda _cell: provider_access.append("endpoint"),
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
        lambda _cell: provider_access.append("endpoint"),
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
