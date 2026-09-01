from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import gm_bench.publication as publication
import scripts.run_publication_matrix as publication_runner
from gm_bench.contract import BENCHMARK_VERSION, contract_fingerprint, scaffold_fingerprint
from gm_bench.publication import (
    PENDING_STRICT_SMOKE_CAP_VERIFICATION,
    canonical_sha256,
    v3_route_acceptance_issues,
    v3_route_identity_sha256,
)
from scripts.run_publication_matrix import (
    _artifact_spend_usd,
    _call_spend_guard_environment,
    _cell_reservation_usd,
    _endpoint_issues,
    _panel_artifact_issues,
    _reconcile_spend_guard,
    _record_failed_cell_reservation,
    _record_ineligible_cell_reservation,
    _require_paid_smoke_attempt_authorized,
    _reserve_cell,
    _settle_cell_reservation,
    _write_run_state,
    build_cells,
    cell_command,
    cell_environment,
    publication_run_status,
    render_publication_status,
)
from scripts.run_publication_matrix import (
    main as _runner_main,
)


def main(argv: list[str]) -> int:
    """Keep runner tests explicit about the lane selected by their fixture."""
    if argv[0] != "sweep" and "--contract" not in argv:
        selected = json.loads(publication_runner.PANEL_CONFIG.read_text())["contract"]
        argv = [argv[0], "--contract", selected, *argv[1:]]
    return _runner_main(argv)


@pytest.fixture(autouse=True)
def _reset_publication_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent one in-process CLI invocation from leaking its lane to another test."""
    panel, lane, manifest, protocol, pricing = publication_runner.CONTRACT_CONFIGS["sota-v2"]
    monkeypatch.setattr(publication_runner, "PANEL_CONFIG", panel)
    monkeypatch.setattr(publication_runner, "LANE_CONFIG", lane)
    monkeypatch.setattr(publication_runner, "SMOKE_MANIFEST", manifest)
    monkeypatch.setattr(publication_runner, "PROTOCOL_CONFIG", protocol)
    monkeypatch.setattr(publication_runner, "PRICING_CONFIG", pricing)


def test_v4_publication_paths_and_strict_capabilities_are_explicit() -> None:
    panel, lane, manifest, protocol, pricing = publication_runner.CONTRACT_CONFIGS["sota-v4"]

    assert panel.name == "sota_v4_models.json"
    assert lane.name == "sota_v4_lane.json"
    assert manifest.name == "sota_v4_smoke_manifest.json"
    assert protocol.name == "sota_v4_publication_protocol.json"
    assert pricing.name == "sota_v4_pricing_snapshot.json"
    assert publication_runner.STRICT_PRIVATE_PANEL_CONTRACTS == {"sota-v3", "sota-v4", "sota-v5"}
    assert publication_runner.AUTHENTICATED_ROUTE_CONTRACTS == {"sota-v3", "sota-v4", "sota-v5"}


def test_v4_consumed_paid_smoke_authorization_rejects_another_attempt(tmp_path: Path) -> None:
    publication_runner._select_contract_config("sota-v4")
    qwen = build_cells("route-preflight", model_id="openrouter-qwen3.8-max-alibaba")[0]

    with pytest.raises(ValueError, match="exactly one remaining attempt"):
        _require_paid_smoke_attempt_authorized([qwen], tmp_path)


def _frozen_panel_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict, dict, Path]:
    monkeypatch.setattr(publication, "_REPO_ROOT", tmp_path)
    registry = json.loads(Path("config/sota_v2_models.json").read_text())
    registry["contract"] = BENCHMARK_VERSION
    registry["contract_fingerprint"] = contract_fingerprint()
    registry["selection_status"] = "frozen"
    registry["provider"] = "openrouter"
    registry["spend_authorized"] = True
    registry["route_preflight_authorized"] = True
    registry["panel_execution_authorized"] = True
    paid_smoke_authorization = {
        "scope": "single-model-single-infrastructure-attempt",
        "model_id": registry["models"][0]["id"],
        "attempt_number": 1,
        "remaining_attempts": 1,
    }
    registry["paid_smoke_authorization"] = paid_smoke_authorization
    registry["exact_route_acceptance"] = {
        "schema_version": 1,
        "status": "accepted",
        "accepted_at_utc": "2026-07-30T00:00:00Z",
        "privacy_standard": {
            "data_classification": "synthetic-benchmark-no-personal-or-confidential-data",
            "provider_data_collection": "deny",
            "provider_training_use_allowed": False,
            "zero_data_retention_required": False,
        },
        "entries": {
            model["id"]: {
                "route_identity_sha256": v3_route_identity_sha256(registry, model),
                "authenticated": True,
                "verified_at_utc": "2026-07-30T00:00:00Z",
                "route_evidence_sha256": "d" * 64,
                "privacy_acceptance": {
                    "status": "accepted",
                    "route_identity_sha256": v3_route_identity_sha256(registry, model),
                    "data_collection_policy_accepted": True,
                    "retention_policy_accepted": True,
                    "training_use_policy_accepted": True,
                    "zero_data_retention_endpoint": True,
                    "zero_data_retention_requirement_satisfied": True,
                    "accepted_at_utc": "2026-07-30T00:00:00Z",
                    "evidence_sha256": "e" * 64,
                },
            }
            for model in registry["models"]
        },
    }
    evidence = {
        "format": "gm-bench-route-acceptance-evidence-v1",
        "contract": BENCHMARK_VERSION,
        "contract_fingerprint": contract_fingerprint(),
        "completion_calls": 0,
        "generated_at_utc": "2026-07-30T00:00:00Z",
        "privacy_standard": registry["exact_route_acceptance"]["privacy_standard"],
        "official_policy_sources": [],
        "routes": {},
    }
    for model_id, entry in registry["exact_route_acceptance"]["entries"].items():
        route = {
            "route_identity_sha256": entry["route_identity_sha256"],
            "zero_data_retention_endpoint": True,
            "provider_policy": {},
        }
        evidence["routes"][model_id] = route
        entry["route_evidence_sha256"] = canonical_sha256(route)
        entry["privacy_acceptance"]["evidence_sha256"] = canonical_sha256(
            {
                "route_identity_sha256": route["route_identity_sha256"],
                "privacy_standard": evidence["privacy_standard"],
                "zero_data_retention_endpoint": True,
                "provider_policy": {},
                "official_policy_sources": [],
            }
        )
    evidence_path = tmp_path / "route-evidence.json"
    evidence_path.write_text(json.dumps(evidence))
    registry["exact_route_acceptance"]["evidence_artifact"] = evidence_path.name
    private_seeds = list(range(101, 110))
    monkeypatch.setenv("GM_BENCH_PRIVATE_SEEDS", ",".join(str(seed) for seed in private_seeds))
    lane = json.loads(Path("config/sota_v2_lane.json").read_text())
    lane["contract"] = BENCHMARK_VERSION
    lane["contract_fingerprint"] = contract_fingerprint()
    lane["preregistration_status"] = "frozen"
    lane["panel_design_status"] = "frozen"
    lane["spend_authorized"] = True
    lane["route_preflight_authorized"] = True
    lane["smoke_execution_authorized"] = True
    lane["panel_execution_authorized"] = True
    lane["paid_smoke_authorization"] = paid_smoke_authorization
    lane["output_budget_status"] = "frozen-native-reasoning-cap"
    lane["execution_profile_authority"] = "lane"
    lane["headline_lane"] = registry["lane"]
    lane["provider"] = registry["provider"]
    lane["observation_profile"] = registry["profile"]
    lane["preset"] = registry["preset"]
    lane["session"] = registry["session"]
    lane["repeats"] = registry["repeats"]
    lane["minimum_headline_models"] = len(registry["models"])
    lane["reference_agent"] = "pick-trader"
    lane["cap_pressure_threshold_tokens"] = 3072
    lane["fallback_output_token_cap"] = 8192
    lane["statistical_panel_design"] = {
        "status": "frozen",
        "holm_family_size": len(registry["models"]),
        "target_effect_score_points": -100,
        "selected_allocation": {
            "seed_count": len(private_seeds),
            "repeats": registry["repeats"],
            "episodes_per_model": len(private_seeds) * registry["repeats"],
        },
    }
    lane["seed_panel"] = {
        "status": "frozen",
        "name": "private-env",
        "count": len(private_seeds),
        "sha256": hashlib.sha256(",".join(str(seed) for seed in private_seeds).encode()).hexdigest(),
        "hiding_commitment_sha256": "c" * 64,
        "owner_attestation_required": True,
        "owner_attestation_status": "attested-before-seed-access",
    }
    final_evidence_path = tmp_path / "final-preflight.json"
    final_evidence = {
        "format": f"gm-bench-{BENCHMARK_VERSION}-final-preflight-v1",
        "schema_version": 1,
        "contract": BENCHMARK_VERSION,
        "contract_fingerprint": contract_fingerprint(),
        "openrouter_scaffold_fingerprint": scaffold_fingerprint("openrouter"),
        "generated_at_utc": "2026-07-30T00:01:00Z",
        "canonical_openrouter_api_base": "https://openrouter.ai/api/v1",
        "completion_calls": 0,
        "route_preflight": {
            "status": "accepted",
            "evidence_artifact": evidence_path.name,
            "evidence_sha256": canonical_sha256(evidence),
            "verified_at_utc": evidence["generated_at_utc"],
        },
        "smoke_command_dry_run": {
            "status": "passed",
            "model_ids": [model["id"] for model in registry["models"]],
            "commands_constructed": len(registry["models"]),
            "operator_ceiling_usd": 100.0,
            "seed_panel_sha256": lane["seed_panel"]["sha256"],
            "hiding_commitment_verified": False,
            "private_seed_accessed": False,
            "private_seed_values_included": False,
        },
        "authenticated_route_and_price_preflight": {
            "status": "passed",
            "model_ids": [model["id"] for model in registry["models"]],
            "commands_executed": len(registry["models"]),
            "completion_calls": 0,
            "canonical_openrouter_api_base": "https://openrouter.ai/api/v1",
            "pricing_checked": True,
        },
    }
    final_evidence_path.write_text(json.dumps(final_evidence))
    lane["final_preflight_evidence"] = {
        "status": "accepted",
        "artifact": final_evidence_path.name,
        "sha256": canonical_sha256(final_evidence),
        "contract_fingerprint": contract_fingerprint(),
        "completion_calls": 0,
        "operator_ceiling_usd": 100.0,
    }
    lane.pop("smoke_manifest", None)
    registry_path = tmp_path / "models.json"
    lane_path = tmp_path / "lane.json"
    manifest_path = tmp_path / "smokes.json"
    protocol_path = tmp_path / "protocol.json"
    pricing_path = tmp_path / "pricing.json"
    registry_path.write_text(json.dumps(registry))
    lane_path.write_text(json.dumps(lane))
    protocol = json.loads(Path("config/publication_protocol.json").read_text())
    protocol.update(
        {
            "contract": BENCHMARK_VERSION,
            "contract_fingerprint": contract_fingerprint(),
            "status": "frozen",
        }
    )
    protocol["budget_policy"]["spend_authorized"] = True
    protocol["budget_policy"]["operator_ceiling_usd"] = 100.0
    protocol["paid_smoke_authorization"] = paid_smoke_authorization
    protocol["statistical_analysis_plan"] = {
        "status": "frozen",
        "analysis_mode": "reference-only",
        "inference_method": "exact-enumeration-sign-flip",
        "unit_of_inference": "seed",
        "primary_contrast": "paired lift versus pick-trader",
        "reference_agent": "pick-trader",
        "multiplicity_method": "holm-bonferroni",
        "alpha": 0.05,
        "holm_family_size": len(registry["models"]),
        "target_effect_score_points": -100,
    }
    protocol["output_policy"] = {
        "output_token_cap": lane["output_token_cap"],
        "cap_pressure_threshold_tokens": lane["cap_pressure_threshold_tokens"],
        "fallback_output_token_cap": lane["fallback_output_token_cap"],
    }
    protocol_path.write_text(json.dumps(protocol))
    pricing = json.loads(Path("config/openrouter_pricing_snapshot.json").read_text())
    pricing.update(
        {
            "contract": BENCHMARK_VERSION,
            "contract_fingerprint": contract_fingerprint(),
            "status": "frozen",
            "spend_authorized": True,
        }
    )
    pricing["planning_assumptions"]["expected_output_tokens_per_decision"] = lane["output_token_cap"]
    pricing["planning_assumptions"]["cost_contingency_multiplier"] = 1.2
    pricing["paid_smoke_authorization"] = paid_smoke_authorization
    pricing_path.write_text(json.dumps(pricing))
    manifest_path.write_text(
        json.dumps(
            {
                "format": "gm-bench-smoke-manifest-v1",
                "schema_version": 1,
                "contract": BENCHMARK_VERSION,
                "contract_fingerprint": contract_fingerprint(),
                "status": "not-started",
                "accepted_for_panel": False,
                "entries": {},
            }
        )
    )
    monkeypatch.setattr(publication_runner, "PANEL_CONFIG", registry_path)
    monkeypatch.setattr(publication_runner, "LANE_CONFIG", lane_path)
    monkeypatch.setattr(publication_runner, "SMOKE_MANIFEST", manifest_path)
    monkeypatch.setattr(publication_runner, "PROTOCOL_CONFIG", protocol_path)
    monkeypatch.setattr(publication_runner, "PRICING_CONFIG", pricing_path)
    monkeypatch.setitem(
        publication_runner.CONTRACT_CONFIGS,
        BENCHMARK_VERSION,
        (registry_path, lane_path, manifest_path, protocol_path, pricing_path),
    )
    return registry, lane, manifest_path


@pytest.mark.parametrize(
    "mutation",
    [
        "route",
        "model-option",
        "shared-option",
        "reasoning-policy",
        "output-cap",
        "supported-parameters",
        "absent-options",
        "privacy-control",
    ],
)
def test_exact_route_acceptance_digest_stales_on_execution_policy_edits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    registry, _lane, _manifest_path = _frozen_panel_files(tmp_path, monkeypatch)
    assert v3_route_acceptance_issues(registry) == []
    model = registry["models"][0]

    if mutation == "route":
        model["endpoint_name"] = f"{model['endpoint_name']} changed"
    elif mutation == "model-option":
        model.setdefault("fixed_options", {})["OPENROUTER_REASONING_ENABLED"] = "changed"
    elif mutation == "shared-option":
        registry.setdefault("shared_fixed_options", {})["OPENROUTER_JSON_MODE"] = "changed"
    elif mutation == "reasoning-policy":
        model["reasoning_policy"] = "changed"
    elif mutation == "output-cap":
        registry["output_token_cap"] += 1
    elif mutation == "supported-parameters":
        model.setdefault("catalog_supported_parameters", []).append("changed")
    elif mutation == "absent-options":
        model.setdefault("absent_options", []).append("OPENROUTER_CHANGED")
    else:
        registry.setdefault("shared_fixed_options", {})["OPENROUTER_DATA_COLLECTION"] = "changed"

    issues = v3_route_acceptance_issues(registry)
    assert any("does not bind to the registered route identity" in issue for issue in issues)


def test_exact_route_acceptance_rejects_cross_contract_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, _lane, _manifest_path = _frozen_panel_files(tmp_path, monkeypatch)
    evidence_path = tmp_path / str(registry["exact_route_acceptance"]["evidence_artifact"])
    evidence = json.loads(evidence_path.read_text())
    evidence["contract"] = "sota-v3"
    evidence_path.write_text(json.dumps(evidence))

    issues = v3_route_acceptance_issues(registry)

    assert any("different contract" in issue for issue in issues)


def _valid_manifest(registry: dict, lane: dict) -> dict:
    entries = {}
    for model in registry["models"]:
        entries[model["id"]] = {
            "provider": model["provider"],
            "model": model["model"],
            "upstream_provider": model["upstream_provider"],
            "upstream_provider_slug": model["upstream_provider_slug"],
            "endpoint_tag": model["endpoint_tag"],
            "endpoint_name": model["endpoint_name"],
            "reasoning_policy": model["reasoning_policy"],
            "reasoning_effort": model["reasoning_effort"],
            "output_token_cap": lane["output_token_cap"],
            "api_calls": 4,
            "calls_with_finish_reason": 4,
            "decisions_with_usage": 4,
            "cost_decisions": 4,
            "truncated_calls": 0,
            "max_output_tokens_per_call": 100,
            "reasoning_tokens": 0,
            "decision_failure_rate": 0,
            "contract_fingerprint": contract_fingerprint(),
            "scaffold_fingerprint": scaffold_fingerprint(model["provider"]),
            "artifact_sha256": "a" * 64,
            "strict_fallback": True,
            "accepted": True,
        }
    return {
        "format": "gm-bench-smoke-manifest-v1",
        "schema_version": 1,
        "contract": BENCHMARK_VERSION,
        "contract_fingerprint": contract_fingerprint(),
        "accepted_for_panel": True,
        "entries": entries,
    }


def _valid_smoke_artifact(registry: dict, lane: dict, model: dict) -> dict:
    return {
        "seeds": [1],
        "seasons": 1,
        "run_info": {
            "provider": model["provider"],
            "model": model["model"],
            "profile": registry["profile"],
            "preset": "smoke",
            "strict_fallback": True,
            "provider_options": {
                **registry["shared_fixed_options"],
                **model["fixed_options"],
                "OPENROUTER_PROVIDER_ONLY": model["upstream_provider_slug"],
                "OPENROUTER_EXPECTED_UPSTREAM_PROVIDER": model["upstream_provider"],
                "OPENROUTER_EXPECTED_ENDPOINT_NAME": model["endpoint_name"],
                "GM_BENCH_OUTPUT_BUDGET_CELL": str(lane["output_token_cap"]),
            },
            "benchmark_contract": {
                "benchmark_version": lane["contract"],
                "contract_fingerprint": contract_fingerprint(),
            },
            "scaffold_fingerprint": scaffold_fingerprint(model["provider"]),
        },
        "candidate": {
            "seasons": 1,
            "repeats": 1,
            "episodes": [
                {
                    "seed": 1,
                    "repeat": 1,
                    "seasons": 1,
                    "decisions": 4,
                    "failed_decisions": 0,
                }
            ],
            "summary": {
                "decisions": 4,
                "failed_decisions": 0,
                "decision_failure_rate": 0,
                "usage": {
                    "provider": model["provider"],
                    "model": model["model"],
                    "decisions_with_usage": 4,
                    "cost_decisions": 4,
                    "protocol_repair_attempts": 0,
                    "protocol_repairs_succeeded": 0,
                    "api_calls": 4,
                    "calls_with_finish_reason": 4,
                    "truncated_calls": 0,
                    "max_output_tokens_per_call": 100,
                    "reasoning_tokens": 0,
                    "upstream_providers": [model["upstream_provider"].lower()],
                },
            },
        },
    }


def test_sweep_matrix_is_pre_registered_and_serial(tmp_path: Path) -> None:
    cells = build_cells("sweep")
    assert len(cells) == 12
    assert {cell.cap for cell in cells} == {256, 1024, 4096, 16384}
    assert len({cell.experiment_id for cell in cells}) == 3
    for cell in cells:
        env = cell_environment(cell)
        command = cell_command(cell, tmp_path)
        assert env["GM_BENCH_WORKERS"] == "1"
        assert env["OPENROUTER_PROVIDER_ONLY"] == cell.fixed_options["OPENROUTER_PROVIDER_ONLY"]
        assert command[:4] == [sys.executable, "-m", "gm_bench", "model"]
        assert command[command.index("--workers") + 1] == "1"
        assert "--resume" not in command


def test_bounded_cell_overrides_inherited_provider_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_MAX_TOKENS", "999")
    cell = next(cell for cell in build_cells("sweep") if cell.cap == 16384)
    env = cell_environment(cell)
    assert env["OPENROUTER_MAX_TOKENS"] == "16384"
    assert env["GM_BENCH_OUTPUT_BUDGET_CELL"] == "16384"


def test_publication_cells_pin_strict_failure_handling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GM_AGENT_STRICT", "0")
    for lane in ("smoke", "sweep"):
        for cell in build_cells(lane):
            assert cell_environment(cell)["GM_AGENT_STRICT"] == "1"


def test_publication_cells_keep_strict_after_registry_fixed_options(monkeypatch: pytest.MonkeyPatch) -> None:
    from dataclasses import replace

    monkeypatch.setenv("GM_AGENT_STRICT", "0")
    cell = build_cells("smoke")[0]
    loosened = replace(cell, fixed_options={**cell.fixed_options, "GM_AGENT_STRICT": "0"})
    assert cell_environment(loosened)["GM_AGENT_STRICT"] == "1"


def test_paid_cell_pins_travel_in_the_config_env_block(tmp_path: Path) -> None:
    """Provider pins outrank ambient env at adapter launch, so a cell pin
    passed only as ambient env (a mandatory-reasoning row's
    OPENROUTER_REASONING_ENABLED=true) would be stomped back to the provider
    default. The paid command must carry the pins in the --config env block,
    the channel that outranks provider pins and is recorded in
    provider_options."""
    cell = build_cells("smoke")[0]
    command = cell_command(cell, tmp_path)
    config_path = Path(command[command.index("--config") + 1])
    payload = json.loads(config_path.read_text())
    env = payload["env"]
    assert env["OPENROUTER_REASONING_ENABLED"] == cell.fixed_options["OPENROUTER_REASONING_ENABLED"]
    assert env["OPENROUTER_MAX_TOKENS"] == str(cell.cap)
    for key, value in cell.fixed_options.items():
        assert env[key] == value
    # Absent options must not sneak in through the config block either.
    for key in cell.absent_options:
        assert key not in env
    # Preflight commands make no completion call and stay config-free.
    assert "--config" not in cell_command(cell, tmp_path, preflight=True)


def test_runner_rejects_cap_outside_pre_registered_sweep() -> None:
    with pytest.raises(ValueError, match="not in the pre-registered sweep"):
        build_cells("sweep", cap=999)


def test_smoke_is_clean_and_resumes_existing_checkpoint(tmp_path: Path) -> None:
    assert len(build_cells("smoke")) == 10
    cell = build_cells("smoke", model_id="openrouter-qwen3.7-plus-alibaba")[0]
    command = cell_command(cell, tmp_path)
    assert cell.preset == "smoke"
    assert cell.repeats == 1
    assert cell.seed_count is None  # frozen sota-v2 keeps its preset-derived reservation behavior
    assert cell.cap == 4096
    assert "--require-clean" in command
    checkpoint = tmp_path / "checkpoints" / f"{cell.experiment_id}--4096.json"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.touch()
    assert "--resume" in cell_command(cell, tmp_path)


def test_smoke_retry_archives_empty_aborted_stale_checkpoint(tmp_path: Path) -> None:
    cell = build_cells("smoke")[0]
    stem = f"{cell.experiment_id}--{cell.cap_label}"
    checkpoint = tmp_path / "checkpoints" / f"{stem}.json"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_text(
        json.dumps(
            {
                "format": "gm-bench-model-checkpoint-v1",
                "status": "aborted",
                "provenance": {
                    "benchmark_contract": {"contract_fingerprint": contract_fingerprint()},
                    "scaffold_fingerprint": "superseded-scaffold",
                },
                "episodes": [],
                "completed": [],
            }
        )
    )
    (tmp_path / "openrouter-reservations.json").write_text(json.dumps({"cells": {stem: {"attempts": 1}}}))

    archived = publication_runner._prepare_smoke_retry_checkpoint(cell, tmp_path)

    assert archived == tmp_path / "checkpoints" / "failed-attempts" / f"{stem}--attempt-1.json"
    assert archived.is_file()
    assert not checkpoint.exists()
    assert "--resume" not in cell_command(cell, tmp_path)


def test_smoke_retry_preserves_current_checkpoint_for_resume(tmp_path: Path) -> None:
    cell = build_cells("smoke")[0]
    stem = f"{cell.experiment_id}--{cell.cap_label}"
    checkpoint = tmp_path / "checkpoints" / f"{stem}.json"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_text(
        json.dumps(
            {
                "format": "gm-bench-model-checkpoint-v1",
                "status": "aborted",
                "provenance": {
                    "benchmark_contract": {"contract_fingerprint": contract_fingerprint()},
                    "scaffold_fingerprint": scaffold_fingerprint(cell.provider),
                },
                "episodes": [],
                "completed": [],
            }
        )
    )

    assert publication_runner._prepare_smoke_retry_checkpoint(cell, tmp_path) is None
    assert checkpoint.is_file()
    assert "--resume" in cell_command(cell, tmp_path)


def test_smoke_retry_rejects_nonempty_stale_checkpoint_before_reservation(tmp_path: Path) -> None:
    cell = build_cells("smoke")[0]
    stem = f"{cell.experiment_id}--{cell.cap_label}"
    checkpoint = tmp_path / "checkpoints" / f"{stem}.json"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_text(
        json.dumps(
            {
                "format": "gm-bench-model-checkpoint-v1",
                "status": "aborted",
                "provenance": {
                    "benchmark_contract": {"contract_fingerprint": contract_fingerprint()},
                    "scaffold_fingerprint": "superseded-scaffold",
                },
                "episodes": [{"seed": 1}],
                "completed": [{"seed": 1, "repeat": 1}],
            }
        )
    )

    with pytest.raises(ValueError, match="not an empty aborted attempt"):
        publication_runner._prepare_smoke_retry_checkpoint(cell, tmp_path)

    assert checkpoint.is_file()


def test_smoke_reuses_only_existing_artifact_that_passes_current_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, lane, _manifest_path = _frozen_panel_files(tmp_path, monkeypatch)
    model = registry["models"][0]
    cell = build_cells("smoke", model_id=model["id"])[0]
    raw = tmp_path / "raw"
    raw.mkdir()
    artifact_path = raw / f"{cell.experiment_id}--{cell.cap_label}.json"

    assert publication_runner._reusable_smoke_artifact(cell, tmp_path) is None
    artifact = _valid_smoke_artifact(registry, lane, model)
    artifact_path.write_text(json.dumps(artifact))
    assert publication_runner._reusable_smoke_artifact(cell, tmp_path) == artifact_path

    artifact["candidate"]["summary"]["failed_decisions"] = 1
    artifact_path.write_text(json.dumps(artifact))
    assert publication_runner._reusable_smoke_artifact(cell, tmp_path) is None


def test_preflight_only_still_validates_endpoint_despite_reusable_smoke_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--preflight-only must never take the cached-artifact shortcut that skips it."""
    registry, lane, _manifest_path = _frozen_panel_files(tmp_path, monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-preflight-key")
    model = registry["models"][0]
    cell = build_cells("smoke", model_id=model["id"])[0]
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    artifact_path = raw_dir / f"{cell.experiment_id}--{cell.cap_label}.json"
    artifact_path.write_text(json.dumps(_valid_smoke_artifact(registry, lane, model)))
    assert publication_runner._reusable_smoke_artifact(cell, tmp_path) == artifact_path

    validated: list[str] = []
    monkeypatch.setattr(
        publication_runner,
        "_validate_openrouter_endpoint",
        lambda cell, _env: validated.append(cell.experiment_id),
    )
    monkeypatch.setattr(
        publication_runner.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args=args, returncode=0),
    )

    assert (
        main(
            [
                "smoke",
                "--contract",
                BENCHMARK_VERSION,
                "--model-id",
                model["id"],
                "--run-dir",
                str(tmp_path),
                "--preflight-only",
            ]
        )
        == 0
    )
    assert validated == [cell.experiment_id]
    assert not (tmp_path / "openrouter-budget.json").exists()
    assert not (tmp_path / "openrouter-reservations.json").exists()
    assert not (tmp_path / publication_runner.CALL_SPEND_GUARD_STATE).exists()


def test_smoke_rejects_cap_that_differs_from_frozen_lane() -> None:
    with pytest.raises(ValueError, match="differs from frozen panel smoke cap"):
        build_cells("smoke", cap=1024)


def test_smoke_applies_each_models_registered_reasoning_policy() -> None:
    disabled = build_cells("smoke", model_id="openrouter-gpt-5.6-luna-openai")[0]
    mandatory = build_cells("smoke", model_id="openrouter-gemini-3.5-flash-google-ai-studio")[0]

    assert disabled.fixed_options["OPENROUTER_REASONING_ENABLED"] == "false"
    assert "OPENROUTER_REASONING_EFFORT" in disabled.absent_options
    assert mandatory.fixed_options["OPENROUTER_REASONING_ENABLED"] == "true"
    assert mandatory.fixed_options["OPENROUTER_REASONING_EFFORT"] == "minimal"
    assert mandatory.fixed_options["OPENROUTER_PROVIDER_ONLY"] == "google-ai-studio"


def _minimal_registered_model(**overrides: object) -> dict:
    model = {
        "id": "test-model",
        "provider": "openrouter",
        "model": "test/model",
        "upstream_provider": "Test",
        "upstream_provider_slug": "test",
        "endpoint_tag": "test",
        "endpoint_name": "Test | test/model",
        "reasoning_policy": "disabled",
        "reasoning_effort": None,
        "fixed_options": {"OPENROUTER_REASONING_ENABLED": "false"},
    }
    model.update(overrides)
    return model


def test_validate_models_rejects_disabled_policy_with_a_fixed_reasoning_effort() -> None:
    model = _minimal_registered_model(
        fixed_options={"OPENROUTER_REASONING_ENABLED": "false", "OPENROUTER_REASONING_EFFORT": "minimal"}
    )
    with pytest.raises(ValueError, match="invalid disabled reasoning policy"):
        publication_runner._validate_models([model])


def test_validate_models_rejects_mandatory_minimum_policy_with_no_effort_declared() -> None:
    model = _minimal_registered_model(
        reasoning_policy="mandatory-minimum",
        reasoning_effort=None,
        fixed_options={"OPENROUTER_REASONING_ENABLED": "true"},
    )
    with pytest.raises(ValueError, match="invalid mandatory reasoning policy"):
        publication_runner._validate_models([model])


def test_validate_sweep_models_rejects_invalid_cap_deferral() -> None:
    model = _minimal_registered_model(
        output_cap_verification=dict(PENDING_STRICT_SMOKE_CAP_VERIFICATION),
        catalog_supported_parameters=[],
    )
    with pytest.raises(ValueError, match="cannot defer cap verification"):
        publication_runner._validate_models([model], exact_routes=False)


def test_committed_v2_panel_is_locked_after_current_contract_advances() -> None:
    with pytest.raises(SystemExit):
        _runner_main(["panel", "--contract", "sota-v2", "--dry-run"])


def test_panel_stays_locked_when_frozen_registry_has_no_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _registry, _lane, manifest_path = _frozen_panel_files(tmp_path, monkeypatch)
    manifest_path.unlink()
    with pytest.raises(ValueError, match="smoke manifest is missing"):
        build_cells("panel")


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing", "has no smoke manifest entry"),
        ("not-accepted", "is not accepted"),
        ("truncated", "cap-induced truncation"),
        ("wrong-cap", "not frozen"),
        ("peak", "cap-pressure threshold"),
        ("wrong-scaffold", "different prompt scaffold"),
    ],
)
def test_panel_stays_locked_for_invalid_smoke_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    message: str,
) -> None:
    registry, lane, manifest_path = _frozen_panel_files(tmp_path, monkeypatch)
    manifest = _valid_manifest(registry, lane)
    model_id = registry["models"][0]["id"]
    if mutation == "missing":
        del manifest["entries"][model_id]
    elif mutation == "not-accepted":
        manifest["entries"][model_id]["accepted"] = False
    elif mutation == "truncated":
        manifest["entries"][model_id]["truncated_calls"] = 1
    elif mutation == "wrong-cap":
        manifest["entries"][model_id]["output_token_cap"] = 1024
    elif mutation == "peak":
        manifest["entries"][model_id]["max_output_tokens_per_call"] = 3072
    else:
        manifest["entries"][model_id]["scaffold_fingerprint"] = "wrong"
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match=message):
        build_cells("panel")


def test_panel_unlocks_with_complete_valid_smoke_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, lane, manifest_path = _frozen_panel_files(tmp_path, monkeypatch)
    manifest_path.write_text(json.dumps(_valid_manifest(registry, lane)))
    assert len(build_cells("panel")) == 10


@pytest.mark.parametrize("bad_reasoning_tokens", [True, -1])
def test_panel_stays_locked_for_invalid_manifest_reasoning_tokens(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bad_reasoning_tokens: object,
) -> None:
    registry, lane, manifest_path = _frozen_panel_files(tmp_path, monkeypatch)
    manifest = _valid_manifest(registry, lane)
    model = next(m for m in registry["models"] if m["reasoning_policy"] == "mandatory-minimum")
    manifest["entries"][model["id"]]["reasoning_tokens"] = bad_reasoning_tokens
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(ValueError, match="missing reasoning-token telemetry"):
        build_cells("panel")


def test_record_smoke_writes_accepted_manifest_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, lane, manifest_path = _frozen_panel_files(tmp_path, monkeypatch)
    model = registry["models"][0]
    artifact_path = tmp_path / "raw-smoke.json"
    artifact_path.write_text(json.dumps(_valid_smoke_artifact(registry, lane, model)))
    expected_sha = hashlib.sha256(artifact_path.read_bytes()).hexdigest()

    assert (
        main(
            [
                "record-smoke",
                "--model-id",
                model["id"],
                "--artifact",
                str(artifact_path),
                "--manifest",
                str(manifest_path),
            ]
        )
        == 0
    )
    manifest = json.loads(manifest_path.read_text())
    entry = manifest["entries"][model["id"]]
    assert manifest["status"] == "in-progress"
    assert manifest["accepted_for_panel"] is False
    assert entry["accepted"] is True
    assert entry["artifact_sha256"] == expected_sha
    assert entry["artifact_path"] == str(artifact_path)
    assert entry["decisions_with_usage"] == 4
    assert entry["cost_decisions"] == 4
    assert entry["protocol_repair_attempts"] == 0
    assert entry["protocol_repairs_succeeded"] == 0
    assert entry["strict_fallback"] is True


def test_record_smoke_refuses_a_soft_fallback_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    registry, lane, manifest_path = _frozen_panel_files(tmp_path, monkeypatch)
    model = registry["models"][0]
    artifact = _valid_smoke_artifact(registry, lane, model)
    artifact["run_info"]["strict_fallback"] = False
    artifact_path = tmp_path / "raw-smoke.json"
    artifact_path.write_text(json.dumps(artifact))

    assert (
        main(
            [
                "record-smoke",
                "--model-id",
                model["id"],
                "--artifact",
                str(artifact_path),
                "--manifest",
                str(manifest_path),
            ]
        )
        == 1
    )
    assert "strict failure handling" in capsys.readouterr().err
    assert json.loads(manifest_path.read_text())["entries"] == {}


def test_panel_stays_locked_for_a_soft_fallback_smoke_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, lane, manifest_path = _frozen_panel_files(tmp_path, monkeypatch)
    manifest = _valid_manifest(registry, lane)
    manifest["entries"][registry["models"][0]["id"]]["strict_fallback"] = False
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(ValueError, match="strict failure handling"):
        build_cells("panel")


def test_record_smoke_refuses_summary_only_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    registry, lane, manifest_path = _frozen_panel_files(tmp_path, monkeypatch)
    model = registry["models"][0]
    artifact = _valid_smoke_artifact(registry, lane, model)
    del artifact["candidate"]["episodes"]
    artifact_path = tmp_path / "incomplete-smoke.json"
    artifact_path.write_text(json.dumps(artifact))

    assert (
        main(
            [
                "record-smoke",
                "--model-id",
                model["id"],
                "--artifact",
                str(artifact_path),
                "--manifest",
                str(manifest_path),
            ]
        )
        == 1
    )
    assert "complete smoke episode" in capsys.readouterr().err
    assert json.loads(manifest_path.read_text())["entries"] == {}


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("decisions_with_usage", 1, "usage must cover all 4"),
        ("cost_decisions", 0, "cost telemetry must cover all 4"),
        ("provider", None, "usage provider does not match"),
        ("model", None, "usage model does not match"),
        ("provider", "other", "usage provider does not match"),
        ("model", "other/model", "usage model does not match"),
    ],
)
def test_record_smoke_refuses_incomplete_execution_telemetry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    field: str,
    value: object,
    message: str,
) -> None:
    registry, lane, manifest_path = _frozen_panel_files(tmp_path, monkeypatch)
    model = registry["models"][0]
    artifact = _valid_smoke_artifact(registry, lane, model)
    artifact["candidate"]["summary"]["usage"][field] = value
    artifact_path = tmp_path / f"incomplete-{field}.json"
    artifact_path.write_text(json.dumps(artifact))

    assert (
        main(
            [
                "record-smoke",
                "--model-id",
                model["id"],
                "--artifact",
                str(artifact_path),
                "--manifest",
                str(manifest_path),
            ]
        )
        == 1
    )
    assert message in capsys.readouterr().err
    assert json.loads(manifest_path.read_text())["entries"] == {}


def test_record_smoke_refuses_too_few_api_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    registry, lane, manifest_path = _frozen_panel_files(tmp_path, monkeypatch)
    model = registry["models"][0]
    artifact = _valid_smoke_artifact(registry, lane, model)
    usage = artifact["candidate"]["summary"]["usage"]
    usage["api_calls"] = 1
    usage["calls_with_finish_reason"] = 1
    artifact_path = tmp_path / "too-few-api-calls.json"
    artifact_path.write_text(json.dumps(artifact))

    assert (
        main(
            [
                "record-smoke",
                "--model-id",
                model["id"],
                "--artifact",
                str(artifact_path),
                "--manifest",
                str(manifest_path),
            ]
        )
        == 1
    )
    assert "at least 4 API calls" in capsys.readouterr().err
    assert json.loads(manifest_path.read_text())["entries"] == {}


def test_record_smoke_requires_call_telemetry_for_protocol_repairs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    registry, lane, manifest_path = _frozen_panel_files(tmp_path, monkeypatch)
    model = registry["models"][0]
    artifact = _valid_smoke_artifact(registry, lane, model)
    usage = artifact["candidate"]["summary"]["usage"]
    usage["protocol_repair_attempts"] = 1
    usage["protocol_repairs_succeeded"] = 1
    artifact_path = tmp_path / "repair-without-call-telemetry.json"
    artifact_path.write_text(json.dumps(artifact))

    assert (
        main(
            [
                "record-smoke",
                "--model-id",
                model["id"],
                "--artifact",
                str(artifact_path),
                "--manifest",
                str(manifest_path),
            ]
        )
        == 1
    )
    assert "at least 5 API calls" in capsys.readouterr().err
    assert json.loads(manifest_path.read_text())["entries"] == {}


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("truncated_calls", 1, "cap-induced truncation"),
        ("max_output_tokens_per_call", 3072, "cap-pressure threshold"),
        ("scaffold_fingerprint", "wrong", "different prompt scaffold"),
        ("decision_failure_rate", 0.1, "decision_failure_rate must be zero"),
    ],
)
def test_record_smoke_refuses_invalid_artifact_without_writing_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    field: str,
    value: object,
    message: str,
) -> None:
    registry, lane, manifest_path = _frozen_panel_files(tmp_path, monkeypatch)
    model = registry["models"][0]
    artifact = _valid_smoke_artifact(registry, lane, model)
    if field == "scaffold_fingerprint":
        artifact["run_info"][field] = value
    elif field == "decision_failure_rate":
        artifact["candidate"]["summary"][field] = value
    else:
        artifact["candidate"]["summary"]["usage"][field] = value
    artifact_path = tmp_path / f"{field}.json"
    artifact_path.write_text(json.dumps(artifact))

    assert (
        main(
            [
                "record-smoke",
                "--model-id",
                model["id"],
                "--artifact",
                str(artifact_path),
                "--manifest",
                str(manifest_path),
            ]
        )
        == 1
    )
    assert message in capsys.readouterr().err
    assert json.loads(manifest_path.read_text())["entries"] == {}


@pytest.mark.parametrize("bad_reasoning_tokens", [True, -1])
def test_record_smoke_refuses_invalid_reasoning_token_telemetry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    bad_reasoning_tokens: object,
) -> None:
    registry, lane, manifest_path = _frozen_panel_files(tmp_path, monkeypatch)
    model = next(m for m in registry["models"] if m["reasoning_policy"] == "mandatory-minimum")
    artifact = _valid_smoke_artifact(registry, lane, model)
    artifact["candidate"]["summary"]["usage"]["reasoning_tokens"] = bad_reasoning_tokens
    artifact_path = tmp_path / "bad-reasoning-tokens.json"
    artifact_path.write_text(json.dumps(artifact))

    assert (
        main(
            [
                "record-smoke",
                "--model-id",
                model["id"],
                "--artifact",
                str(artifact_path),
                "--manifest",
                str(manifest_path),
            ]
        )
        == 1
    )
    assert "missing reasoning-token telemetry" in capsys.readouterr().err
    assert json.loads(manifest_path.read_text())["entries"] == {}


def test_artifact_spend_uses_completed_result_telemetry(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "one.json").write_text(json.dumps({"candidate": {"summary": {"usage": {"cost_usd": 0.12}}}}))
    (raw / "two.json").write_text(json.dumps({"candidate": {"summary": {"usage": {"cost_usd": 0.03}}}}))
    assert _artifact_spend_usd(tmp_path) == pytest.approx(0.15)


def test_paid_openrouter_run_requires_explicit_spend_ceiling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _frozen_panel_files(tmp_path, monkeypatch)
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "smoke",
                "--contract",
                BENCHMARK_VERSION,
                "--model-id",
                "openrouter-qwen3.7-plus-alibaba",
                "--run-dir",
                str(tmp_path),
            ]
        )
    assert exc.value.code == 2
    assert "require an explicit --max-spend-usd ceiling" in capsys.readouterr().err


def test_paid_sweep_is_locked_after_policy_is_retired(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["sweep", "--run-dir", str(tmp_path), "--max-spend-usd", "10"])
    assert exc.value.code == 2
    assert "paid sweep is locked" in capsys.readouterr().err


def test_cell_reservation_blocks_launch_before_ceiling_overrun(tmp_path: Path) -> None:
    cell = build_cells("smoke", model_id="openrouter-gpt-5.6-luna-openai", cap=4096)[0]
    reservation = _cell_reservation_usd(cell)
    assert 0 < reservation < 1
    with pytest.raises(SystemExit, match="reservation would exceed"):
        _reserve_cell(tmp_path, cell, measured_spend=0.99, ceiling=1.0)
    assert not (tmp_path / "openrouter-reservations.json").exists()


def test_cell_reservation_covers_repairs_and_cost_contingency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, lane, manifest_path = _frozen_panel_files(tmp_path, monkeypatch)
    manifest_path.write_text(json.dumps(_valid_manifest(registry, lane)))
    cell = build_cells("panel", model_id="openrouter-gpt-5.6-luna-openai")[0]
    pricing = json.loads(Path("config/openrouter_pricing_snapshot.json").read_text())
    assumptions = pricing["planning_assumptions"]
    rates = pricing["models"][cell.model]
    assert cell.seed_count == 9
    decisions = 9 * 5 * 4 * 3
    base = decisions * (assumptions["input_tokens_per_decision"] * rates["prompt"] + cell.cap * rates["completion"])

    assert cell.fixed_options["GM_BENCH_PROTOCOL_REPAIR_ATTEMPTS"] == "1"
    assert _cell_reservation_usd(cell) == pytest.approx(base * 2 * assumptions["cost_contingency_multiplier"], abs=1e-6)


def test_larger_output_cap_scales_only_completion_part_of_reservation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Input spend does not double merely because the output cap doubles."""
    registry, lane, manifest_path = _frozen_panel_files(tmp_path, monkeypatch)
    manifest_path.write_text(json.dumps(_valid_manifest(registry, lane)))
    cell = build_cells("panel", model_id="openrouter-gpt-5.6-luna-openai")[0]
    larger = replace(cell, cap=cell.cap * 2)
    pricing = json.loads(Path("config/openrouter_pricing_snapshot.json").read_text())
    assumptions = pricing["planning_assumptions"]
    rates = pricing["models"][cell.model]
    decisions = 9 * 5 * 4 * 3
    repair_multiplier = 2
    expected_increment = (
        decisions * cell.cap * rates["completion"] * repair_multiplier * assumptions["cost_contingency_multiplier"]
    )

    base_reservation = _cell_reservation_usd(cell)
    larger_reservation = _cell_reservation_usd(larger)
    assert larger_reservation - base_reservation == pytest.approx(expected_increment, abs=1e-6)
    assert larger_reservation != pytest.approx(base_reservation * 2)


def test_call_guard_receives_frozen_rates_and_global_ceiling(tmp_path: Path) -> None:
    cell = build_cells("smoke", model_id="openrouter-gpt-5.6-luna-openai", cap=4096)[0]
    guard = _call_spend_guard_environment(
        cell,
        tmp_path,
        ceiling_usd=100.0,
        measured_spend_floor_usd=12.5,
    )
    prefix = "GM_BENCH_OPENROUTER_SPEND_GUARD_"

    assert guard[f"{prefix}STATE_PATH"] == str(tmp_path / publication_runner.CALL_SPEND_GUARD_STATE)
    assert guard[f"{prefix}CEILING_USD"] == "100.0"
    assert guard[f"{prefix}MEASURED_SPEND_FLOOR_USD"] == "12.5"
    assert float(guard[f"{prefix}PROMPT_RATE_USD"]) > 0
    assert float(guard[f"{prefix}COMPLETION_RATE_USD"]) > 0
    assert guard[f"{prefix}OUTPUT_TOKEN_CAP"] == "4096"


def test_call_guard_rejects_reasoning_without_a_committed_token_allowance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cell = build_cells("smoke", model_id="openrouter-gpt-5.6-luna-openai", cap=4096)[0]
    cell = replace(cell, fixed_options={"OPENROUTER_REASONING_ENABLED": "true"})
    pricing = json.loads(Path("config/sota_v3_pricing_snapshot.json").read_text())
    pricing["planning_assumptions"].pop("expected_internal_reasoning_tokens_per_decision", None)
    monkeypatch.setattr(publication_runner, "_read_json", lambda _path: pricing)

    with pytest.raises(ValueError, match="positive committed"):
        _call_spend_guard_environment(
            cell,
            tmp_path,
            ceiling_usd=100.0,
            measured_spend_floor_usd=0.0,
        )


def test_call_guard_accepts_zero_reasoning_allowance_when_cap_includes_reasoning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The v6 lane bills reasoning inside the output cap, so the full-cap
    completion reservation already prices it and zero extra tokens is honest."""
    cell = build_cells("smoke", model_id="openrouter-gpt-5.6-luna-openai", cap=4096)[0]
    cell = replace(cell, fixed_options={"OPENROUTER_REASONING_ENABLED": "true"})
    pricing = json.loads(Path("config/sota_v3_pricing_snapshot.json").read_text())
    pricing["planning_assumptions"]["expected_internal_reasoning_tokens_per_decision"] = 0
    pricing["planning_assumptions"]["reasoning_tokens_billed_within_output_cap"] = True
    monkeypatch.setattr(publication_runner, "_read_json", lambda _path: pricing)

    guard = _call_spend_guard_environment(
        cell,
        tmp_path,
        ceiling_usd=100.0,
        measured_spend_floor_usd=0.0,
    )
    prefix = "GM_BENCH_OPENROUTER_SPEND_GUARD_"
    assert guard[f"{prefix}OUTPUT_TOKEN_CAP"] == "4096"
    # Anything other than the exact boolean true keeps the strict refusal.
    pricing["planning_assumptions"]["reasoning_tokens_billed_within_output_cap"] = "true"
    with pytest.raises(ValueError, match="positive committed"):
        _call_spend_guard_environment(
            cell,
            tmp_path,
            ceiling_usd=100.0,
            measured_spend_floor_usd=0.0,
        )


def test_cell_reservation_scales_to_future_24_seed_private_panel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, lane, manifest_path = _frozen_panel_files(tmp_path, monkeypatch)
    manifest_path.write_text(json.dumps(_valid_manifest(registry, lane)))
    nine_seed_cell = build_cells("panel", model_id="openrouter-gpt-5.6-luna-openai")[0]
    twenty_four_seed_cell = replace(nine_seed_cell, seed_count=24)

    assert _cell_reservation_usd(twenty_four_seed_cell) == pytest.approx(
        _cell_reservation_usd(nine_seed_cell) * (24 / 9),
        abs=1e-6,
    )


def test_retry_reservation_accounts_for_fresh_full_attempt(tmp_path: Path) -> None:
    cell = build_cells("smoke", model_id="openrouter-gpt-5.6-luna-openai", cap=4096)[0]
    reservation = _cell_reservation_usd(cell)
    path = tmp_path / "openrouter-reservations.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "cells": {
                    f"{cell.experiment_id}--4096": {
                        "experiment_id": cell.experiment_id,
                        "model": cell.model,
                        "output_token_cap": 4096,
                        "reserved_usd": reservation,
                        "attempts": 1,
                    }
                },
            }
        )
    )
    with pytest.raises(SystemExit, match="retry reservation would exceed"):
        _reserve_cell(tmp_path, cell, measured_spend=0.9, ceiling=0.9 + reservation / 2)

    committed = _reserve_cell(tmp_path, cell, measured_spend=0.1, ceiling=reservation * 2 + 0.1)
    stored = json.loads(path.read_text())["cells"][f"{cell.experiment_id}--4096"]
    assert committed == pytest.approx(reservation * 2 + 0.1)
    assert stored["reserved_usd"] == pytest.approx(reservation * 2)
    assert stored["status"] == "active"
    assert stored["attempts"] == 2


def test_retry_reservation_enforces_frozen_attempt_limit(tmp_path: Path) -> None:
    cell = build_cells("smoke", model_id="openrouter-gpt-5.6-luna-openai", cap=4096)[0]
    reservation = _cell_reservation_usd(cell)
    path = tmp_path / "openrouter-reservations.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "cells": {
                    f"{cell.experiment_id}--4096": {
                        "experiment_id": cell.experiment_id,
                        "model": cell.model,
                        "output_token_cap": 4096,
                        "reserved_usd": reservation * 2,
                        "attempts": 2,
                        "status": "active",
                    }
                },
            }
        )
    )

    with pytest.raises(SystemExit, match="attempt limit reached"):
        _reserve_cell(tmp_path, cell, measured_spend=0.1, ceiling=100.0)
    assert json.loads(path.read_text())["cells"][f"{cell.experiment_id}--4096"]["attempts"] == 2


def test_second_failed_attempt_becomes_terminal_exclusion_and_releases_reservation(tmp_path: Path) -> None:
    cell = build_cells("smoke", model_id="openrouter-gpt-5.6-luna-openai", cap=4096)[0]

    _reserve_cell(tmp_path, cell, measured_spend=0.0, ceiling=100.0)
    _record_failed_cell_reservation(tmp_path, cell, measured_spend=0.01, error="network failure one")
    _reserve_cell(tmp_path, cell, measured_spend=0.01, ceiling=100.0)
    _record_failed_cell_reservation(tmp_path, cell, measured_spend=0.02, error="network failure two")

    stored = json.loads((tmp_path / "openrouter-reservations.json").read_text())["cells"][f"{cell.experiment_id}--4096"]
    assert stored["attempts"] == 2
    assert stored["status"] == "excluded"
    assert stored["reserved_usd"] == 0
    assert [attempt["status"] for attempt in stored["attempt_history"]] == ["failed", "failed"]
    assert stored["last_failure"] == "network failure two"


def test_completed_ineligible_cell_releases_reservation_without_becoming_retryable(tmp_path: Path) -> None:
    cell = build_cells("smoke", model_id="openrouter-gpt-5.6-luna-openai", cap=4096)[0]
    _reserve_cell(tmp_path, cell, measured_spend=0.0, ceiling=100.0)

    _record_ineligible_cell_reservation(
        tmp_path,
        cell,
        measured_spend=0.02,
        error="candidate usage must cover every decision point",
    )

    stored = json.loads((tmp_path / "openrouter-reservations.json").read_text())["cells"][f"{cell.experiment_id}--4096"]
    assert stored["status"] == "ineligible"
    assert stored["reserved_usd"] == 0
    assert stored["attempt_history"][-1]["status"] == "ineligible"
    assert stored["ineligibility_reason"] == "candidate usage must cover every decision point"


def test_completed_smoke_model_behavior_is_ineligible_without_rerun(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, lane, _manifest_path = _frozen_panel_files(tmp_path, monkeypatch)
    model = registry["models"][0]
    cell = build_cells("smoke", model_id=model["id"])[0]
    artifact = _valid_smoke_artifact(registry, lane, model)
    artifact["candidate"]["episodes"][0]["failed_decisions"] = 1
    artifact["candidate"]["summary"]["failed_decisions"] = 1
    artifact["candidate"]["summary"]["decision_failure_rate"] = 0.25
    raw = tmp_path / "raw" / f"{cell.experiment_id}--{cell.cap_label}.json"
    raw.parent.mkdir(parents=True)
    raw.write_text(json.dumps(artifact))

    assert publication_runner._completed_smoke_model_behavior_issues(cell, tmp_path) == [
        "artifact candidate episode contains failed decisions",
        "artifact candidate summary failed_decisions must be zero",
        "artifact decision_failure_rate must be zero",
    ]

    artifact["candidate"]["summary"]["usage"]["cost_decisions"] = 3
    raw.write_text(json.dumps(artifact))
    assert publication_runner._completed_smoke_model_behavior_issues(cell, tmp_path) == []


@pytest.mark.parametrize("status", ["excluded", "ineligible"])
def test_terminal_smoke_is_skipped_before_child_or_new_reservation(
    status: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, _lane, _manifest_path = _frozen_panel_files(tmp_path, monkeypatch)
    cell = build_cells("smoke", model_id=registry["models"][0]["id"])[0]
    stem = f"{cell.experiment_id}--{cell.cap_label}"
    (tmp_path / "openrouter-reservations.json").write_text(
        json.dumps({"schema_version": 1, "cells": {stem: {"status": status, "attempts": 2}}})
    )
    monkeypatch.setattr(publication_runner, "_validate_openrouter_endpoint", lambda *_args: pytest.fail("endpoint"))
    monkeypatch.setattr(publication_runner.subprocess, "run", lambda *_args, **_kwargs: pytest.fail("child"))

    assert (
        _runner_main(
            [
                "smoke",
                "--contract",
                BENCHMARK_VERSION,
                "--model-id",
                cell.experiment_id,
                "--run-dir",
                str(tmp_path),
                "--max-spend-usd",
                "100",
            ],
            _paid_run_lock_held=True,
        )
        == 0
    )

    stored = json.loads((tmp_path / "openrouter-reservations.json").read_text())["cells"][stem]
    assert stored == {"status": status, "attempts": 2}


def test_successful_cell_settlement_releases_reservation_for_next_cell(tmp_path: Path) -> None:
    first = build_cells("smoke", model_id="openrouter-gpt-5.6-luna-openai")[0]
    second = build_cells("smoke", model_id="openrouter-claude-sonnet-5-bedrock")[0]
    first_reservation = _cell_reservation_usd(first)
    second_reservation = _cell_reservation_usd(second)

    _reserve_cell(tmp_path, first, measured_spend=0.0, ceiling=first_reservation + 0.01)
    _settle_cell_reservation(tmp_path, first, measured_spend=0.02)
    committed = _reserve_cell(
        tmp_path,
        second,
        measured_spend=0.02,
        ceiling=0.02 + second_reservation + 0.01,
    )

    cells = json.loads((tmp_path / "openrouter-reservations.json").read_text())["cells"]
    assert cells[f"{first.experiment_id}--4096"]["reserved_usd"] == 0
    assert cells[f"{first.experiment_id}--4096"]["status"] == "settled"
    assert cells[f"{second.experiment_id}--4096"]["status"] == "active"
    assert committed == pytest.approx(0.02 + second_reservation)


def test_unsettled_failed_attempt_remains_part_of_next_reservation_guard(tmp_path: Path) -> None:
    first = build_cells("smoke", model_id="openrouter-gpt-5.6-luna-openai")[0]
    second = build_cells("smoke", model_id="openrouter-claude-sonnet-5-bedrock")[0]
    first_reservation = _cell_reservation_usd(first)
    second_reservation = _cell_reservation_usd(second)
    _reserve_cell(tmp_path, first, measured_spend=0.0, ceiling=first_reservation + 0.01)

    with pytest.raises(SystemExit, match="reservation would exceed"):
        _reserve_cell(
            tmp_path,
            second,
            measured_spend=0.02,
            ceiling=0.02 + second_reservation + first_reservation / 2,
        )


def test_panel_artifact_gate_requires_complete_cost_and_registered_route_telemetry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, lane, manifest_path = _frozen_panel_files(tmp_path, monkeypatch)
    manifest_path.write_text(json.dumps(_valid_manifest(registry, lane)))
    cell = build_cells("panel", model_id="openrouter-grok-4.5-xai")[0]
    artifact = {
        "run_info": {
            "provider": cell.provider,
            "model": cell.model,
            "profile": cell.profile,
            "preset": cell.preset,
            "provider_options": {
                **cell.fixed_options,
                "GM_BENCH_OUTPUT_BUDGET_CELL": cell.cap_label,
            },
        },
        "candidate": {
            "summary": {
                "decisions": 480,
                "usage": {
                    "decisions_with_usage": 480,
                    "cost_decisions": 480,
                    "upstream_providers": [cell.upstream_provider],
                },
            }
        },
    }
    monkeypatch.setattr(
        publication_runner,
        "validate_leaderboard_payload",
        lambda *args, **kwargs: SimpleNamespace(errors=[]),
    )

    assert _panel_artifact_issues(cell, artifact) == []
    artifact["candidate"]["summary"]["usage"]["cost_decisions"] = 474
    assert "candidate cost telemetry must cover every decision point" in _panel_artifact_issues(cell, artifact)
    artifact["candidate"]["summary"]["usage"]["cost_decisions"] = 480
    artifact["candidate"]["summary"]["usage"]["upstream_providers"] = ["Other"]
    assert "observed upstream provider does not match the registered route" in _panel_artifact_issues(cell, artifact)


def test_existing_ineligible_panel_artifact_is_not_reused_or_overwritten(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, lane, manifest_path = _frozen_panel_files(tmp_path, monkeypatch)
    manifest_path.write_text(json.dumps(_valid_manifest(registry, lane)))
    cell = build_cells("panel", model_id="openrouter-grok-4.5-xai")[0]
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    artifact_path = raw_dir / f"{cell.experiment_id}--{cell.cap_label}.json"
    artifact_path.write_text(json.dumps({"candidate": {"summary": {"decisions": 480, "usage": {}}}}))
    monkeypatch.setattr(
        publication_runner,
        "_panel_artifact_issues",
        lambda *args, **kwargs: ["candidate usage must cover every decision point"],
    )

    existing, issues = publication_runner._existing_panel_artifact(cell, tmp_path)
    assert existing == artifact_path
    assert issues == ["candidate usage must cover every decision point"]


def test_panel_run_records_existing_ineligible_artifact_without_provider_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, lane, manifest_path = _frozen_panel_files(tmp_path, monkeypatch)
    manifest_path.write_text(json.dumps(_valid_manifest(registry, lane)))
    cell = build_cells("panel", model_id=registry["models"][0]["id"])[0]
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / f"{cell.experiment_id}--{cell.cap_label}.json").write_text(json.dumps({}))
    monkeypatch.setattr(
        publication_runner,
        "_panel_artifact_issues",
        lambda *args, **kwargs: ["candidate usage must cover every decision point"],
    )
    monkeypatch.setattr(
        publication_runner.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("an existing ineligible artifact must not be rerun"),
    )

    with pytest.raises(SystemExit, match="existing panel artifact failed the publication gate"):
        main(
            [
                "panel",
                "--model-id",
                cell.experiment_id,
                "--run-dir",
                str(tmp_path),
                "--max-spend-usd",
                "95",
            ]
        )

    run_state = json.loads((tmp_path / "run-state.json").read_text())
    assert run_state["cell_outcomes"][cell.experiment_id]["status"] == "ineligible"


def test_panel_run_rejects_ineligible_artifact_before_settlement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, lane, manifest_path = _frozen_panel_files(tmp_path, monkeypatch)
    manifest_path.write_text(json.dumps(_valid_manifest(registry, lane)))
    model = registry["models"][0]
    cell = build_cells("panel", model_id=model["id"])[0]
    monkeypatch.setattr(publication_runner, "_validate_openrouter_endpoint", lambda _cell, _env: None)
    monkeypatch.setattr(publication_runner, "_openrouter_usage_usd", lambda _env: 0.0)
    monkeypatch.setattr(
        publication_runner,
        "_panel_artifact_issues",
        lambda *args, **kwargs: ["candidate usage must cover every decision point"],
    )

    def complete_child(*args: object, **kwargs: object) -> subprocess.CompletedProcess:
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir(exist_ok=True)
        (raw_dir / f"{cell.experiment_id}--{cell.cap_label}.json").write_text(json.dumps({}))
        return subprocess.CompletedProcess(args=args, returncode=0)

    monkeypatch.setattr(publication_runner.subprocess, "run", complete_child)

    with pytest.raises(SystemExit, match="failed the publication gate"):
        main(
            [
                "panel",
                "--model-id",
                cell.experiment_id,
                "--run-dir",
                str(tmp_path),
                "--max-spend-usd",
                "95",
            ]
        )

    reservation = json.loads((tmp_path / "openrouter-reservations.json").read_text())["cells"][
        f"{cell.experiment_id}--{cell.cap_label}"
    ]
    assert reservation["status"] == "ineligible"
    assert reservation["reserved_usd"] == 0
    run_state = json.loads((tmp_path / "run-state.json").read_text())
    assert run_state["cell_outcomes"][cell.experiment_id]["status"] == "ineligible"


def test_panel_preflight_does_not_require_a_completed_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, lane, manifest_path = _frozen_panel_files(tmp_path, monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-preflight-key")
    manifest_path.write_text(json.dumps(_valid_manifest(registry, lane)))
    cell = build_cells("panel", model_id=registry["models"][0]["id"])[0]
    monkeypatch.setattr(publication_runner, "_validate_openrouter_endpoint", lambda _cell, _env: None)
    monkeypatch.setattr(
        publication_runner.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args=args, returncode=0),
    )

    assert (
        main(
            [
                "panel",
                "--model-id",
                cell.experiment_id,
                "--run-dir",
                str(tmp_path),
                "--preflight-only",
            ]
        )
        == 0
    )
    assert not (tmp_path / "run-state.json").exists()


def test_zero_call_route_preflight_has_separate_authorization_and_never_launches_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-route-preflight-key")
    registry, lane, _manifest_path = _frozen_panel_files(tmp_path, monkeypatch)
    registry["selection_status"] = "route-preflight-ready"
    registry["spend_authorized"] = False
    lane["preregistration_status"] = "provisional-blocked"
    lane["route_preflight_authorized"] = True
    lane["spend_authorized"] = False
    lane["smoke_execution_authorized"] = False
    lane["panel_execution_authorized"] = False
    publication_runner.PANEL_CONFIG.write_text(json.dumps(registry))
    publication_runner.LANE_CONFIG.write_text(json.dumps(lane))
    protocol = json.loads(publication_runner.PROTOCOL_CONFIG.read_text())
    protocol["status"] = "provisional-blocked"
    protocol["statistical_analysis_plan"]["status"] = "unresolved-pre-data"
    protocol["budget_policy"]["spend_authorized"] = False
    publication_runner.PROTOCOL_CONFIG.write_text(json.dumps(protocol))
    pricing = json.loads(publication_runner.PRICING_CONFIG.read_text())
    pricing["status"] = "not-started"
    pricing["spend_authorized"] = False
    publication_runner.PRICING_CONFIG.write_text(json.dumps(pricing))
    endpoint_checks: list[str] = []
    child_calls: list[str] = []
    monkeypatch.setattr(
        publication_runner,
        "_validate_openrouter_endpoint",
        lambda cell, _env: endpoint_checks.append(cell.experiment_id),
    )
    monkeypatch.setattr(
        publication_runner.subprocess,
        "run",
        lambda *_args, **_kwargs: child_calls.append("child"),
    )

    assert (
        main(
            [
                "route-preflight",
                "--model-id",
                registry["models"][0]["id"],
                "--run-dir",
                str(tmp_path),
            ]
        )
        == 0
    )
    assert endpoint_checks == [registry["models"][0]["id"]]
    assert child_calls == []
    assert not (tmp_path / "run-state.json").exists()
    assert not (tmp_path / "raw").exists()
    assert not (tmp_path / "checkpoints").exists()


def test_route_preflight_checks_every_route_before_failing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A bad route must not hide the routes queued behind it.

    Exiting on the first failure understates how much is broken: the operator
    sees one dead route, fixes it, and only then learns about the next one.
    The zero-call phase is free, so it has no reason to stop early -- it must
    probe every route and report the complete set in one pass.  The paid
    phases keep failing fast, which is asserted separately below.
    """
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-route-preflight-key")
    registry, lane, _manifest_path = _frozen_panel_files(tmp_path, monkeypatch)
    registry["selection_status"] = "frozen"
    lane["preregistration_status"] = "frozen"
    lane["route_preflight_authorized"] = True
    publication_runner.PANEL_CONFIG.write_text(json.dumps(registry))
    publication_runner.LANE_CONFIG.write_text(json.dumps(lane))

    model_ids = [model["id"] for model in registry["models"]]
    assert len(model_ids) >= 3, "this test needs a route queued behind both failures"
    doomed = {model_ids[0], model_ids[2]}
    checked: list[str] = []
    child_calls: list[str] = []

    def fake_validate(cell, _env):
        checked.append(cell.experiment_id)
        if cell.experiment_id in doomed:
            raise RuntimeError("no healthy OpenRouter endpoint matches")

    monkeypatch.setattr(publication_runner, "_validate_openrouter_endpoint", fake_validate)
    monkeypatch.setattr(
        publication_runner.subprocess,
        "run",
        lambda *_args, **_kwargs: child_calls.append("child"),
    )

    with pytest.raises(SystemExit) as exc_info:
        main(["route-preflight", "--contract", BENCHMARK_VERSION, "--run-dir", str(tmp_path)])

    message = str(exc_info.value.code)
    # Every route was probed, including the ones queued behind both failures.
    assert checked == model_ids
    assert f"failed for {len(doomed)} of {len(model_ids)} routes" in message
    for model_id in doomed:
        assert model_id in message
    captured = capsys.readouterr()
    assert captured.err.count("OpenRouter endpoint preflight failed") == len(doomed)
    assert "OpenRouter endpoint preflight failed" not in captured.out
    # Still zero-call and still stateless, exactly as on the passing path.
    assert child_calls == []
    assert not (tmp_path / "run-state.json").exists()
    assert not (tmp_path / "raw").exists()


def test_paid_phases_still_abort_on_the_first_bad_route(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Collecting failures is a zero-call affordance, not a general one.

    A phase that spends money must stop the instant a route is wrong, so the
    later cells are never probed at all.
    """
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-smoke-key")
    registry, _lane, _manifest_path = _frozen_panel_files(tmp_path, monkeypatch)
    model_ids = [model["id"] for model in registry["models"]]
    checked: list[str] = []

    def fake_validate(cell, _env):
        checked.append(cell.experiment_id)
        raise RuntimeError("no healthy OpenRouter endpoint matches")

    monkeypatch.setattr(publication_runner, "_validate_openrouter_endpoint", fake_validate)

    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "smoke",
                "--contract",
                BENCHMARK_VERSION,
                "--model-id",
                model_ids[0],
                "--run-dir",
                str(tmp_path),
                "--max-spend-usd",
                "1.00",
            ]
        )

    assert checked == model_ids[:1], "a paid phase kept probing after a bad route"
    assert model_ids[0] in str(exc_info.value.code)


def test_current_strict_route_preflight_requires_bearer_credential_before_endpoint_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, lane, _manifest_path = _frozen_panel_files(tmp_path, monkeypatch)
    registry["selection_status"] = "frozen"
    lane["preregistration_status"] = "frozen"
    lane["route_preflight_authorized"] = True
    publication_runner.PANEL_CONFIG.write_text(json.dumps(registry))
    publication_runner.LANE_CONFIG.write_text(json.dumps(lane))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(publication_runner, "load_environment_files", lambda _root: [])
    endpoint_checks: list[str] = []
    child_calls: list[str] = []
    monkeypatch.setattr(
        publication_runner,
        "_validate_openrouter_endpoint",
        lambda cell, _env: endpoint_checks.append(cell.experiment_id),
    )
    monkeypatch.setattr(
        publication_runner.subprocess,
        "run",
        lambda *_args, **_kwargs: child_calls.append("child"),
    )

    with pytest.raises(SystemExit, match="requires OPENROUTER_API_KEY"):
        main(
            [
                "route-preflight",
                "--model-id",
                registry["models"][0]["id"],
                "--run-dir",
                str(tmp_path),
            ]
        )

    assert endpoint_checks == []
    assert child_calls == []
    assert not (tmp_path / "run-state.json").exists()


def test_current_strict_smoke_preflight_requires_bearer_credential_before_endpoint_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, lane, _manifest_path = _frozen_panel_files(tmp_path, monkeypatch)
    publication_runner.PANEL_CONFIG.write_text(json.dumps(registry))
    publication_runner.LANE_CONFIG.write_text(json.dumps(lane))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(publication_runner, "load_environment_files", lambda _root: [])
    endpoint_checks: list[str] = []
    monkeypatch.setattr(
        publication_runner,
        "_validate_openrouter_endpoint",
        lambda cell, _env: endpoint_checks.append(cell.experiment_id),
    )

    with pytest.raises(SystemExit, match="requires OPENROUTER_API_KEY"):
        main(
            [
                "smoke",
                "--preflight-only",
                "--model-id",
                registry["models"][0]["id"],
                "--run-dir",
                str(tmp_path),
            ]
        )

    assert endpoint_checks == []


def test_authenticated_endpoint_metadata_request_sends_bearer_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = []
    monkeypatch.setenv("OPENROUTER_API_KEY", "ambient-key-that-must-not-be-used")

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return io.BytesIO(b'{"data":{"endpoints":[]}}')

    monkeypatch.setattr(publication_runner.urllib.request, "urlopen", fake_urlopen)
    publication_runner._openrouter_endpoints(
        "demo/authenticated-route",
        {"OPENROUTER_API_KEY": "test-authenticated-metadata-key"},
    )

    assert len(requests) == 1
    request, timeout = requests[0]
    assert request.get_header("Authorization") == "Bearer test-authenticated-metadata-key"
    assert timeout == 30


def test_frozen_private_panel_rejects_inherited_seed_drift_before_cells(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, _lane, manifest_path = _frozen_panel_files(tmp_path, monkeypatch)
    manifest_path.write_text(json.dumps(_valid_manifest(registry, _lane)))
    monkeypatch.setenv("GM_BENCH_PRIVATE_SEEDS", "101,102,103")
    endpoint_checks: list[str] = []
    child_calls: list[str] = []
    monkeypatch.setattr(
        publication_runner,
        "_validate_openrouter_endpoint",
        lambda cell, _env: endpoint_checks.append(cell.experiment_id),
    )
    monkeypatch.setattr(
        publication_runner.subprocess,
        "run",
        lambda *_args, **_kwargs: child_calls.append("child"),
    )

    with pytest.raises(SystemExit) as exc_info:
        main(["panel", "--model-id", registry["models"][0]["id"], "--dry-run"])

    assert exc_info.value.code == 2
    assert endpoint_checks == []
    assert child_calls == []


def test_frozen_private_panel_rejects_duplicate_seeds_before_cells(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, lane, manifest_path = _frozen_panel_files(tmp_path, monkeypatch)
    duplicate_seeds = [101, 101, 102, 103, 104, 105, 106, 107, 108]
    lane["seed_panel"] = {
        "status": "frozen",
        "name": "private-env",
        "count": len(duplicate_seeds),
        "sha256": publication_runner.seed_panel_hash(duplicate_seeds),
        "hiding_commitment_sha256": "c" * 64,
    }
    publication_runner.LANE_CONFIG.write_text(json.dumps(lane))
    manifest_path.write_text(json.dumps(_valid_manifest(registry, lane)))
    monkeypatch.setenv("GM_BENCH_PRIVATE_SEEDS", ",".join(str(seed) for seed in duplicate_seeds))
    endpoint_checks: list[str] = []
    child_calls: list[str] = []
    monkeypatch.setattr(
        publication_runner,
        "_validate_openrouter_endpoint",
        lambda cell, _env: endpoint_checks.append(cell.experiment_id),
    )
    monkeypatch.setattr(
        publication_runner.subprocess,
        "run",
        lambda *_args, **_kwargs: child_calls.append("child"),
    )

    with pytest.raises(SystemExit) as exc_info:
        main(["panel", "--model-id", registry["models"][0]["id"], "--dry-run"])

    assert exc_info.value.code == 2
    assert endpoint_checks == []
    assert child_calls == []


def test_frozen_public_panel_rejects_private_seed_env_before_cells(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, lane, manifest_path = _frozen_panel_files(tmp_path, monkeypatch)
    public_seeds = publication_runner.PRESETS["leaderboard"]["seeds"]
    lane["seed_panel"] = {
        "status": "frozen",
        "name": "public-leaderboard",
        "count": len(public_seeds),
        "sha256": hashlib.sha256(",".join(str(seed) for seed in public_seeds).encode()).hexdigest(),
    }
    # Reduce the synthetic family so the eight-seed exact test is feasible;
    # this test isolates environment drift rather than the statistics gate.
    registry["models"] = registry["models"][:1]
    registry["required_smokes"] = [registry["models"][0]["id"]]
    lane["minimum_headline_models"] = 1
    publication_runner.PANEL_CONFIG.write_text(json.dumps(registry))
    publication_runner.LANE_CONFIG.write_text(json.dumps(lane))
    protocol = json.loads(publication_runner.PROTOCOL_CONFIG.read_text())
    protocol["statistical_analysis_plan"]["holm_family_size"] = 1
    publication_runner.PROTOCOL_CONFIG.write_text(json.dumps(protocol))
    manifest_path.write_text(json.dumps(_valid_manifest(registry, lane)))
    monkeypatch.setenv("GM_BENCH_PRIVATE_SEEDS", "101,102,103,104,105,106,107,108,109")

    with pytest.raises(SystemExit) as exc_info:
        main(["panel", "--model-id", registry["models"][0]["id"], "--dry-run"])

    assert exc_info.value.code == 2


def test_endpoint_preflight_requires_frozen_healthy_capable_route() -> None:
    cell = build_cells("smoke", model_id="openrouter-qwen3.7-plus-alibaba", cap=4096)[0]
    valid = {
        "data": {
            "endpoints": [
                {
                    "provider_name": "Alibaba",
                    "tag": "alibaba",
                    "name": cell.endpoint_name,
                    "status": 0,
                    "max_completion_tokens": 65536,
                    "supported_parameters": ["max_tokens", "response_format", "reasoning"],
                    "uptime_last_30m": 99.8,
                    "uptime_last_1d": 99.75,
                }
            ]
        }
    }
    assert _endpoint_issues(cell, valid) == []
    valid["data"]["endpoints"][0]["tag"] = "alibaba/other-tier"
    assert "no healthy OpenRouter endpoint" in _endpoint_issues(cell, valid)[0]
    valid["data"]["endpoints"][0]["tag"] = "alibaba"
    valid["data"]["endpoints"][0]["name"] = "Alibaba | replaced-snapshot"
    assert "no healthy OpenRouter endpoint" in _endpoint_issues(cell, valid)[0]
    valid["data"]["endpoints"][0]["name"] = cell.endpoint_name
    valid["data"]["endpoints"][0]["supported_parameters"] = ["max_tokens", "response_format"]
    assert "cannot honor required parameters" in _endpoint_issues(cell, valid)[0]
    valid["data"]["endpoints"][0]["supported_parameters"] = ["max_tokens", "response_format", "reasoning"]
    valid["data"]["endpoints"][0].pop("max_completion_tokens")
    assert "cannot honor required parameters" in _endpoint_issues(cell, valid)[0]
    valid["data"]["endpoints"][0]["max_completion_tokens"] = "65536"
    assert "cannot honor required parameters" in _endpoint_issues(cell, valid)[0]


def test_endpoint_preflight_allows_explicit_null_cap_deferral_only_until_strict_smoke() -> None:
    cell = build_cells("smoke", model_id="openrouter-qwen3.7-plus-alibaba", cap=4096)[0]
    payload = {"data": {"endpoints": [_healthy_endpoint(cell)]}}
    payload["data"]["endpoints"][0]["max_completion_tokens"] = None

    assert "cannot honor required parameters" in _endpoint_issues(cell, payload)[0]

    deferred = replace(
        cell,
        output_cap_verification=dict(PENDING_STRICT_SMOKE_CAP_VERIFICATION),
    )
    assert _endpoint_issues(deferred, payload) == []

    payload["data"]["endpoints"][0]["supported_parameters"].remove("max_tokens")
    assert "cannot honor required parameters" in _endpoint_issues(deferred, payload)[0]

    payload["data"]["endpoints"][0]["supported_parameters"].append("max_tokens")
    payload["data"]["endpoints"][0]["max_completion_tokens"] = 2048
    assert "cannot honor required parameters" in _endpoint_issues(deferred, payload)[0]


def _healthy_endpoint(cell) -> dict:
    return {
        "provider_name": "Alibaba",
        "tag": "alibaba",
        "name": cell.endpoint_name,
        "status": 0,
        "max_completion_tokens": 65536,
        "supported_parameters": ["max_tokens", "response_format", "reasoning"],
        "uptime_last_30m": 99.8,
        "uptime_last_1d": 99.75,
    }


def test_non_finite_spend_limits_are_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--max-spend-usd nan` must not read as a ceiling.

    NaN defeats every downstream guard at once and silently: `nan <= 0`,
    `nan > ceiling`, and `spent >= nan` are all False, so a NaN limit satisfies
    "the operator passed a ceiling" while bounding nothing at all -- an
    unbounded paid run that looks fully authorized. Infinity is the same hole
    wherever no ceiling is configured.
    """
    _frozen_panel_files(tmp_path, monkeypatch)
    checked: list[str] = []
    monkeypatch.setattr(
        publication_runner,
        "_validate_openrouter_endpoint",
        lambda cell, _env: checked.append(cell.experiment_id),
    )

    for literal in ("nan", "inf", "-inf", "NaN", "Infinity"):
        with pytest.raises(SystemExit) as exc_info:
            main(["smoke", "--contract", "sota-v3", "--run-dir", str(tmp_path), "--max-spend-usd", literal])
        assert exc_info.value.code == 2, literal
    assert checked == [], "a non-finite spend limit reached the endpoint probe"

    nonfinite = tmp_path / "nonfinite-protocol.json"
    nonfinite.write_text(json.dumps({"budget_policy": {"operator_ceiling_usd": float("inf")}}))
    monkeypatch.setitem(
        publication_runner.CONTRACT_CONFIGS,
        "sota-nonfinite-ceiling",
        (nonfinite,) * 5,
    )
    with pytest.raises(ValueError, match="positive finite number"):
        publication_runner._enforce_operator_ceiling(1.0, "sota-nonfinite-ceiling")


def test_pricing_drift_fails_closed_when_a_rate_cannot_be_verified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ "Could not verify the price" is not "the price is unchanged".

    Only one of those is safe to spend against, so every unverifiable case
    blocks rather than passing quietly.
    """
    cell = build_cells("smoke", model_id="openrouter-qwen3.7-plus-alibaba", cap=4096)[0]
    committed = json.loads(publication_runner.PRICING_CONFIG.read_text())["models"][cell.model]

    def payload(pricing: dict, **overrides) -> dict:
        endpoint = {
            "provider_name": cell.upstream_provider,
            "tag": cell.endpoint_tag,
            "name": cell.endpoint_name,
            "pricing": pricing,
        }
        endpoint.update(overrides)
        return {"data": {"endpoints": [endpoint]}}

    good = {"prompt": str(committed["prompt"]), "completion": str(committed["completion"])}
    assert publication_runner._pricing_drift_issues(cell, payload(good)) == []

    for pricing, expected in (
        ({"completion": good["completion"]}, "unreadable"),
        ({**good, "prompt": "not-a-number"}, "unreadable"),
        ({**good, "prompt": "nan"}, "not a usable number"),
        ({**good, "prompt": "-1e-07"}, "not a usable number"),
    ):
        issues = publication_runner._pricing_drift_issues(cell, payload(pricing))
        assert issues and expected in issues[0], (pricing, issues)

    # The pinned identity is provider + tag + name, matching the preflight.
    # A same-tag endpoint from another provider is not this cell's price.
    issues = publication_runner._pricing_drift_issues(cell, payload(good, provider_name="Somebody Else"))
    assert issues and "pinned route identity" in issues[0]

    # A model absent from the snapshot cannot be price-checked at all.
    snapshot = json.loads(publication_runner.PRICING_CONFIG.read_text())
    del snapshot["models"][cell.model]
    stripped = tmp_path / "pricing.json"
    stripped.write_text(json.dumps(snapshot))
    monkeypatch.setattr(publication_runner, "PRICING_CONFIG", stripped)
    issues = publication_runner._pricing_drift_issues(cell, payload(good))
    assert issues and "no rates for" in issues[0]


def test_pricing_drift_fails_upward_and_only_reports_downward(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rate that rose invalidates the reservation; a rate that fell does not.

    The committed snapshot is what the budget was computed from, so an
    increase makes the plan wrong in the direction that costs money. A
    decrease only means coming in under reserve -- the GLM Novita route picked
    up a 55.1% discount that nobody noticed for two weeks because nothing
    compared the snapshot to reality.
    """
    cell = build_cells("smoke", model_id="openrouter-qwen3.7-plus-alibaba", cap=4096)[0]
    committed = json.loads(publication_runner.PRICING_CONFIG.read_text())["models"][cell.model]

    def payload(prompt: float, completion: float) -> dict:
        return {
            "data": {
                "endpoints": [
                    {
                        "provider_name": cell.upstream_provider,
                        "tag": cell.endpoint_tag,
                        "name": cell.endpoint_name,
                        "pricing": {"prompt": str(prompt), "completion": str(completion)},
                    }
                ]
            }
        }

    unchanged = payload(committed["prompt"], committed["completion"])
    assert publication_runner._pricing_drift_issues(cell, unchanged) == []

    risen = payload(committed["prompt"] * 2, committed["completion"])
    issues = publication_runner._pricing_drift_issues(cell, risen)
    assert issues and "exceeds the committed snapshot rate" in issues[0]

    capsys.readouterr()
    fallen = payload(committed["prompt"] / 2, committed["completion"] / 2)
    assert publication_runner._pricing_drift_issues(cell, fallen) == [], "a discount must not block a run"
    out = capsys.readouterr().out
    assert "fell from" in out and "under its reservation" in out

    # Another provider's rate is not this cell's rate, so it must not be read
    # as one -- but nor may the absence of the pinned route pass as "unchanged".
    # Both are "the price could not be verified", which now blocks.
    other = payload(committed["prompt"] * 10, committed["completion"])
    other["data"]["endpoints"][0]["tag"] = "someone-else/fp8"
    issues = publication_runner._pricing_drift_issues(cell, other)
    assert issues and "pinned route identity" in issues[0]
    assert "exceeds the committed snapshot rate" not in issues[0], "priced against the wrong route"


def test_the_suite_cannot_inherit_a_live_provider_credential() -> None:
    """Pin the guard that stops a test from quietly billing a real account.

    The runner loads the gitignored `.env.local` itself, so before this guard
    existed any test driving `main()` through a paid phase without stubbing
    the child process ran the real benchmark against real routes. On
    2026-08-04 a test written to assert a spend ceiling *blocks* a run instead
    spent $0.44 across 38 live calls, and passed no judgement on it -- the run
    simply succeeded.
    """
    assert os.environ.get("OPENROUTER_API_KEY") is None
    assert publication_runner.load_environment_files(Path(".")) == []


def test_operator_ceiling_rejects_a_run_that_could_outspend_the_committed_cap() -> None:
    """The committed ceiling has to bind, or it is a comment.

    `budget_policy.operator_ceiling_usd` sat in the config unread, so the only
    thing between a mistyped `--max-spend-usd` and an unbounded run was the
    operator retyping the right number from memory.
    """
    ceiling = json.loads(Path("config/sota_v3_publication_protocol.json").read_text())
    ceiling = ceiling["budget_policy"]["operator_ceiling_usd"]
    assert ceiling == 100.00

    publication_runner._enforce_operator_ceiling(ceiling, "sota-v3")
    publication_runner._enforce_operator_ceiling(ceiling - 0.01, "sota-v3")

    with pytest.raises(ValueError, match="exceeds the committed operator ceiling"):
        publication_runner._enforce_operator_ceiling(ceiling + 0.01, "sota-v3")
    with pytest.raises(ValueError, match=r"\$1200\.00"):
        publication_runner._enforce_operator_ceiling(1200.00, "sota-v3")


def test_spend_reconciliation_charges_the_full_unknown_call_reservation(tmp_path: Path) -> None:
    (tmp_path / "openrouter-budget.json").write_text(json.dumps({"starting_total_usage_usd": 10.0}))
    state_path = tmp_path / publication_runner.CALL_SPEND_GUARD_STATE
    state_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "ceiling_usd": 100.0,
                "reported_spend_usd": 0.001,
                "active_call_reservation_usd": 0.02,
                "blocked_reason": "missing cost",
                "telemetry_error": "lookup exhausted",
            }
        )
    )

    evidence = _reconcile_spend_guard(tmp_path, observed_total_usage_usd=10.0)
    state = json.loads(state_path.read_text())

    assert evidence["method"] == "charge-full-conservative-call-reservation"
    assert evidence["observed_account_delta_usd"] == 0.0
    assert evidence["reconciled_reported_spend_usd"] == pytest.approx(0.021)
    assert state["reported_spend_usd"] == pytest.approx(0.021)
    assert state["active_call_reservation_usd"] == 0
    assert "blocked_reason" not in state
    assert (tmp_path / publication_runner.SPEND_RECONCILIATION).is_file()


def test_repeated_spend_reconciliation_preserves_and_hash_links_prior_evidence(tmp_path: Path) -> None:
    (tmp_path / "openrouter-budget.json").write_text(json.dumps({"starting_total_usage_usd": 10.0}))
    state_path = tmp_path / publication_runner.CALL_SPEND_GUARD_STATE
    state_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "ceiling_usd": 100.0,
                "reported_spend_usd": 0.001,
                "active_call_reservation_usd": 0.02,
                "blocked_reason": "missing cost one",
            }
        )
    )
    _reconcile_spend_guard(tmp_path, observed_total_usage_usd=10.0)
    first_path = tmp_path / publication_runner.SPEND_RECONCILIATION
    first_bytes = first_path.read_bytes()
    first_sha = hashlib.sha256(first_bytes).hexdigest()
    state = json.loads(state_path.read_text())
    state.update(active_call_reservation_usd=0.03, blocked_reason="missing cost two")
    state_path.write_text(json.dumps(state))

    second = _reconcile_spend_guard(tmp_path, observed_total_usage_usd=10.0)
    state = json.loads(state_path.read_text())
    second_path = tmp_path / "openrouter-spend-reconciliation-2.json"

    assert first_path.read_bytes() == first_bytes
    assert second_path.is_file()
    assert second["previous_reconciliation_evidence"] == publication_runner.SPEND_RECONCILIATION
    assert second["previous_reconciliation_sha256"] == first_sha
    assert state["reconciliation_history"] == [
        {"evidence": publication_runner.SPEND_RECONCILIATION, "sha256": first_sha},
        {"evidence": second_path.name, "sha256": hashlib.sha256(second_path.read_bytes()).hexdigest()},
    ]


def test_spend_reconciliation_rejects_nonfinite_ceiling(tmp_path: Path) -> None:
    (tmp_path / "openrouter-budget.json").write_text(json.dumps({"starting_total_usage_usd": 10.0}))
    state_path = tmp_path / publication_runner.CALL_SPEND_GUARD_STATE
    state_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "ceiling_usd": float("nan"),
                "reported_spend_usd": 0.001,
                "active_call_reservation_usd": 0.02,
                "blocked_reason": "missing cost",
            }
        )
    )

    with pytest.raises(ValueError, match="authorized ceiling"):
        _reconcile_spend_guard(tmp_path, observed_total_usage_usd=10.0)

    assert not (tmp_path / publication_runner.SPEND_RECONCILIATION).exists()


def test_spend_reconciliation_rejects_account_usage_below_run_start(tmp_path: Path) -> None:
    (tmp_path / "openrouter-budget.json").write_text(json.dumps({"starting_total_usage_usd": 10.0}))
    state_path = tmp_path / publication_runner.CALL_SPEND_GUARD_STATE
    state_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "ceiling_usd": 100.0,
                "reported_spend_usd": 0.0,
                "active_call_reservation_usd": 0.02,
                "blocked_reason": "missing cost",
            }
        )
    )

    with pytest.raises(ValueError, match="no less than the run start"):
        _reconcile_spend_guard(tmp_path, observed_total_usage_usd=9.99)

    assert not (tmp_path / publication_runner.SPEND_RECONCILIATION).exists()


def test_operator_ceiling_stays_permissive_when_no_cap_is_committed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A contract that has not chosen a number must not be given one silently."""
    protocol_path = tmp_path / "protocol.json"
    protocol_path.write_text(json.dumps({"budget_policy": {"operator_ceiling_usd": None}}))
    monkeypatch.setitem(
        publication_runner.CONTRACT_CONFIGS,
        "sota-test",
        (protocol_path, protocol_path, protocol_path, protocol_path, protocol_path),
    )
    publication_runner._enforce_operator_ceiling(10_000.00, "sota-test")

    protocol_path.write_text(json.dumps({"budget_policy": {"operator_ceiling_usd": "lots"}}))
    with pytest.raises(ValueError, match="must be a positive finite number"):
        publication_runner._enforce_operator_ceiling(1.00, "sota-test")


def test_operator_ceiling_fails_closed_when_the_protocol_cannot_be_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unreadable protocol is not a null ceiling: it may hide a committed cap.

    Every other malformed input to this gate raises; a corrupt or missing
    protocol file silently disabling the ceiling was the one fail-open path.
    """
    corrupt = tmp_path / "corrupt-protocol.json"
    corrupt.write_text("{this is not json")
    monkeypatch.setitem(
        publication_runner.CONTRACT_CONFIGS,
        "sota-corrupt-protocol",
        (corrupt,) * 5,
    )
    with pytest.raises(ValueError, match="operator ceiling"):
        publication_runner._enforce_operator_ceiling(1.00, "sota-corrupt-protocol")

    monkeypatch.setitem(
        publication_runner.CONTRACT_CONFIGS,
        "sota-missing-protocol",
        (tmp_path / "does-not-exist.json",) * 5,
    )
    with pytest.raises(ValueError, match="operator ceiling"):
        publication_runner._enforce_operator_ceiling(1.00, "sota-missing-protocol")


def test_paid_run_above_the_ceiling_is_refused_before_any_cell_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gate has to sit ahead of the cell loop, not inside it.

    Checked by proving that neither the endpoint probe nor a child process is
    reached: a ceiling enforced after the first cell has already spent money
    is not a ceiling.
    """
    _frozen_panel_files(tmp_path, monkeypatch)
    protocol = json.loads(publication_runner.PROTOCOL_CONFIG.read_text())
    protocol["budget_policy"]["operator_ceiling_usd"] = 120.00
    publication_runner.PROTOCOL_CONFIG.write_text(json.dumps(protocol))

    checked: list[str] = []
    child_calls: list[str] = []
    monkeypatch.setattr(
        publication_runner,
        "_validate_openrouter_endpoint",
        lambda cell, _env: checked.append(cell.experiment_id),
    )
    monkeypatch.setattr(
        publication_runner.subprocess,
        "run",
        lambda *_args, **_kwargs: child_calls.append("child"),
    )

    with pytest.raises(SystemExit) as exc_info:
        main(["smoke", "--contract", "sota-v3", "--run-dir", str(tmp_path), "--max-spend-usd", "500"])

    assert exc_info.value.code == 2
    assert checked == [], "a run over the ceiling reached the endpoint probe"
    assert child_calls == [], "a run over the ceiling launched a model"


def test_endpoint_preflight_enforces_both_uptime_floors() -> None:
    """The two windows catch different failures, so both have to gate.

    The 24h figure is a chronic filter and cannot see an outage in progress:
    on 2026-08-04 the first-party DeepSeek route was deranked to status -5
    while still reporting 99.24% over 24h.  The 30m figure is the one that
    moved, so it carries the acute signal. Missing or malformed telemetry is
    unknown health, so it must fail closed rather than read as a passing route.
    """
    cell = build_cells("smoke", model_id="openrouter-qwen3.7-plus-alibaba", cap=4096)[0]
    endpoint = _healthy_endpoint(cell)
    payload = {"data": {"endpoints": [endpoint]}}
    assert _endpoint_issues(cell, payload) == []

    # The acute case: the exact shape of the DeepSeek derank, which a 24h-only
    # floor waves straight through.
    endpoint["uptime_last_30m"], endpoint["uptime_last_1d"] = 78.93, 99.24
    issues = _endpoint_issues(cell, payload)
    assert issues and "30m uptime floor" in issues[0] and "78.93%" in issues[0]

    # The chronic case: recent traffic looks fine, the whole day did not.
    endpoint["uptime_last_30m"], endpoint["uptime_last_1d"] = 99.9, 80.0
    issues = _endpoint_issues(cell, payload)
    assert issues and "24h uptime floor" in issues[0] and "80.00%" in issues[0]

    for field, floor in (
        ("uptime_last_30m", publication_runner.MIN_UPTIME_LAST_30M_PCT),
        ("uptime_last_1d", publication_runner.MIN_UPTIME_LAST_1D_PCT),
    ):
        endpoint.update(_healthy_endpoint(cell))
        endpoint[field] = floor
        assert _endpoint_issues(cell, payload) == [], f"{field} floor must be inclusive"

    for field, value in (
        ("uptime_last_30m", None),
        ("uptime_last_30m", "unknown"),
        ("uptime_last_30m", float("nan")),
        ("uptime_last_1d", float("inf")),
    ):
        endpoint.update(_healthy_endpoint(cell))
        endpoint[field] = value
        issues = _endpoint_issues(cell, payload)
        assert issues and "no finite numeric" in issues[0], (field, value, issues)

    endpoint.update(_healthy_endpoint(cell))
    del endpoint["uptime_last_30m"], endpoint["uptime_last_1d"]
    issues = _endpoint_issues(cell, payload)
    assert issues and "no finite numeric" in issues[0]


def test_uptime_floors_sit_below_the_healthy_cohort_noise_band() -> None:
    """The floors must not flap.

    These readings drift by roughly half a point between consecutive polls,
    so a floor set near real values rejects healthy routes at random.  A 99%
    24h floor rejected two healthy cohort members on the day it was written.
    Both floors are therefore pinned well clear of the observed band.
    """
    assert publication_runner.MIN_UPTIME_LAST_30M_PCT <= 90.0
    assert publication_runner.MIN_UPTIME_LAST_1D_PCT <= 95.0


def test_endpoint_preflight_allows_registered_prompt_only_json_route() -> None:
    cell = build_cells("smoke", model_id="openrouter-tencent-hy3-free-novita", cap=4096)[0]
    assert cell.fixed_options["OPENROUTER_JSON_MODE"] == "false"
    payload = {
        "data": {
            "endpoints": [
                {
                    "provider_name": "Novita",
                    "tag": "novita",
                    "name": cell.endpoint_name,
                    "status": 0,
                    "max_completion_tokens": 262144,
                    "supported_parameters": ["max_tokens", "reasoning", "structured_outputs"],
                    "uptime_last_30m": 99.8,
                    "uptime_last_1d": 99.75,
                }
            ]
        }
    }
    assert _endpoint_issues(cell, payload) == []


def test_publication_status_tracks_active_progress_spend_and_ceiling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import fcntl

    registry, lane, manifest_path = _frozen_panel_files(tmp_path, monkeypatch)
    cell = build_cells("smoke", model_id=registry["models"][0]["id"])[0]
    _write_run_state(tmp_path, "smoke", [cell], 1.0)
    checkpoint_path = tmp_path / "checkpoints" / f"{cell.experiment_id}--{lane['output_token_cap']}.json"
    checkpoint_path.parent.mkdir(parents=True)
    checkpoint_path.write_text(
        json.dumps(
            {
                "format": "gm-bench-model-checkpoint-v1",
                "status": "running",
                "seeds": [1],
                "seasons": 1,
                "repeats": 1,
                "completed": [],
                "episodes": [],
            }
        )
    )
    lock_path = checkpoint_path.with_suffix(".json.lock")
    lock_path.write_text(f"pid={os.getpid()}\n")
    lock_descriptor = os.open(lock_path, os.O_RDONLY)
    fcntl.flock(lock_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    reservations = tmp_path / "openrouter-reservations.json"
    reservations.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "cells": {
                    f"{cell.experiment_id}--{cell.cap_label}": {
                        "experiment_id": cell.experiment_id,
                        "reserved_usd": 0.01,
                    }
                },
            }
        )
    )

    try:
        status = publication_run_status(tmp_path, manifest_path)
        row = next(row for row in status["rows"] if row["model_id"] == cell.experiment_id)
        assert status["phase"] == "smoke"
        assert status["spend_ceiling_usd"] == 1.0
        assert status["active_cells"] == 1
        assert status["reserved_spend_usd"] == 0.01
        assert row["state"] == "running"
        assert row["reserved_usd"] == pytest.approx(0.01)
        assert (row["completed_episodes"], row["total_episodes"]) == (0, 1)
        assert (row["completed_decisions"], row["total_decisions"]) == (0, 4)
    finally:
        os.close(lock_descriptor)


def test_publication_status_distinguishes_complete_and_accepted_smokes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, lane, manifest_path = _frozen_panel_files(tmp_path, monkeypatch)
    first, second = registry["models"][:2]
    _write_run_state(tmp_path, "smoke", [build_cells("smoke")[0]], 1.0)
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(parents=True)
    for model, cost in ((first, 0.01), (second, 0.02)):
        artifact = _valid_smoke_artifact(registry, lane, model)
        artifact["candidate"]["summary"]["usage"]["cost_usd"] = cost
        (raw_dir / f"{model['id']}--{lane['output_token_cap']}.json").write_text(json.dumps(artifact))
    manifest_path.write_text(json.dumps(_valid_manifest(registry, lane)))

    status = publication_run_status(tmp_path, manifest_path)
    rows = {row["model_id"]: row for row in status["rows"]}
    assert rows[first["id"]]["state"] == "accepted"
    assert rows[first["id"]]["completed_decisions"] == 4
    assert status["artifact_spend_usd"] == pytest.approx(0.03)
    assert status["accepted_smokes"] == 10
    assert "accepted smokes: 10/10" in render_publication_status(status)


def test_publication_status_does_not_mark_accepted_without_this_runs_raw_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An accepted manifest entry must not stand in for this run/cap's own artifact."""
    registry, lane, manifest_path = _frozen_panel_files(tmp_path, monkeypatch)
    model = registry["models"][0]
    _write_run_state(tmp_path, "smoke", [build_cells("smoke")[0]], 1.0)
    manifest_path.write_text(json.dumps(_valid_manifest(registry, lane)))

    status = publication_run_status(tmp_path, manifest_path)
    row = next(row for row in status["rows"] if row["model_id"] == model["id"])
    assert row["state"] == "queued"
    assert row["smoke_accepted"] is True


def test_publication_status_does_not_promote_complete_state_on_stale_manifest_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A manifest entry accepted at a different cap must not upgrade this cell's state."""
    registry, lane, manifest_path = _frozen_panel_files(tmp_path, monkeypatch)
    model = registry["models"][0]
    _write_run_state(tmp_path, "smoke", [build_cells("smoke")[0]], 1.0)
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(parents=True)
    artifact = _valid_smoke_artifact(registry, lane, model)
    (raw_dir / f"{model['id']}--{lane['output_token_cap']}.json").write_text(json.dumps(artifact))

    manifest = _valid_manifest(registry, lane)
    manifest["entries"][model["id"]]["output_token_cap"] = lane["output_token_cap"] + 1
    manifest_path.write_text(json.dumps(manifest))

    status = publication_run_status(tmp_path, manifest_path)
    row = next(row for row in status["rows"] if row["model_id"] == model["id"])
    assert row["state"] == "complete"
    assert row["smoke_accepted"] is True


def test_panel_status_keeps_smoke_acceptance_separate_from_panel_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, _lane, manifest_path = _frozen_panel_files(tmp_path, monkeypatch)
    cell = build_cells("smoke")[0]
    _write_run_state(tmp_path, "panel", [cell], 60.0)
    manifest_path.write_text(json.dumps(_valid_manifest(registry, _lane)))

    status = publication_run_status(tmp_path, manifest_path)
    assert status["accepted_smokes"] == 10
    assert status["completed_cells"] == 0
    assert {row["state"] for row in status["rows"]} == {"queued"}
    assert {row["total_episodes"] for row in status["rows"]} == {24}
    assert {row["total_decisions"] for row in status["rows"]} == {480}


def test_panel_status_surfaces_recorded_ineligible_outcome(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry, lane, manifest_path = _frozen_panel_files(tmp_path, monkeypatch)
    manifest_path.write_text(json.dumps(_valid_manifest(registry, lane)))
    cell = build_cells("panel", model_id=registry["models"][0]["id"])[0]
    _write_run_state(tmp_path, "panel", [cell], 95.0)
    run_state_path = tmp_path / "run-state.json"
    run_state = json.loads(run_state_path.read_text())
    run_state["cell_outcomes"][cell.experiment_id] = {
        "status": "ineligible",
        "error": "candidate usage must cover every decision point",
    }
    run_state_path.write_text(json.dumps(run_state))
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / f"{cell.experiment_id}--{lane['output_token_cap']}.json").write_text(
        json.dumps(_valid_smoke_artifact(registry, lane, registry["models"][0]))
    )

    status = publication_run_status(tmp_path, manifest_path)
    row = next(row for row in status["rows"] if row["model_id"] == cell.experiment_id)
    assert row["state"] == "ineligible"
    assert row["error"] == "candidate usage must cover every decision point"


def test_status_command_prints_snapshot_without_creating_run_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _runner_main(["status", "--contract", "sota-v2", "--run-dir", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert "GM-Bench publication run" in output
    assert "openrouter-gpt-5.6-luna-openai" in output
    assert list(tmp_path.iterdir()) == []
