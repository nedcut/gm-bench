"""The GM-Bench 2.1 lane: its config, its reference, and the committed 2.1 rows."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gm_bench.agentic.publication import (
    LANE_CONFIGS,
    REFERENCE_AGENT,
    load_lane_config,
    reference_contrast,
    validate_agentic_artifact,
)
from gm_bench.agents import AGENTS
from gm_bench.runner import run_episode as run_v1
from gm_bench.v21.runner import run_episode as run_v21

V20, V21 = "gm-bench-2.0", "gm-bench-2.1"
ROWS_V20 = sorted(Path("results/agentic").glob("*.json"))
ROWS_V21 = sorted(Path("results/agentic_v21").glob("*.json"))


def test_each_contract_has_its_own_lane_on_one_shared_private_panel() -> None:
    lane20, lane21 = load_lane_config(version=V20), load_lane_config(version=V21)
    assert set(LANE_CONFIGS) == {V20, V21}
    assert lane21["benchmark_version"] == V21 and "benchmark_version" not in lane20
    # Same seeds, same order, same escrow: a 2.1 row pairs seed by seed with the model's 2.0 row.
    assert lane21["seed_panel"] == lane20["seed_panel"]
    assert lane21["panel_design"]["reference_agent"] == REFERENCE_AGENT
    pins = lane21["reference_scores"]["mean_scores"]
    assert pins == {key: lane21["scripted_bot_scores"]["mean_scores"][key] for key in pins}
    assert pins != lane20["reference_scores"]["mean_scores"]


def test_a_2_1_reference_is_played_under_the_2_1_rules() -> None:
    raw = {"contract": {"benchmark_version": V21}, "seasons": 1, "episodes": [{"seed": 11, "final_score": 100.0}]}
    reference = reference_contrast(raw)
    expected = run_v21(AGENTS[REFERENCE_AGENT](), 11, seasons=1)["final_score"]
    assert reference["mean_score"] == expected
    assert reference["paired_lift_mean"] == round(100.0 - expected, 3)
    v1 = run_v1(AGENTS[REFERENCE_AGENT](), seed=11, seasons=1).final_score
    assert reference_contrast({**raw, "contract": {"benchmark_version": V20}})["mean_score"] == v1 != expected


def test_an_unknown_contract_cannot_be_published() -> None:
    raw = {
        "contract": {"benchmark_version": "gm-bench-9.9"},
        "seasons": 1,
        "episodes": [{"seed": 11, "final_score": 1}],
    }
    with pytest.raises(ValueError, match="no lane"):
        reference_contrast(raw)


@pytest.mark.parametrize("path", ROWS_V21, ids=lambda path: path.name)
def test_committed_2_1_rows_validate_against_the_2_1_lane(path: Path) -> None:
    artifact = json.loads(path.read_text())
    assert artifact["contract"]["benchmark_version"] == V21
    report = validate_agentic_artifact(artifact)
    assert report["ok"], report["errors"]
    assert artifact["grade"] == "panel"
    assert (
        artifact["reference"]["mean_score"]
        == load_lane_config(version=V21)["reference_scores"]["mean_scores"][REFERENCE_AGENT]
    )


def test_rows_sit_in_the_directory_of_their_contract() -> None:
    assert ROWS_V21, "no committed 2.1 rows"
    for path in ROWS_V20:
        assert (json.loads(path.read_text()).get("contract") or {}).get("benchmark_version", V20) == V20, path
    for path in ROWS_V21:
        assert json.loads(path.read_text())["contract"]["benchmark_version"] == V21, path


def test_a_2_1_row_is_not_accepted_by_the_2_0_lane() -> None:
    artifact = json.loads(ROWS_V21[0].read_text())
    report = validate_agentic_artifact(artifact, lane=load_lane_config(version=V20))
    assert not report["ok"]
    assert any("lane config is for gm-bench-2.0" in error for error in report["errors"]), report["errors"]


def test_a_2_1_row_with_the_2_0_reference_mean_is_rejected() -> None:
    artifact = json.loads(ROWS_V21[0].read_text())
    pinned_v20 = load_lane_config(version=V20)["reference_scores"]["mean_scores"][REFERENCE_AGENT]
    shift = pinned_v20 - artifact["reference"]["mean_score"]
    artifact["reference"]["mean_score"] = pinned_v20
    artifact["reference"]["paired_lift_mean"] = round(artifact["reference"]["paired_lift_mean"] - shift, 3)
    artifact["reference"]["paired_lift_ci95"] = [round(b - shift, 3) for b in artifact["reference"]["paired_lift_ci95"]]
    report = validate_agentic_artifact(artifact)
    assert not report["ok"]
    assert any("is not the frozen panel's" in error and "bench_v21_lane.json" in error for error in report["errors"]), (
        report["errors"]
    )
