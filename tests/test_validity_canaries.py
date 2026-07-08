from __future__ import annotations

import json

import pytest

from gm_bench import cli as cli_module
from gm_bench.benchmark_config import PRESETS
from gm_bench.validity import run_validity_canaries


def test_official_validity_canaries_underperform_value() -> None:
    result = run_validity_canaries()
    assert result["ok"], result["checks"]
    assert result["seeds"] == PRESETS["leaderboard"]["seeds"]
    assert result["seasons"] == PRESETS["leaderboard"]["seasons"]
    assert [row["agent"] for row in result["baselines"][:3]] == ["pick-trader", "strategic", "shrewd"]
    assert all(row["seed_count"] >= row["minimum_seed_count"] for row in result["mechanic_coverage"])
    canary_names = {row["agent"] for row in result["canaries"]}
    assert {"exploit", "pick-hoard", "cap-hoard", "accept-everything"} <= canary_names


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
