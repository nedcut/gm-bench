"""Zero-spend coherence checks for the SOTA-v5 successor preregistration."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

import scripts.run_publication_matrix as publication_runner
from gm_bench.official import SOTA_V5_POLICY
from gm_bench.protocol import V6_PAID_CALLS_PER_DECISION
from gm_bench.publication import (
    exact_sign_flip_feasibility,
    publication_execution_issues,
    smoke_manifest_issues,
    v5_statistical_plan_issues,
)

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
    # Moved from 247e12fe5a7d4f5b, thirteen contract moves stale, by the
    # 2026-08-31 amendment. Every file in the set must move together or the
    # lane's own identity check fails.
    assert all(record["contract_fingerprint"] == "a600b7da0c302231" for record in records)
    model_ids = [model["id"] for model in registry["models"]]
    assert len(model_ids) == len(set(model_ids)) == 16
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
    revision = "2026-09-01-v6-route-and-cohort-amendment"
    assert registry["selection_revision"] == revision
    for record in (lane, protocol, pricing, manifest):
        assert record["amendment_revision"] == revision
        assert record["amendment_record"] == registry["amendment"]["amendment_record"]


def test_v5_registers_the_frozen_v6_panel() -> None:
    _, registry, protocol, _, _ = _configs()
    models = {model["model"]: model for model in registry["models"]}

    # Twelve identities are the frozen v6 spec panel; four were revised by the dated 2026-09-01 amendment.
    assert set(models) == {
        "x-ai/grok-4.6",
        "anthropic/claude-haiku-4.5",
        "google/gemini-3.7-flash",
        "x-ai/grok-4.3",
        "openai/gpt-5.4-mini",
        "z-ai/glm-5",
        "moonshotai/kimi-k2.5",
        "qwen/qwen3.8-flash",
        "minimax/minimax-m3",
        "google/gemini-3.1-flash-lite",
        "openai/gpt-5.6-luna",
        "z-ai/glm-5.3-flash",
        "deepseek/deepseek-v4-flash-0731",
        "qwen/qwen3.5-27b",
        "openai/gpt-5.6-sol",
        "openai/gpt-oss-20b",
    }
    assert models["x-ai/grok-4.6"]["tier"] == "frontier"
    assert protocol["selection_and_lineage"]["frontier_slot_model_id"] == models["x-ai/grok-4.6"]["id"]
    assert protocol["selection_and_lineage"]["panel_source"] == "docs/bench_v6_spec.md"
    # The withdrawn cohort is named, not quietly deleted.
    assert protocol["selection_and_lineage"]["withdrawn_cohort_model_count"] == 8
    assert registry["amendment"]["supersedes_revision"] == "2026-08-31-v6-execution-rules-amendment"
    # The route-and-cohort amendment keeps the execution-rules amendment nested, which in turn names the withdrawn cohort.
    assert (
        registry["amendment"]["supersedes_amendment"]["supersedes_revision"]
        == "2026-08-16-sota-v5-successor-preregistration"
    )
    # Four rows were revised after the smoke gate; the withdrawn identities must stay named, not deleted.
    assert "qwen/qwen3.5-397b-a17b" not in models
    assert "nvidia/nemotron-3-nano-30b-a3b" not in models
    assert "nvidia/nemotron-3-super-120b-a12b" not in models
    assert "nvidia/nemotron-3.5-lightning" not in models
    assert registry["route_selection_rule"]["lane_infrastructure_exclusion"]
    assert "qwen/qwen3.8-max" not in models
    assert "upstage/solar-pro4" not in models


def test_v5_pins_the_v6_execution_rules_a_row_is_judged_against() -> None:
    lane, registry, protocol, _, _ = _configs()

    # A v6 row is refused at validation if it bought a paid retry, so the
    # config that describes the run has to say zero in both places.
    assert SOTA_V5_POLICY.max_protocol_repair_attempts == 0
    assert registry["shared_fixed_options"]["GM_BENCH_PROTOCOL_REPAIR_ATTEMPTS"] == "0"
    assert lane["protocol_repair_attempts"] == 0
    assert protocol["rerun_policy"]["paid_model_retry_authorized"] is False
    assert SOTA_V5_POLICY.required_output_token_ceiling == lane["output_token_cap"] == 4096
    assert registry["shared_fixed_options"]["OPENROUTER_MAX_TOKENS"] == "4096"
    assert SOTA_V5_POLICY.expected_contract["simulator_version"] == "sim-v4"
    assert SOTA_V5_POLICY.expected_contract["observation_version"] == "observation-v3"
    assert "sim-v4" in protocol["research_question"]
    assert "observation-v3" in protocol["research_question"]


def test_v5_records_a_reasoning_decision_for_every_panel_model() -> None:
    _, registry, protocol, _, _ = _configs()

    mandatory = []
    for model in registry["models"]:
        catalog = model["catalog_reasoning"]
        assert isinstance(catalog["mandatory"], bool)
        assert model["reasoning_decision"]
        assert model["output_ceiling_headroom"]["status"] in {
            "metadata-sufficient",
            "verify-at-smoke-time",
        }
        if catalog["mandatory"]:
            mandatory.append(model["id"])
            assert model["reasoning_policy"] == "mandatory-minimum"
            # Minimum means the lowest effort the catalog actually advertises.
            assert model["reasoning_effort"] == catalog["supported_efforts"][-1]
            assert model["fixed_options"]["OPENROUTER_REASONING_ENABLED"] == "true"
            assert model["fixed_options"]["OPENROUTER_REASONING_EFFORT"] == model["reasoning_effort"]
            # 4,096 tokens includes reasoning, and free metadata cannot say how
            # many of them minimum effort spends.
            assert model["output_ceiling_headroom"]["status"] == "verify-at-smoke-time"
        else:
            assert model["reasoning_policy"] == "disabled"
            assert model["reasoning_effort"] is None
            assert model["fixed_options"] == {"OPENROUTER_REASONING_ENABLED": "false"}
            assert model["absent_options"] == ["OPENROUTER_REASONING_EFFORT"]

    assert mandatory == registry["reasoning_policy_rule"]["mandatory_reasoning_models"]
    assert set(mandatory) == {
        "openrouter-grok-4.6-xai",
        "openrouter-gemini-3.7-flash-google-ai-studio",
        "openrouter-glm-5.3-flash-fireworks",
        "openrouter-gpt-oss-20b-deepinfra",
    }
    # Mandatory reasoning used to abort the lane, which would have killed the
    # frontier slot outright.
    assert (
        protocol["output_policy"]["mandatory_reasoning_action"]
        == "run-at-minimum-advertised-effort-and-record-reasoning-tokens"
    )


def test_v5_every_registered_route_is_eligible_on_public_metadata() -> None:
    _, registry, _, _, _ = _configs()

    for model in registry["models"]:
        advertised = set(model["catalog_supported_parameters"])
        # Memory of a real failure: a route without response_format cannot run
        # the lane at all, and structured_outputs is the eligibility rule in
        # docs/bench_v6_spec.md.
        assert {"max_tokens", "reasoning", "response_format", "structured_outputs"} <= advertised
        assert model["catalog_route_status"] == 0
        assert model["catalog_uptime_last_1d"] >= 99.0
        # run_publication_matrix fails closed on a missing 30-minute figure, so
        # a route that publishes none cannot be registered here either.
        assert isinstance(model["catalog_uptime_last_30m"], int | float)
        assert not isinstance(model["catalog_uptime_last_30m"], bool)
        assert model["catalog_uptime_last_30m"] >= 90.0
        assert model["catalog_max_completion_tokens"] >= registry["output_token_cap"]
        assert model["upstream_provider_slug"] == model["endpoint_tag"]


def test_v5_retires_the_sixteen_seed_commitment_without_revealing_it() -> None:
    lane, _, protocol, _, _ = _configs()
    seed_panel = lane["seed_panel"]

    # 29 paired seeds is the frozen v6 width; the carried-forward commitment was
    # for 16 and is retired unused rather than reused or partially revealed.
    assert seed_panel["count"] == 29
    assert seed_panel["status"] == "frozen"
    assert seed_panel["sha256"] == "a21edc686a579b908998065fe17cb0a27cd5d541cbf074f4f5a8e52b86c2bf11"
    assert seed_panel["hiding_commitment_sha256"] == "3ece2f67ac3cb6bc5c77e71feb6a9ecf56d09eec544c206db260d083c345e1e7"
    assert seed_panel["seed_values_included"] is False
    assert seed_panel["secret_values_read_for_v5_preregistration"] is False
    assert protocol["panel_design"]["seed_values_read_for_preregistration"] is False
    retired = seed_panel["retired_commitment"]
    assert retired["count"] == 16
    assert retired["sha256"] == "291fa61cc3dfd8b23fdd79cce3c80a0a98f918f6c8757d35c21b4d8131cc6099"
    assert retired["hiding_commitment_sha256"] == "7f8da7ca4db4a698ea2b0506af8568c89744e18508d8dedbfeb1c87e90a2b5f8"
    assert retired["lineage_chain"] == ["sota-v3", "sota-v4", "sota-v5"]
    assert "unused" in retired["lineage_use_status"]
    assert seed_panel["owner_attestation_required"] is True
    assert seed_panel["owner_attestation_status"] == "attested-before-seed-access"


def test_v5_twenty_nine_seeds_still_clear_the_holm_first_step() -> None:
    lane, registry, protocol, pricing, manifest = _configs()
    design = lane["statistical_panel_design"]

    assert design["seed_count"] == 29
    assert design["holm_family_size"] == protocol["panel_design"]["holm_family_size"] == 16
    assert design["holm_family_size"] == len(registry["models"])
    feasibility = exact_sign_flip_feasibility(29, 16)
    assert feasibility["feasible"]
    assert feasibility["holm_first_step_threshold"] == pytest.approx(0.003125)
    assert design["selected_allocation"]["minimum_exact_two_sided_sign_flip_p_value"] == pytest.approx(
        feasibility["minimum_two_sided_p_value"]
    )

    # The seed panel froze on 2026-09-01, so the real lane carries no
    # statistical-plan blocker; unfreezing it must still raise one.
    assert v5_statistical_plan_issues(lane, registry, protocol) == []
    unfrozen_panel_lane = copy.deepcopy(lane)
    unfrozen_panel_lane["seed_panel"].update(status="pending-authorized-generation")
    unfrozen_panel_lane["seed_panel"].pop("sha256")
    unfrozen_panel_lane["seed_panel"].pop("hiding_commitment_sha256")
    assert "seed panel identity is not frozen" in " ".join(
        publication_execution_issues(
            unfrozen_panel_lane,
            registry,
            manifest,
            phase="panel",
            protocol=protocol,
            pricing=pricing,
        )
    )


def test_v5_real_registry_builds_every_seed_free_smoke_cell(monkeypatch: pytest.MonkeyPatch) -> None:
    panel, lane, manifest, protocol, pricing = publication_runner.CONTRACT_CONFIGS["sota-v5"]
    monkeypatch.setattr(publication_runner, "PANEL_CONFIG", panel)
    monkeypatch.setattr(publication_runner, "LANE_CONFIG", lane)
    monkeypatch.setattr(publication_runner, "SMOKE_MANIFEST", manifest)
    monkeypatch.setattr(publication_runner, "PROTOCOL_CONFIG", protocol)
    monkeypatch.setattr(publication_runner, "PRICING_CONFIG", pricing)

    cells = publication_runner.build_cells("smoke", authorization_phase="route-preflight")

    assert len(cells) == 16
    assert {cell.experiment_id for cell in cells} == set(_read(panel)["required_smokes"])


def _fireworks_smoke_entry_placeholder(registry: dict[str, Any], withdrawn_entry: dict[str, Any]) -> dict[str, Any]:
    """Shape the withdrawn DeepInfra entry as if the Fireworks cell had been recorded.

    Only route identity fields change; every telemetry field is the withdrawn
    row's. This stands in for the pending Fireworks smoke so the rest of the
    panel path (frozen status, cap, run order) can still be exercised.
    """
    model = next(m for m in registry["models"] if m["id"] == "openrouter-glm-5.3-flash-fireworks")
    entry = copy.deepcopy(withdrawn_entry)
    for key in ("upstream_provider", "upstream_provider_slug", "endpoint_tag", "endpoint_name"):
        entry[key] = model[key]
    return entry


def _patched_read_json(runner: Any, manifest_path: Path, replacement: dict[str, Any]) -> Any:
    original = runner._read_json

    def read(path: Path) -> Any:
        if Path(path) == Path(manifest_path):
            return copy.deepcopy(replacement)
        return original(path)

    return read


def test_v5_real_registry_builds_every_panel_cell_once_the_owner_flips_the_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The only remaining panel locks must be the authorization flags and the seeds.

    Everything else the runner checks on the panel path (frozen output-budget
    status, frozen registry, accepted manifest, cap) must already pass on the
    committed configs, or flipping the flags would still not start the run.
    """
    panel, lane, manifest, protocol, pricing = publication_runner.CONTRACT_CONFIGS["sota-v5"]
    monkeypatch.setattr(publication_runner, "PANEL_CONFIG", panel)
    monkeypatch.setattr(publication_runner, "LANE_CONFIG", lane)
    monkeypatch.setattr(publication_runner, "SMOKE_MANIFEST", manifest)
    monkeypatch.setattr(publication_runner, "PROTOCOL_CONFIG", protocol)
    monkeypatch.setattr(publication_runner, "PRICING_CONFIG", pricing)
    # Stand in for the owner's flag flip and the Keychain-verified seed panel.
    monkeypatch.setattr(publication_runner, "_require_execution_authorized", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(publication_runner, "_validate_frozen_seed_panel", lambda _lane: None)

    # Until the Fireworks glm-5.3-flash cell holds an accepted one-call smoke
    # (its DeepInfra smoke was withdrawn with the route on 2026-09-02), the
    # missing manifest entry is the one remaining lock on the panel path.
    with pytest.raises(ValueError, match="openrouter-glm-5.3-flash-fireworks' has no smoke manifest entry"):
        publication_runner.build_cells("panel")
    accepted_manifest = copy.deepcopy(_read(manifest))
    accepted_manifest["entries"]["openrouter-glm-5.3-flash-fireworks"] = _fireworks_smoke_entry_placeholder(
        _read(panel), accepted_manifest["withdrawn_entries_2026_09_02"]["entries"]["openrouter-glm-5.3-flash-deepinfra"]
    )
    accepted_manifest["accepted_for_panel"] = True
    monkeypatch.setattr(
        publication_runner, "_read_json", _patched_read_json(publication_runner, manifest, accepted_manifest)
    )

    cells = publication_runner.build_cells("panel")

    assert len(cells) == 16
    assert {cell.experiment_id for cell in cells} == set(_read(panel)["required_smokes"])
    assert {cell.seed_count for cell in cells} == {29}
    assert {cell.cap for cell in cells} == {4096}
    assert {(cell.preset, cell.repeats) for cell in cells} == {("leaderboard", 1)}
    # The protocol promises the cheapest rows run first; the runner must honor it.
    frozen_order = [entry["experiment_id"] for entry in _read(panel)["ascending_cost_run_order"]["order"]]
    assert [cell.experiment_id for cell in cells] == frozen_order
    assert cells[0].experiment_id == "openrouter-gpt-oss-20b-deepinfra"
    assert cells[-1].experiment_id == "openrouter-grok-4.6-xai"


def test_v5_authorizations_match_the_owner_instructions() -> None:
    lane, registry, protocol, pricing, manifest = _configs()
    records = (lane, registry, protocol, pricing)

    assert all(record["route_preflight_authorized"] is True for record in records)
    # All sixteen routes were re-accepted by the authenticated zero-completion
    # preflight after the 2026-09-01 route-and-cohort amendment; the earlier
    # sixteen-route acceptance and the withdrawn eight-route acceptance both
    # stay recorded as superseded rather than silently deleted.
    acceptance = registry["exact_route_acceptance"]
    assert acceptance["status"] == "accepted"
    assert len(acceptance["entries"]) == 16
    assert set(acceptance["entries"]) == set(registry["required_smokes"])
    superseded = acceptance["superseded_acceptance"]
    assert [record["model_count"] for record in superseded] == [16, 16, 16, 16, 16, 8]
    assert all(record["status"] == "accepted" for record in superseded)
    assert superseded[0]["evidence_artifact"].endswith("-superseded.json")
    # Spend and smoke execution were authorized on the owner's explicit
    # 2026-09-01 instruction, and panel execution on the owner's 2026-09-02
    # instruction once all sixteen one-call smokes were accepted; publication
    # stays locked until the panel artifacts pass the publication gate.
    for record in records:
        assert record["spend_authorized"] is True
        assert record["smoke_execution_authorized"] is True
        assert record["panel_execution_authorized"] is True
        assert record["publication_authorized"] is False
    assert protocol["budget_policy"]["spend_authorized"] is True
    assert lane["final_preflight_evidence"]["status"] == "accepted"
    assert lane["final_preflight_evidence"]["completion_calls"] == 0
    assert manifest["format"] == "gm-bench-smoke-manifest-v1"
    # The sixteen 2026-09-01 smokes were invalidated after review: the
    # fail-fast wrapper had dropped pays_for_calls, so they ran with the
    # five-round query loop open instead of the frozen one-call rule. They
    # stay recorded as invalidated evidence, and the manifest is not accepted
    # until every row is re-recorded from a smoke run under the fixed rule.
    assert lane["paid_calls_per_decision"] == V6_PAID_CALLS_PER_DECISION == 1
    # Fifteen registered rows hold one-call smokes with exactly four calls.
    # The z-ai/glm-5.3-flash row moved from DeepInfra fp8 back to Fireworks on
    # 2026-09-02 (DeepInfra fell under the uptime floor), so its accepted
    # DeepInfra smoke is withdrawn with the route and the Fireworks cell must
    # earn its own before the manifest is accepted for panel again.
    assert manifest["accepted_for_panel"] is False
    assert set(manifest["entries"]) == set(registry["required_smokes"]) - {"openrouter-glm-5.3-flash-fireworks"}
    withdrawn = manifest["withdrawn_entries_2026_09_02"]["entries"]
    assert set(withdrawn) == {"openrouter-glm-5.3-flash-deepinfra"}
    for entry in [*manifest["entries"].values(), *withdrawn.values()]:
        assert entry["api_calls"] == 4
    invalidated = manifest["invalidated_entries_2026_09_01"]["entries"]
    assert len(invalidated) == 16
    # Fourteen of the invalidated artifacts bought extra query rounds; the
    # exact-count gate must refuse every one of those.
    replayed = {**manifest, "entries": invalidated, "accepted_for_panel": True}
    replayed_issues = smoke_manifest_issues(replayed, registry, lane)
    exact_issues = [issue for issue in replayed_issues if "exactly" in issue]
    # Thirteen of those rows are still registered; the fourteenth is the
    # withdrawn DeepInfra glm-5.3-flash cell, which the gate now rejects as
    # stale before it counts calls.
    assert len(exact_issues) == 13
    assert any(
        "openrouter-glm-5.3-flash-deepinfra" in issue and "not in the current model registry" in issue
        for issue in replayed_issues
    )
    panel_issues = publication_execution_issues(
        lane, registry, manifest, phase="panel", protocol=protocol, pricing=pricing
    )
    # With the flags flipped, the only remaining panel lock is the missing
    # Fireworks smoke.
    assert panel_issues == [
        "sota-v5 smoke manifest is not accepted for panel execution",
        "registered model 'openrouter-glm-5.3-flash-fireworks' has no smoke manifest entry",
    ]
    # Withdrawing the registry's panel authorization alone must re-lock it.
    unauthorized_registry = copy.deepcopy(registry)
    unauthorized_registry["panel_execution_authorized"] = False
    relocked_panel = publication_execution_issues(
        lane, unauthorized_registry, manifest, phase="panel", protocol=protocol, pricing=pricing
    )
    assert "panel execution is locked by the model registry" in relocked_panel
    for phase in ("route-preflight", "smoke"):
        assert (
            publication_execution_issues(
                lane,
                registry,
                manifest,
                phase=phase,
                protocol=protocol,
                pricing=pricing,
            )
            == []
        )
    # Withdrawing any single authorization must re-lock the smoke phase.
    unauthorized_lane = copy.deepcopy(lane)
    unauthorized_lane["smoke_execution_authorized"] = False
    relocked = publication_execution_issues(
        unauthorized_lane,
        registry,
        manifest,
        phase="smoke",
        protocol=protocol,
        pricing=pricing,
    )
    assert any("smoke_execution_authorized is false" in issue for issue in relocked)
    panel_issues = publication_execution_issues(
        lane,
        registry,
        manifest,
        phase="panel",
        protocol=protocol,
        pricing=pricing,
    )
    # Attested on 2026-09-01, so the real lane no longer raises the attestation
    # blocker; resetting the attestation must still bring it back.
    assert not any("owner attestation before private seed access" in issue for issue in panel_issues)
    unattested_lane = copy.deepcopy(lane)
    unattested_lane["seed_panel"]["owner_attestation_status"] = "pending-before-seed-access"
    unattested_issues = publication_execution_issues(
        unattested_lane,
        registry,
        manifest,
        phase="panel",
        protocol=protocol,
        pricing=pricing,
    )
    assert any("owner attestation before private seed access" in issue for issue in unattested_issues)


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


def test_v5_cost_plan_states_where_the_hundred_dollar_ceiling_bites() -> None:
    lane, registry, protocol, pricing, _ = _configs()
    estimate = _read(ROOT / "results/analysis/sota-v6-panel-cost-estimate.json")
    budget = protocol["budget_policy"]

    assert lane["cost_estimate_artifact"] == "results/analysis/sota-v6-panel-cost-estimate.json"
    assert budget["cost_estimate_artifact"] == lane["cost_estimate_artifact"]
    # The retired artifact is kept, not overwritten, and is named as retired.
    assert lane["superseded_cost_estimate_artifact"] == "results/analysis/sota-v5-pre-smoke-cost-estimate.json"
    assert (ROOT / lane["superseded_cost_estimate_artifact"]).is_file()

    assert estimate["calls"] == {
        "model_count": 16,
        "panel_decisions_per_model": 580,
        "panel_calls": 9280,
        "smoke_runs": 16,
        "smoke_decisions_per_run": 4,
        "smoke_calls": 64,
        "total_calls": 9344,
    }
    # Zero configured repairs and one paid call per phase: the plan and the
    # protocol maximum are the same run.
    assert estimate["protocol_maximum"]["paid_calls_per_decision"] == 1
    assert estimate["protocol_maximum"]["total_calls"] == estimate["calls"]["total_calls"]
    assert estimate["protocol_maximum"]["costs_usd"]["panel"] == pytest.approx(estimate["costs_usd"]["panel"])

    assert budget["operator_ceiling_usd"] == 100.0
    assert budget["expected_base_spend_usd"] == 75.0
    assert budget["spend_enforcement"] == "dynamic-pre-provider-call"
    # The honest statement of the plan: the cap-priced maximum does NOT fit
    # under the ceiling, and the runner's dynamic guard is what enforces it.
    assert estimate["costs_usd"]["panel"] > budget["operator_ceiling_usd"]
    assert budget["cost_components_usd"]["cap_priced_panel"] == pytest.approx(estimate["costs_usd"]["panel"], abs=1e-3)
    assert budget["cost_components_usd"]["cap_priced_total_with_contingency"] == pytest.approx(
        estimate["costs_usd"]["total_with_1_2x_contingency"], abs=1e-3
    )
    # A 2x completion overrun on the expected ~1,000-token reply still fits.
    input_only = budget["cost_components_usd"]["input_only_at_8000_tokens"]
    per_thousand = budget["cost_components_usd"]["per_1000_completion_tokens_across_the_panel"]
    assert input_only + 2 * per_thousand < budget["operator_ceiling_usd"]
    assert {row["experiment_id"] for row in estimate["models"]} == set(registry["required_smokes"])


def test_v5_run_order_spends_the_cheapest_rows_first() -> None:
    _, registry, _, _, _ = _configs()
    estimate = _read(ROOT / "results/analysis/sota-v6-panel-cost-estimate.json")
    order = registry["ascending_cost_run_order"]["order"]
    by_id = {row["experiment_id"]: row["panel_cost_usd"] for row in estimate["models"]}

    assert [row["experiment_id"] for row in order] == sorted(by_id, key=lambda key: (by_id[key], key))
    assert [row["planning_panel_cost_usd"] for row in order] == sorted(row["planning_panel_cost_usd"] for row in order)
    for row in order:
        assert row["planning_panel_cost_usd"] == pytest.approx(by_id[row["experiment_id"]], abs=1e-3)
    # The frontier slot is the most expensive row and therefore the last money
    # committed.
    assert order[-1]["experiment_id"] == "openrouter-grok-4.6-xai"
    assert registry["ascending_cost_run_order"]["planning_panel_total_usd"] == pytest.approx(
        estimate["costs_usd"]["panel"], abs=1e-3
    )
