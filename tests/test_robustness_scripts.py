"""Smoke coverage for the standalone robustness diagnostics."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

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


def test_weight_sensitivity_reweights_a_saved_artifact_without_rerunning(tmp_path: Path) -> None:
    from gm_bench.agents import AGENTS
    from gm_bench.runner import run_many
    from scripts.weight_sensitivity import analyse

    seeds = [11, 12]
    blocks = {name: run_many(AGENTS[name](), seeds=seeds, seasons=2, workers=1) for name in ("strategic", "value")}
    for name, block in blocks.items():
        block["agent"] = name
    artifact = tmp_path / "result.json"
    artifact.write_text(
        json.dumps({"seeds": seeds, "seasons": 2, "candidate": blocks["strategic"], "baselines": [blocks["value"]]})
    )

    result = analyse(seeds=[], seasons=0, draws=10, perturbation=0.3, result=artifact)

    assert result["panel"]["rows"] == ["strategic", "value"]
    assert result["max_recombination_error"] < 0.001


def test_weight_sensitivity_rejects_a_pre_v3_artifact(tmp_path: Path) -> None:
    from scripts.weight_sensitivity import analyse

    artifact = tmp_path / "legacy.json"
    artifact.write_text(json.dumps({"candidate": {"agent": "x", "episodes": [{"seed": 11, "final_score": 1.0}]}}))

    with pytest.raises(SystemExit, match="lack score_components"):
        analyse(seeds=[], seasons=0, draws=10, perturbation=0.3, result=artifact)


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
