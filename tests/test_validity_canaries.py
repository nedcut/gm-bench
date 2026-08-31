from __future__ import annotations

import json

import pytest

from gm_bench import cli as cli_module
from gm_bench.benchmark_config import PRESETS
from gm_bench.validity import (
    CANARY_MIN_PAIRED_T,
    CANARY_SEEDS,
    _paired_significance_check,
    run_validity_canaries,
)


def test_official_validity_canaries_underperform_value() -> None:
    result = run_validity_canaries()
    assert result["ok"], result["checks"]
    # The canaries deliberately run a wider panel than the paid leaderboard
    # lane. Every policy they exercise is scripted and costs only CPU, while the
    # leaderboard width is set by what a model row costs in API spend, so the
    # two were never under the same constraint. On the final contract the
    # headline ordering measures paired t=-0.004 at 8 seeds and 2.559 at 24.
    assert result["seeds"] == list(CANARY_SEEDS)
    assert len(result["seeds"]) > len(PRESETS["leaderboard"]["seeds"])
    assert result["seasons"] == PRESETS["leaderboard"]["seasons"]
    # `baselines` is emitted in a fixed literal order, so asserting its sequence
    # tests nothing about scores -- it restates the order the code wrote them in.
    # It previously read as a top-three ordering invariant and could not fail;
    # on the 24-seed panel the actual score order is shrewd > strategic >
    # pick-trader, which that assertion happily accepted. Assert membership, and
    # leave orderings to the paired-significance checks, which can fail.
    assert {row["agent"] for row in result["baselines"]} == {"pick-trader", "strategic", "shrewd", "value"}
    assert all(row["seed_count"] >= row["minimum_seed_count"] for row in result["mechanic_coverage"])
    release_coverage = next(row for row in result["mechanic_coverage"] if row["mechanic"] == "release")
    # Re-pinned for v6 free-agent willingness: repriced signings shift which
    # roster spots the baselines clear via release.
    assert release_coverage == {
        "mechanic": "release",
        "accepted_actions": 8,
        "seed_count": 7,
        "seed_rate": 0.292,
        "minimum_seed_count": 3,
    }
    significance = [check for check in result["checks"] if check["name"].endswith("_paired_significance")]
    honest_significance = [check for check in significance if check["name"] == "honest_bar_paired_significance"]
    assert [(check["winner"], check["loser"]) for check in honest_significance] == [("pick-trader", "value")]
    assert ("shrewd", "value") in {(check["winner"], check["loser"]) for check in significance}
    assert all(check["ok"] for check in significance)
    canary_names = {row["agent"] for row in result["canaries"]}
    assert {"exploit", "pick-hoard", "cap-hoard", "accept-everything"} <= canary_names


def test_paired_significance_rejects_a_noisy_positive_mean() -> None:
    winner = {
        "episodes": [
            {"seed": seed, "final_score": score} for seed, score in enumerate([11.0, -8.0, 11.0, -8.0], start=1)
        ]
    }
    loser = {"episodes": [{"seed": seed, "final_score": 0.0} for seed in range(1, 5)]}

    check = _paired_significance_check(winner, loser, "winner", "loser", "final_score", "honest_bar")

    assert check["paired_mean_difference"] == 1.5
    assert check["margin"] < CANARY_MIN_PAIRED_T
    assert not check["ok"]


def test_paired_significance_requires_matching_seed_panels() -> None:
    winner = {"episodes": [{"seed": 1, "final_score": 10.0}, {"seed": 2, "final_score": 10.0}]}
    loser = {"episodes": [{"seed": 1, "final_score": 0.0}, {"seed": 3, "final_score": 0.0}]}

    check = _paired_significance_check(winner, loser, "winner", "loser", "final_score", "honest_bar")

    assert not check["complete_pairing"]
    assert not check["ok"]


def test_cli_validate_contract_json(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(
        cli_module,
        "run_validity_canaries",
        lambda **kwargs: {
            "ok": True,
            "seeds": kwargs["seeds"],
            "seasons": kwargs["seasons"],
            "baselines": [],
            "canaries": [],
            "checks": [],
        },
    )

    cli_module.main(["validate-contract", "--seeds", "11", "12", "--seasons", "2", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["seeds"] == [11, 12]
    assert payload["seasons"] == 2


def test_cli_validate_contract_exits_nonzero_on_failed_canary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli_module,
        "run_validity_canaries",
        lambda **kwargs: {
            "ok": False,
            "seeds": [11],
            "seasons": 1,
            "baselines": [],
            "canaries": [],
            "checks": [
                {
                    "ok": False,
                    "winner": "value",
                    "loser": "pick-hoard",
                    "metric": "mean_score",
                    "margin": -1.0,
                    "minimum_margin": 25.0,
                }
            ],
        },
    )

    with pytest.raises(SystemExit) as excinfo:
        cli_module.main(["validate-contract"])
    assert excinfo.value.code == 1
