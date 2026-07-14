from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from gm_bench.publication import PUBLICATION_FORMAT, canonical_sha256, compact_result


def _payload() -> dict:
    episode = {
        "seed": 11,
        "repeat": 1,
        "seasons": 5,
        "final_score": 12.5,
        "strategy_score": 14.5,
        "protocol_penalty": -2.0,
        "decisions": 20,
        "transactions": [{"message": "large trace"}],
        "season_summaries": [{"season": 1}],
        "usage": {"total_tokens": 100, "per_decision": [{"input_tokens": 4}]},
    }
    return {"candidate": {"episodes": [episode]}, "baselines": [{"episodes": [episode]}]}


def test_compact_result_removes_traces_and_hashes_raw_payload() -> None:
    raw = _payload()
    compact = compact_result(raw)
    assert compact["publication"] == {
        "format": PUBLICATION_FORMAT,
        "raw_artifact_sha256": canonical_sha256(raw),
        "traces_included": False,
        "mechanic_breakdown": {
            "draft": {"accepted": 0, "rejected": 0},
            "trades": {"accepted": 0, "rejected": 0},
            "cap_free_agency": {"accepted": 0, "rejected": 0},
            "lineup": {"accepted": 0, "rejected": 0},
            "information_memory": {"accepted": 0, "rejected": 0},
        },
    }
    episode = compact["candidate"]["episodes"][0]
    assert episode["seed"] == 11
    assert episode["final_score"] == 12.5
    assert "transactions" not in episode
    assert "season_summaries" not in episode
    assert episode["usage"] == {"total_tokens": 100}


def test_budget_analysis_refuses_empty_sweep(tmp_path: Path) -> None:
    output = tmp_path / "analysis.json"
    subprocess.run(["python3", "scripts/analyze_output_budget.py", "--output", str(output)], check=True)
    result = json.loads(output.read_text())
    assert result["status"] == "incomplete"
    assert result["publishable_ranking"] is False


def test_budget_analysis_does_not_discover_models_when_config_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("analyze_output_budget", Path("scripts/analyze_output_budget.py"))
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    monkeypatch.setattr(module, "validate_leaderboard_payload", lambda *args, **kwargs: type("R", (), {"ok": True})())
    config = json.loads(Path("config/output_budget_sweep.json").read_text())
    assert config["models"] == []
    payload = {
        "run_info": {
            "model": "accidental-model",
            "transport": "direct-api",
            "benchmark_contract": {"benchmark_version": "sota-v2"},
            "provider_options": {"GM_BENCH_OUTPUT_BUDGET_CELL": "256", "OPENAI_MAX_TOKENS": "256"},
        },
        "candidate": {
            "repeats": 3,
            "summary": {"decisions": 20, "mean_score": 1.0, "usage": {"input_tokens": 1, "output_tokens": 1}},
        },
    }
    result = module.analyze(config, [payload])
    assert result["status"] == "incomplete"
    assert result["models"] == []
    assert result["points"] == []
    assert any("no models selected" in reason for row in result["rejected_artifacts"] for reason in row["reasons"])


def test_budget_analysis_rejects_uncapped_cell_with_numeric_provider_max(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("analyze_output_budget", Path("scripts/analyze_output_budget.py"))
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    monkeypatch.setattr(module, "validate_leaderboard_payload", lambda *args, **kwargs: type("R", (), {"ok": True})())
    config = json.loads(Path("config/output_budget_sweep.json").read_text())
    config["models"] = ["demo-model"]
    payload = {
        "run_info": {
            "model": "demo-model",
            "provider": "openai",
            "transport": "direct-api",
            "benchmark_contract": {"benchmark_version": "sota-v2"},
            "provider_options": {
                "GM_BENCH_OUTPUT_BUDGET_CELL": "uncapped",
                "OPENAI_MAX_TOKENS": "4096",
            },
        },
        "candidate": {
            "repeats": 3,
            "summary": {
                "decisions": 20,
                "mean_score": 1.0,
                "decision_failure_rate": 0.0,
                "usage": {"input_tokens": 100, "output_tokens": 50},
            },
        },
    }
    result = module.analyze(config, [payload])
    assert result["points"] == []
    assert any(
        "does not match the provider output cap" in reason
        for row in result["rejected_artifacts"]
        for reason in row["reasons"]
    )
