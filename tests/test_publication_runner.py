from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from scripts.run_publication_matrix import _artifact_spend_usd, build_cells, cell_command, cell_environment


def test_sweep_matrix_is_pre_registered_and_serial(tmp_path: Path) -> None:
    cells = build_cells("sweep")
    assert len(cells) == 12
    assert {cell.cap for cell in cells} == {256, 1024, 4096, None}
    assert len({cell.experiment_id for cell in cells}) == 3
    for cell in cells:
        env = cell_environment(cell)
        command = cell_command(cell, tmp_path)
        assert env["GM_BENCH_WORKERS"] == "1"
        assert env["OPENROUTER_PROVIDER_ONLY"] == cell.fixed_options["OPENROUTER_PROVIDER_ONLY"]
        assert command[:4] == [sys.executable, "-m", "gm_bench", "model"]
        assert command[command.index("--workers") + 1] == "1"
        assert "--resume" not in command


def test_uncapped_cell_removes_inherited_provider_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_MAX_TOKENS", "999")
    cell = next(cell for cell in build_cells("sweep") if cell.cap is None)
    env = cell_environment(cell)
    assert "OPENROUTER_MAX_TOKENS" not in env
    assert env["GM_BENCH_OUTPUT_BUDGET_CELL"] == "uncapped"


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
