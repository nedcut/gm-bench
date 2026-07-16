from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

import scripts.run_publication_matrix as publication_runner
from gm_bench.contract import contract_fingerprint, scaffold_fingerprint
from scripts.run_publication_matrix import (
    _artifact_spend_usd,
    _cell_reservation_usd,
    _endpoint_issues,
    _reserve_cell,
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
    assert len(build_cells("smoke")) == 12
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


def test_smoke_rejects_cap_that_differs_from_frozen_lane() -> None:
    with pytest.raises(ValueError, match="differs from frozen panel smoke cap"):
        build_cells("smoke", cap=1024)


def test_smoke_applies_each_models_registered_reasoning_policy() -> None:
    disabled = build_cells("smoke", model_id="openrouter-gpt-5.6-luna-openai")[0]
    mandatory = build_cells("smoke", model_id="openrouter-kimi-k3-moonshot")[0]

    assert disabled.fixed_options["OPENROUTER_REASONING_ENABLED"] == "false"
    assert "OPENROUTER_REASONING_EFFORT" in disabled.absent_options
    assert mandatory.fixed_options["OPENROUTER_REASONING_ENABLED"] == "true"
    assert mandatory.fixed_options["OPENROUTER_REASONING_EFFORT"] == "max"
    assert mandatory.fixed_options["OPENROUTER_PROVIDER_ONLY"] == "moonshotai/int4"


def test_panel_is_locked_until_model_registry_is_frozen() -> None:
    with pytest.raises(ValueError, match="locked until"):
        build_cells("panel")


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
    assert len(build_cells("panel")) == 12


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
    assert committed == pytest.approx(reservation * 2)
    assert stored["reserved_usd"] == pytest.approx(reservation * 2)
    assert stored["attempts"] == 2


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
                    f"{cell.experiment_id}--1024": {
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
        (raw_dir / f"{model['id']}--1024.json").write_text(json.dumps(artifact))
    manifest_path.write_text(json.dumps(_valid_manifest(registry, lane)))

    status = publication_run_status(tmp_path, manifest_path)
    rows = {row["model_id"]: row for row in status["rows"]}
    assert rows[first["id"]]["state"] == "accepted"
    assert rows[first["id"]]["completed_decisions"] == 4
    assert status["artifact_spend_usd"] == pytest.approx(0.03)
    assert status["accepted_smokes"] == 12
    assert "accepted smokes: 12/12" in render_publication_status(status)


def test_panel_status_keeps_smoke_acceptance_separate_from_panel_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry, _lane, manifest_path = _frozen_panel_files(tmp_path, monkeypatch)
    cell = build_cells("smoke")[0]
    _write_run_state(tmp_path, "panel", [cell], 60.0)
    manifest_path.write_text(json.dumps(_valid_manifest(registry, _lane)))

    status = publication_run_status(tmp_path, manifest_path)
    assert status["accepted_smokes"] == 12
    assert status["completed_cells"] == 0
    assert {row["state"] for row in status["rows"]} == {"queued"}
    assert {row["total_episodes"] for row in status["rows"]} == {24}
    assert {row["total_decisions"] for row in status["rows"]} == {480}


def test_status_command_prints_snapshot_without_creating_run_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["status", "--run-dir", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert "GM-Bench publication run" in output
    assert "openrouter-gpt-5.6-luna-openai" in output
    assert list(tmp_path.iterdir()) == []
