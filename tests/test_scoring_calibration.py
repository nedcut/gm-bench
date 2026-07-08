from __future__ import annotations

import json
from dataclasses import replace

import pytest

from gm_bench import cli as cli_module
from gm_bench.calibration import build_scoring_calibration, marginal_value_table
from gm_bench.contract import benchmark_contract
from gm_bench.scoring import (
    ACTIVE_SCORE_SCALE,
    SCORE_SCALES,
    SCORING_VERSION,
    score_breakdown,
    score_components,
    scoring_scale_fingerprint,
    validate_published_scoring_scale,
)
from gm_bench.simulator import League


def test_published_score_scale_is_versioned_and_fingerprinted() -> None:
    assert SCORING_VERSION == "score-v1"
    assert scoring_scale_fingerprint() == "05a60ff4f691e734"
    assert benchmark_contract()["scoring_scale_fingerprint"] == scoring_scale_fingerprint()
    validate_published_scoring_scale()


def test_published_version_rejects_weight_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        SCORE_SCALES,
        SCORING_VERSION,
        replace(ACTIVE_SCORE_SCALE, championship=ACTIVE_SCORE_SCALE.championship + 1.0),
    )
    with pytest.raises(RuntimeError, match="changed without a new published version"):
        validate_published_scoring_scale()


def test_score_breakdown_is_sum_of_exposed_contributions() -> None:
    league = League.new(seed=3)
    components = score_components(league, league.user_team_id)
    breakdown = score_breakdown(league, league.user_team_id)
    contribution_sum = sum(value for key, value in components.items() if key.endswith("_contribution"))

    assert breakdown["strategy_score"] == contribution_sum
    assert breakdown["protocol_penalty"] == components["protocol_penalty"]
    assert breakdown["final_score"] == contribution_sum - components["protocol_penalty"]


def test_required_marginal_value_scenarios_are_explicit() -> None:
    rows = {row["scenario"]: row["score_delta"] for row in marginal_value_table()}
    assert rows["one championship"] == 35.0
    assert rows["ten recent wins"] == 4.2
    assert rows["twenty veteran asset value"] == 3.2
    assert rows["twenty young asset value"] == 6.8
    assert rows["ten cap room before clamp"] == 3.5
    assert rows["one illegal action"] == -2.5


def test_calibration_report_runs_reference_ablations() -> None:
    report = build_scoring_calibration(seeds=[11], seasons=1)
    names = [row["agent"] for row in report["policies"]]

    assert report["panel"] == {"seeds": [11], "seasons": 1}
    assert names == [
        "pick-trader",
        "strategic",
        "strategic-no-scout",
        "strategic-no-offers",
        "strategic-no-memo",
        "shrewd",
        "value",
    ]
    assert all(row["illegal_actions"] == 0 for row in report["policies"])


def test_cli_calibrate_score_json(capsys: pytest.CaptureFixture[str]) -> None:
    cli_module.main(["calibrate-score", "--seeds", "11", "--seasons", "1", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert payload["scoring_scale"]["version"] == SCORING_VERSION
    assert payload["panel"] == {"seeds": [11], "seasons": 1}
