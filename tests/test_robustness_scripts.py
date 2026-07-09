"""Smoke coverage for the standalone robustness diagnostics."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run_script(script: str, *args: str) -> dict[str, object]:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), *args, "--json"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_power_analysis_smoke() -> None:
    result = _run_script(
        "power_analysis.py",
        "--seeds",
        "11",
        "12",
        "--seasons",
        "2",
        "--repeats",
        "2",
        "--seed-counts",
        "2",
        "--trials",
        "20",
        "--gap-step",
        "10",
        "--max-gap",
        "20",
    )
    assert result["exact_sign_flip"]["minimum_p_value"] == 0.5
    assert len(result["across_seed_score_stddev"]) == 8
    assert "2" in result["mdd"]


def test_weight_sensitivity_smoke() -> None:
    result = _run_script(
        "weight_sensitivity.py",
        "--seeds",
        "11",
        "12",
        "--seasons",
        "2",
        "--draws",
        "20",
    )
    assert result["method"]["draws"] == 20
    assert len(result["canonical_ranking"]) == 8
    assert set(result["adjacent_rank_flip_probability"])
    assert result["max_recombination_error"] < 0.001
