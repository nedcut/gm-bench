import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import compare_v21_round as compare  # noqa: E402


def _episode(seed: int, score: float) -> dict:
    return {
        "agent": "test:model",
        "seed": seed,
        "final_score": score,
        "failed_decisions": 0,
        "illegal_actions": 1,
        "agentic": {"tool_calls": 40},
    }


def _runs(tmp_path: Path, new_seeds: list[int], version: str = "gm-bench-2.1") -> tuple[Path, Path]:
    old, new = tmp_path / "old", tmp_path / "new"
    old.mkdir()
    (old / "run.json").write_text(json.dumps({"episodes": [_episode(s, 250.0) for s in (11, 12, 13)]}))
    for index, seed in enumerate(new_seeds):
        directory = new / f"episode-{index:02d}"
        directory.mkdir(parents=True)
        (directory / "result.json").write_text(json.dumps(_episode(seed, 240.0)))
        (directory / "ledger.jsonl").write_text(json.dumps({"event": "episode", "benchmark_version": version}) + "\n")
    return old, new


def test_partial_run_pairs_by_position(tmp_path: Path) -> None:
    old, new = _runs(tmp_path, [11, 12])
    row = compare.compare_pair(old, new, {"old": -5.0})
    assert row["episodes"] == 2
    assert row["lift_2_0_score_v2_e_full_panel"] == -5.0
    assert row["per_episode"]["tool_calls"] == {"2.0": 40.0, "2.1": 40.0}
    assert set(row["lift_2_1"]) >= {"mean", "se", "sign_flip_p", "mde80"}


def test_mismatched_seeds_are_refused(tmp_path: Path) -> None:
    old, new = _runs(tmp_path, [12, 11])
    with pytest.raises(SystemExit):
        compare.compare_pair(old, new, {})


def test_a_2_0_run_is_refused_as_the_2_1_side(tmp_path: Path) -> None:
    old, new = _runs(tmp_path, [11, 12], version="gm-bench-2.0")
    with pytest.raises(SystemExit):
        compare.compare_pair(old, new, {})


def test_kendall_tau() -> None:
    assert compare.kendall_tau([3, 2, 1], [30, 20, 10]) == 1.0
    assert compare.kendall_tau([1, 2], [2, 1]) == -1.0
    # A tie in either column is not a reversal.
    assert compare.kendall_tau([1, 1, 3], [1, 2, 3]) == pytest.approx(2 / 3)


def test_a_different_agent_is_refused(tmp_path: Path) -> None:
    old, new = _runs(tmp_path, [11, 12])
    result = new / "episode-01" / "result.json"
    result.write_text(json.dumps(dict(json.loads(result.read_text()), agent="other:model")))
    with pytest.raises(SystemExit, match="same single agent"):
        compare.compare_pair(old, new, {})


def _row(ci95: list[float], v1: float, e: float | None) -> dict:
    return {"lift_2_1": {"ci95": ci95}, "lift_2_0_score_v1": {"mean": v1}, "lift_2_0_score_v2_e_full_panel": e}


def test_a_sign_conflict_counts_against_either_2_0_column() -> None:
    assert not compare.sign_conflict(_row([5, 20], 3, 4))
    assert compare.sign_conflict(_row([5, 20], 3, -4))
    assert compare.sign_conflict(_row([-20, -5], 3, None))
    # An interval that includes zero conflicts with nothing.
    assert not compare.sign_conflict(_row([-5, 10], -3, -11))
