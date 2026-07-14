from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from scripts.run_publication_matrix import (
    _artifact_spend_usd,
    _cell_reservation_usd,
    _endpoint_issues,
    _reserve_cell,
    build_cells,
    cell_command,
    cell_environment,
    main,
)


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
    cell = build_cells("smoke", model_id="openrouter-qwen3.5-9b-siliconflow")[0]
    command = cell_command(cell, tmp_path)
    assert cell.preset == "smoke"
    assert cell.repeats == 1
    assert "--require-clean" in command
    checkpoint = tmp_path / "checkpoints" / f"{cell.experiment_id}--256.json"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.touch()
    assert "--resume" in cell_command(cell, tmp_path)


def test_panel_is_locked_until_lane_cap_is_frozen() -> None:
    with pytest.raises(ValueError, match="locked until"):
        build_cells("panel")


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
                "openrouter-qwen3.5-9b-siliconflow",
                "--run-dir",
                str(tmp_path),
            ]
        )
    assert exc.value.code == 2
    assert "require an explicit --max-spend-usd ceiling" in capsys.readouterr().err


def test_cell_reservation_blocks_launch_before_ceiling_overrun(tmp_path: Path) -> None:
    cell = build_cells("smoke", model_id="openrouter-gpt-5.4-mini-openai", cap=1024)[0]
    reservation = _cell_reservation_usd(cell)
    assert 0 < reservation < 1
    with pytest.raises(SystemExit, match="reservation would exceed"):
        _reserve_cell(tmp_path, cell, measured_spend=0.99, ceiling=1.0)
    assert not (tmp_path / "openrouter-reservations.json").exists()


def test_endpoint_preflight_requires_frozen_healthy_capable_route() -> None:
    cell = build_cells("smoke", model_id="openrouter-qwen3.5-9b-siliconflow", cap=1024)[0]
    valid = {
        "data": {
            "endpoints": [
                {
                    "provider_name": "SiliconFlow",
                    "name": cell.endpoint_name,
                    "status": 0,
                    "max_completion_tokens": 4096,
                    "supported_parameters": ["max_tokens", "response_format", "reasoning"],
                }
            ]
        }
    }
    assert _endpoint_issues(cell, valid) == []
    valid["data"]["endpoints"][0]["name"] = "SiliconFlow | replaced-snapshot"
    assert "no healthy OpenRouter endpoint" in _endpoint_issues(cell, valid)[0]
    valid["data"]["endpoints"][0]["name"] = cell.endpoint_name
    valid["data"]["endpoints"][0]["supported_parameters"] = ["max_tokens", "response_format"]
    assert "cannot honor required parameters" in _endpoint_issues(cell, valid)[0]
