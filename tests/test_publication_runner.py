from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.run_publication_matrix as publication_runner
from gm_bench.contract import contract_fingerprint, scaffold_fingerprint
from scripts.run_publication_matrix import (
    _artifact_spend_usd,
    _cell_reservation_usd,
    _endpoint_issues,
    _panel_artifact_issues,
    _record_failed_cell_reservation,
    _record_ineligible_cell_reservation,
    _reserve_cell,
    _settle_cell_reservation,
    _write_run_state,
    build_cells,
    cell_command,
    cell_environment,
    main,
    publication_run_status,
    render_publication_status,
)


def _frozen_panel_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict, dict, Path]:
    registry = json.loads(Path("config/sota_v2_models.json").read_text())
    registry["selection_status"] = "frozen"
    lane = json.loads(Path("config/sota_v2_lane.json").read_text())
    lane["output_budget_status"] = "frozen-native-reasoning-cap"
    lane.pop("smoke_manifest", None)
    registry_path = tmp_path / "models.json"
    lane_path = tmp_path / "lane.json"
    manifest_path = tmp_path / "smokes.json"
    registry_path.write_text(json.dumps(registry))
    lane_path.write_text(json.dumps(lane))
    monkeypatch.setattr(publication_runner, "PANEL_CONFIG", registry_path)
    monkeypatch.setattr(publication_runner, "LANE_CONFIG", lane_path)
    monkeypatch.setattr(publication_runner, "SMOKE_MANIFEST", manifest_path)
    return registry, lane, manifest_path


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
            "accepted": True,
        }
    return {
        "format": "gm-bench-smoke-manifest-v1",
        "schema_version": 1,
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
            "provider_options": {
                **registry["shared_fixed_options"],
                **model["fixed_options"],
                "OPENROUTER_PROVIDER_ONLY": model["upstream_provider_slug"],
                "OPENROUTER_EXPECTED_UPSTREAM_PROVIDER": model["upstream_provider"],
                "OPENROUTER_EXPECTED_ENDPOINT_NAME": model["endpoint_name"],
                "GM_BENCH_OUTPUT_BUDGET_CELL": str(lane["output_token_cap"]),
            },
            "benchmark_contract": {"contract_fingerprint": contract_fingerprint()},
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


def test_runner_rejects_cap_outside_pre_registered_sweep() -> None:
    with pytest.raises(ValueError, match="not in the pre-registered sweep"):
        build_cells("sweep", cap=999)


def test_smoke_is_clean_and_resumes_existing_checkpoint(tmp_path: Path) -> None:
    assert len(build_cells("smoke")) == 10
    cell = build_cells("smoke", model_id="openrouter-qwen3.7-plus-alibaba")[0]
    command = cell_command(cell, tmp_path)
    assert cell.preset == "smoke"
    assert cell.repeats == 1
    assert cell.cap == 4096
    assert "--require-clean" in command
    checkpoint = tmp_path / "checkpoints" / f"{cell.experiment_id}--4096.json"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.touch()
    assert "--resume" in cell_command(cell, tmp_path)


def test_smoke_reuses_only_existing_artifact_that_passes_current_gate(tmp_path: Path) -> None:
    registry = json.loads(Path("config/sota_v2_models.json").read_text())
    lane = json.loads(Path("config/sota_v2_lane.json").read_text())
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
    registry = json.loads(Path("config/sota_v2_models.json").read_text())
    lane = json.loads(Path("config/sota_v2_lane.json").read_text())
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
        lambda cell: validated.append(cell.experiment_id),
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


def test_committed_panel_is_unlocked_after_registry_and_smoke_freeze() -> None:
    assert len(build_cells("panel")) == 10


def test_panel_stays_locked_when_frozen_registry_has_no_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _frozen_panel_files(tmp_path, monkeypatch)
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
    entry = json.loads(manifest_path.read_text())["entries"][model["id"]]
    assert entry["accepted"] is True
    assert entry["artifact_sha256"] == expected_sha
    assert entry["artifact_path"] == str(artifact_path)
    assert entry["decisions_with_usage"] == 4
    assert entry["cost_decisions"] == 4
    assert entry["protocol_repair_attempts"] == 0
    assert entry["protocol_repairs_succeeded"] == 0


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
    assert not manifest_path.exists()


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
    assert not manifest_path.exists()


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
    assert not manifest_path.exists()


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
    assert not manifest_path.exists()


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
    assert not manifest_path.exists()


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
    assert not manifest_path.exists()


def test_artifact_spend_uses_completed_result_telemetry(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "one.json").write_text(json.dumps({"candidate": {"summary": {"usage": {"cost_usd": 0.12}}}}))
    (raw / "two.json").write_text(json.dumps({"candidate": {"summary": {"usage": {"cost_usd": 0.03}}}}))
    assert _artifact_spend_usd(tmp_path) == pytest.approx(0.15)


def test_paid_openrouter_run_requires_explicit_spend_ceiling(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        main(
            [
                "smoke",
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


def test_cell_reservation_covers_repairs_and_cost_contingency() -> None:
    cell = build_cells("panel", model_id="openrouter-gpt-5.6-luna-openai")[0]
    pricing = json.loads(Path("config/openrouter_pricing_snapshot.json").read_text())
    assumptions = pricing["planning_assumptions"]
    rates = pricing["models"][cell.model]
    decisions = 8 * 5 * 4 * 3
    base = decisions * (assumptions["input_tokens_per_decision"] * rates["prompt"] + cell.cap * rates["completion"])

    assert cell.fixed_options["GM_BENCH_PROTOCOL_REPAIR_ATTEMPTS"] == "1"
    assert _cell_reservation_usd(cell) == pytest.approx(base * 2 * assumptions["cost_contingency_multiplier"], abs=1e-6)


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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    monkeypatch.setattr(publication_runner, "_validate_openrouter_endpoint", lambda _cell: None)
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
    assert main(["status", "--run-dir", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert "GM-Bench publication run" in output
    assert "openrouter-gpt-5.6-luna-openai" in output
    assert list(tmp_path.iterdir()) == []
