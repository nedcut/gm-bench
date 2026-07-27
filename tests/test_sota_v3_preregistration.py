"""Fail-closed checks for the provisional sota-v3 publication lane."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.run_publication_matrix as publication_runner
from gm_bench.contract import BENCHMARK_VERSION, contract_fingerprint
from gm_bench.publication import SMOKE_MANIFEST_FORMAT

CONFIG = Path("config")


def _read(name: str) -> dict:
    payload = json.loads((CONFIG / name).read_text())
    assert isinstance(payload, dict)
    return payload


def test_v3_lane_pins_current_contract_but_not_an_unresolved_panel_design() -> None:
    lane = _read("sota_v3_lane.json")

    assert lane["contract"] == BENCHMARK_VERSION == "sota-v3"
    assert lane["contract_fingerprint"] == contract_fingerprint()
    assert lane["mechanics_status"] == "frozen-for-sota-v3-panel"
    assert "requires a new contract fingerprint" in lane["mechanics_change_policy"]
    assert lane["headline_lane"] == "api"
    assert lane["observation_profile"] == "compact"
    assert lane["session"] is False
    assert lane["preset"] == "leaderboard"
    assert lane["panel_design_status"] == "unresolved-pre-data"
    candidate = lane["candidate_panel_design"]
    assert candidate["status"] == "illustrative-not-frozen"
    assert candidate["episodes_per_model"] == len(candidate["seeds"]) * candidate["repeats"] == 24
    assert candidate["holm_power_at_delta_40"] == 0.175
    assert any("seed-versus-repeat allocation" in blocker for blocker in lane["blockers"])
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
    assert registry["catalog_checked_at_utc"] is None
    assert registry["models"] == []
    assert registry["required_smokes"] == []
    assert registry["output_token_cap"] is None
    assert registry["spend_authorized"] is False
    assert registry["panel_execution_authorized"] is False
    assert registry["unresolved_decisions"]
    assert registry["provider_policy"] == "openrouter-only"
    assert "OPENROUTER_JSON_MODE" not in registry["shared_fixed_options"]
    assert any("JSON response mode" in decision for decision in registry["unresolved_decisions"])


def test_v3_protocol_and_pricing_are_separate_and_fail_closed() -> None:
    lane = _read("sota_v3_lane.json")
    protocol = _read("sota_v3_publication_protocol.json")
    pricing = _read("sota_v3_pricing_snapshot.json")

    assert protocol["contract"] == pricing["contract"] == lane["contract"]
    assert protocol["contract_fingerprint"] == pricing["contract_fingerprint"] == lane["contract_fingerprint"]
    assert protocol["status"] == "provisional-blocked"
    assert protocol["statistical_analysis_plan"]["status"] == "unresolved-pre-data"
    assert protocol["budget_policy"]["spend_authorized"] is False
    assert pricing["status"] == "not-started"
    assert pricing["checked_at_utc"] is None
    assert pricing["models"] == {}
    assert pricing["spend_authorized"] is False


def test_v3_preregistration_fails_closed_before_smoke_or_panel_spend() -> None:
    lane = _read("sota_v3_lane.json")
    registry = _read("sota_v3_models.json")
    manifest = _read("sota_v3_smoke_manifest.json")

    assert lane["preregistration_status"] == "provisional-blocked"
    assert lane["panel_design_status"] == "unresolved-pre-data"
    assert lane["output_budget_status"] == "blocked-pending-registered-model-smokes"
    assert lane["output_token_cap"] is None
    assert lane["reasoning_policy"] == "pending-live-route-verification"
    assert lane["spend_authorized"] is False
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

    # Empty registries and manifests must never be mistaken for complete gates.
    assert len(registry["models"]) < lane["minimum_headline_models"]
    smoke_gate_complete = (
        bool(registry["models"])
        and set(registry["required_smokes"]) == {model["id"] for model in registry["models"]}
        and set(registry["required_smokes"]) == set(manifest["entries"])
        and manifest["accepted_for_panel"] is True
    )
    assert smoke_gate_complete is False


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
