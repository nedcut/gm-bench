"""Zero-spend coherence checks for the frozen SOTA-v4 preregistration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gm_bench.publication import (
    PENDING_STRICT_SMOKE_CAP_VERIFICATION,
    publication_execution_issues,
    v3_final_preflight_issues,
)
from scripts.estimate_publication_cost import estimate

CONFIG = Path("config")
COST_ARTIFACT = Path("results/analysis/sota-v4-pre-smoke-cost-estimate.json")


def _read(path: Path) -> dict:
    payload = json.loads(path.read_text())
    assert isinstance(payload, dict)
    return payload


def _configs() -> tuple[dict, dict, dict, dict, dict]:
    lane = _read(CONFIG / "sota_v4_lane.json")
    registry = _read(CONFIG / "sota_v4_models.json")
    protocol = _read(CONFIG / "sota_v4_publication_protocol.json")
    pricing = _read(CONFIG / "sota_v4_pricing_snapshot.json")
    manifest = _read(CONFIG / "sota_v4_smoke_manifest.json")
    return lane, registry, protocol, pricing, manifest


def test_v4_frozen_records_are_cross_file_coherent() -> None:
    lane, registry, protocol, pricing, manifest = _configs()
    records = (lane, registry, protocol, pricing, manifest)

    assert {record["contract"] for record in records} == {"sota-v4"}
    assert len({record["contract_fingerprint"] for record in records}) == 1
    model_ids = [model["id"] for model in registry["models"]]
    model_names = [model["model"] for model in registry["models"]]
    assert len(model_ids) == len(set(model_ids)) == lane["minimum_headline_models"] == 8
    assert model_ids == registry["required_smokes"]
    assert set(model_ids) == set(registry["exact_route_acceptance"]["entries"])
    assert set(model_names) == set(pricing["models"])
    assert registry["repeats"] == lane["repeats"] == 1
    assert registry["output_token_cap"] == lane["output_token_cap"] == 4096
    assert lane["preregistration_status"] == protocol["status"] == "frozen"
    assert lane["panel_design_status"] == protocol["panel_design"]["status"] == "frozen"
    assert lane["seed_panel"]["status"] == "frozen"
    assert lane["output_policy_basis"] == "fixed-safety-ceiling"
    assert lane["output_budget_status"] == registry["output_budget_status"]
    assert protocol["output_policy"]["status"] == "frozen-native-reasoning-cap"
    assert pricing["status"] == "frozen"


def test_v4_preserves_the_unused_family_eight_seed_and_power_commitment() -> None:
    lane, _, protocol, _, _ = _configs()
    design = lane["statistical_panel_design"]
    selected = design["selected_allocation"]
    seed_panel = lane["seed_panel"]

    assert design["holm_family_size"] == protocol["statistical_analysis_plan"]["holm_family_size"] == 8
    assert selected["seed_count"] == seed_panel["count"] == 16
    assert selected["repeats"] == lane["repeats"] == 1
    assert selected["episodes_per_model"] == 16
    assert selected["sensitivity_power_estimate"] == 0.8727
    assert selected["sensitivity_power_wilson_ci95"] == [0.866024, 0.87909]
    assert selected["base_power_estimate"] == 0.9629
    assert seed_panel["lineage_contract"] == "sota-v3"
    assert seed_panel["lineage_use_status"] == "unused-no-sota-v3-panel-execution"
    assert seed_panel["sha256"] == "291fa61cc3dfd8b23fdd79cce3c80a0a98f918f6c8757d35c21b4d8131cc6099"
    assert seed_panel["hiding_commitment_sha256"] == (
        "7f8da7ca4db4a698ea2b0506af8568c89744e18508d8dedbfeb1c87e90a2b5f8"
    )
    assert seed_panel["seed_values_included"] is False
    assert seed_panel["secret_values_read_for_v4_preregistration"] is False


def test_v4_replacement_and_route_selection_are_predata() -> None:
    _, registry, _, _, _ = _configs()
    by_model = {model["model"]: model for model in registry["models"]}

    assert "z-ai/glm-5.2" not in by_model
    assert by_model["upstage/solar-pro4"]["endpoint_tag"] == "upstage"
    assert by_model["minimax/minimax-m3"]["endpoint_tag"] == "minimax/fp8"
    assert by_model["minimax/minimax-m3"]["catalog_quantization"] == "fp8"
    assert by_model["qwen/qwen3.8-max"]["request_compatibility_status"].startswith("unresolved-")
    assert by_model["mistralai/mistral-medium-3-5"]["output_cap_verification"] == (
        PENDING_STRICT_SMOKE_CAP_VERIFICATION
    )
    assert registry["selection_status"] == "frozen"
    assert registry["selection_frozen_at_utc"]
    assert registry["exact_route_acceptance"]["status"] == "accepted"
    assert all(
        entry["authenticated"] is True and entry["privacy_acceptance"]["status"] == "accepted"
        for entry in registry["exact_route_acceptance"]["entries"].values()
    )
    assert all("Complete authenticated zero-call" not in item for item in registry["unresolved_decisions"])
    assert all("deliberately false or unresolved" not in item for item in registry["public_metadata_limitations"])


def test_v4_authorizes_only_serial_strict_smokes() -> None:
    lane, registry, protocol, pricing, manifest = _configs()

    assert all(record["route_preflight_authorized"] is True for record in (lane, registry, protocol, pricing))
    for record in (lane, registry, protocol, pricing):
        assert record["spend_authorized"] is True
        assert record["smoke_execution_authorized"] is True
        assert record["panel_execution_authorized"] is False
        assert record["publication_authorized"] is False
    assert protocol["budget_policy"]["spend_authorized"] is True
    operator_ceiling = protocol["budget_policy"]["operator_ceiling_usd"]
    assert operator_ceiling == 10.0
    assert lane["final_preflight_evidence"]["status"] == "accepted"
    assert lane["final_preflight_evidence"]["artifact"] == ("results/analysis/sota-v4-final-preflight-evidence.json")
    assert lane["final_preflight_evidence"]["operator_ceiling_usd"] == operator_ceiling
    final_preflight = _read(Path(lane["final_preflight_evidence"]["artifact"]))
    assert final_preflight["keychain_dry_run"]["operator_ceiling_usd"] == operator_ceiling
    assert all("Complete a zero-completion-call final preflight" not in item for item in lane["blockers"])
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
    smoke_issues = publication_execution_issues(
        lane,
        registry,
        manifest,
        phase="smoke",
        protocol=protocol,
        pricing=pricing,
    )
    panel_issues = publication_execution_issues(
        lane,
        registry,
        manifest,
        phase="panel",
        protocol=protocol,
        pricing=pricing,
    )
    assert smoke_issues == []
    assert any("panel_execution_authorized is false" in issue for issue in panel_issues)
    assert any("smoke manifest is not accepted" in issue for issue in panel_issues)


def test_v4_final_preflight_status_cannot_bypass_artifact_validation() -> None:
    lane, registry, protocol, _, _ = _configs()
    lane["final_preflight_evidence"] = {
        "status": "accepted",
        "artifact": "results/analysis/missing-v4-final-preflight.json",
        "sha256": "0" * 64,
        "operator_ceiling_usd": 10.0,
    }

    issues = v3_final_preflight_issues(lane, registry, protocol, contract="sota-v4")

    assert any("cannot be read" in issue for issue in issues)
    assert all("sota-v3" not in issue for issue in issues)


def test_v4_statistical_plan_rejects_mislabeled_contracts() -> None:
    lane, registry, protocol, _, _ = _configs()
    lane["contract"] = "sota-v3"

    issues = publication_execution_issues(
        lane,
        registry,
        _read(CONFIG / "sota_v4_smoke_manifest.json"),
        phase="smoke",
        protocol=protocol,
        pricing=_read(CONFIG / "sota_v4_pricing_snapshot.json"),
    )

    assert any("contracts do not match" in issue or "must declare contract" in issue for issue in issues)


def test_v4_cost_artifact_regenerates_and_ceiling_covers_smoke_only() -> None:
    lane, registry, protocol, pricing, _ = _configs()
    committed = _read(COST_ARTIFACT)
    regenerated = estimate(registry, lane, pricing)

    assert committed == regenerated
    assert lane["cost_estimate_artifact"] == str(COST_ARTIFACT)
    assert protocol["budget_policy"]["cost_estimate_artifact"] == str(COST_ARTIFACT)
    protocol_maximum_smoke = committed["protocol_maximum"]["costs_usd"]["smoke"]
    assert protocol_maximum_smoke == pytest.approx(6.67548672)
    assert protocol_maximum_smoke < protocol["budget_policy"]["operator_ceiling_usd"] == 10.0
    assert committed["protocol_maximum"]["costs_usd"]["panel"] > 10.0


def test_v4_empty_smoke_manifest_keeps_panel_locked() -> None:
    lane, _, protocol, _, manifest = _configs()

    assert manifest["status"] == "not-started"
    assert manifest["entries"] == {}
    assert manifest["accepted_for_panel"] is False
    assert lane["smoke_execution_authorized"] is True
    assert lane["panel_execution_authorized"] is False
    assert protocol["panel_execution_authorized"] is False
    assert protocol["publication_authorized"] is False
