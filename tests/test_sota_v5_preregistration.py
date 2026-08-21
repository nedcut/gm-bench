"""Zero-spend coherence checks for the SOTA-v5 successor preregistration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.run_publication_matrix as publication_runner
from gm_bench.publication import publication_execution_issues

ROOT = Path(__file__).parents[1]
CONFIG = ROOT / "config"


def _read(path: Path) -> dict:
    payload = json.loads(path.read_text())
    assert isinstance(payload, dict)
    return payload


def _configs() -> tuple[dict, dict, dict, dict, dict]:
    return tuple(
        _read(CONFIG / name)
        for name in (
            "sota_v5_lane.json",
            "sota_v5_models.json",
            "sota_v5_publication_protocol.json",
            "sota_v5_pricing_snapshot.json",
            "sota_v5_smoke_manifest.json",
        )
    )  # type: ignore[return-value]


def test_v5_cross_file_contract_and_family_are_coherent() -> None:
    lane, registry, protocol, pricing, manifest = _configs()
    records = (lane, registry, protocol, pricing, manifest)

    assert {record["contract"] for record in records} == {"sota-v5"}
    assert len({record["contract_fingerprint"] for record in records}) == 1
    assert all(record["contract_fingerprint"] == "519bf6db27320d8b" for record in records)
    model_ids = [model["id"] for model in registry["models"]]
    assert len(model_ids) == len(set(model_ids)) == 8
    assert model_ids == registry["required_smokes"] == manifest["required_models"]
    assert registry["repeats"] == lane["repeats"] == 1
    assert (
        registry["output_token_cap"]
        == lane["output_token_cap"]
        == protocol["output_policy"]["output_token_cap"]
        == 4096
    )
    assert lane["panel_design_status"] == protocol["panel_design"]["status"] == "frozen"
    assert registry["selection_status"] == "frozen"
    assert pricing["status"] == "frozen"
    assert set(model["model"] for model in registry["models"]) == set(pricing["models"])


def test_v5_real_registry_builds_every_seed_free_smoke_cell(monkeypatch: pytest.MonkeyPatch) -> None:
    panel, lane, manifest, protocol, pricing = publication_runner.CONTRACT_CONFIGS["sota-v5"]
    monkeypatch.setattr(publication_runner, "PANEL_CONFIG", panel)
    monkeypatch.setattr(publication_runner, "LANE_CONFIG", lane)
    monkeypatch.setattr(publication_runner, "SMOKE_MANIFEST", manifest)
    monkeypatch.setattr(publication_runner, "PROTOCOL_CONFIG", protocol)
    monkeypatch.setattr(publication_runner, "PRICING_CONFIG", pricing)

    cells = publication_runner.build_cells("smoke", authorization_phase="route-preflight")

    assert len(cells) == 8
    assert {cell.experiment_id for cell in cells} == set(_read(panel)["required_smokes"])


def test_v5_replaces_qwen_before_any_v5_data() -> None:
    _, registry, protocol, _, _ = _configs()
    models = {model["model"]: model for model in registry["models"]}

    assert "qwen/qwen3.8-max" not in models
    assert "z-ai/glm-5.2" not in models
    replacement = models["google/gemini-3.7-flash"]
    assert replacement["id"] == "openrouter-gemini-3.7-flash-google-ai-studio"
    assert replacement["endpoint_tag"] == "google-ai-studio"
    assert replacement["upstream_provider"] == "Google AI Studio"
    assert replacement["endpoint_name"] == "Google AI Studio | google/gemini-3.7-flash-20260813"
    assert replacement["catalog_uptime_last_1d"] == 99.6568375762854
    assert replacement["catalog_uptime_last_30m"] == 99.31597947938438
    assert replacement["reasoning_policy"] == "disabled"
    assert replacement["fixed_options"] == {"OPENROUTER_REASONING_ENABLED": "false"}
    rule = registry["replacement_selection_rule"]
    assert rule["status"] == "frozen-before-v5-provider-evidence"
    assert rule["selected_model"] == replacement["model"]
    assert rule["selected_route"] == replacement["endpoint_tag"]
    assert "GM-Bench score or behavior" in rule["excluded_selection_inputs"]
    assert "price" in rule["excluded_selection_inputs"]
    assert protocol["selection_and_lineage"] == {
        "replacement_model_id": "openrouter-gemini-3.7-flash-google-ai-studio",
        "replaced_terminal_model_id": "openrouter-qwen3.8-max-alibaba",
        "selection_basis": "public-catalog-metadata-before-v5-data",
        "owner_attestation_required": True,
        "v4_terminal": True,
    }


def test_v5_retains_hidden_commitment_but_requires_owner_attestation() -> None:
    lane, _, protocol, _, _ = _configs()
    seed_panel = lane["seed_panel"]

    assert seed_panel["count"] == 16
    assert seed_panel["sha256"] == "291fa61cc3dfd8b23fdd79cce3c80a0a98f918f6c8757d35c21b4d8131cc6099"
    assert seed_panel["hiding_commitment_sha256"] == "7f8da7ca4db4a698ea2b0506af8568c89744e18508d8dedbfeb1c87e90a2b5f8"
    assert seed_panel["lineage_chain"] == ["sota-v3", "sota-v4", "sota-v5"]
    assert seed_panel["owner_attestation_required"] is True
    assert seed_panel["owner_attestation_status"] == "pending-before-seed-access"
    assert seed_panel["seed_values_included"] is False
    assert seed_panel["secret_values_read_for_v5_preregistration"] is False
    assert protocol["panel_design"]["seed_values_read_for_preregistration"] is False


def test_v5_is_fail_closed_before_paid_smokes() -> None:
    lane, registry, protocol, pricing, manifest = _configs()
    records = (lane, registry, protocol, pricing)

    assert all(record["route_preflight_authorized"] is True for record in records)
    assert registry["exact_route_acceptance"]["status"] == "accepted"
    assert len(registry["exact_route_acceptance"]["entries"]) == 8
    for record in records:
        assert record["spend_authorized"] is False
        assert record["smoke_execution_authorized"] is False
        assert record["panel_execution_authorized"] is False
        assert record["publication_authorized"] is False
    assert protocol["budget_policy"]["spend_authorized"] is False
    assert manifest["format"] == "gm-bench-smoke-manifest-v1"
    assert manifest["status"] == "not-started"
    assert manifest["entries"] == {}
    assert manifest["accepted_for_panel"] is False
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
    assert len(smoke_issues) == 6
    assert any(
        "exact-route evidence artifact is for a different contract fingerprint" in issue for issue in smoke_issues
    )
    assert any("final-fingerprint preflight evidence is not accepted" in issue for issue in smoke_issues)
    assert any("spend is explicitly authorized" in issue for issue in smoke_issues)
    assert any("smoke_execution_authorized is false" in issue for issue in smoke_issues)
    panel_issues = publication_execution_issues(
        lane,
        registry,
        manifest,
        phase="panel",
        protocol=protocol,
        pricing=pricing,
    )
    assert any("owner attestation before private seed access" in issue for issue in panel_issues)


@pytest.mark.parametrize("seed_panel", [None, {}, {"owner_attestation_required": False}])
def test_v5_panel_attestation_cannot_be_disabled_by_lane_payload(seed_panel: object) -> None:
    lane, registry, protocol, pricing, manifest = _configs()
    lane["seed_panel"] = seed_panel

    issues = publication_execution_issues(
        lane,
        registry,
        manifest,
        phase="panel",
        protocol=protocol,
        pricing=pricing,
    )

    assert "sota-v5 panel execution requires owner attestation before private seed access" in issues


def test_v5_cost_artifact_covers_the_ten_dollar_smoke_ceiling() -> None:
    lane, registry, protocol, pricing, _ = _configs()
    estimate = _read(ROOT / "results/analysis/sota-v5-pre-smoke-cost-estimate.json")

    assert lane["cost_estimate_artifact"] == "results/analysis/sota-v5-pre-smoke-cost-estimate.json"
    assert protocol["budget_policy"]["cost_estimate_artifact"] == lane["cost_estimate_artifact"]
    assert estimate["calls"] == {
        "model_count": 8,
        "panel_decisions_per_model": 320,
        "panel_calls": 2560,
        "smoke_runs": 8,
        "smoke_decisions_per_run": 4,
        "smoke_calls": 32,
        "total_calls": 2592,
    }
    assert estimate["protocol_maximum"]["costs_usd"]["smoke"] == pytest.approx(6.17324032)
    assert estimate["protocol_maximum"]["costs_usd"]["total_with_contingency"] == pytest.approx(600.038959104)
    assert (
        estimate["protocol_maximum"]["costs_usd"]["smoke"] * 1.2
        < protocol["budget_policy"]["operator_ceiling_usd"]
        == 10.0
    )
    assert estimate["protocol_maximum"]["costs_usd"]["panel"] > protocol["budget_policy"]["operator_ceiling_usd"]
    assert {row["experiment_id"] for row in estimate["models"]} == set(registry["required_smokes"])
