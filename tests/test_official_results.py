from __future__ import annotations

import json
from pathlib import Path

import pytest

from gm_bench import cli as cli_module
from gm_bench.benchmark_config import PRESETS, PRIVATE_SEEDS_ENV, seed_panel_metadata
from gm_bench.contract import benchmark_contract
from gm_bench.official import (
    PUBLIC_LEADERBOARD_POLICY,
    REDACTED_SEEDS_SENTINEL,
    SOTA_V1_POLICY,
    redact_leaderboard_payload,
    validate_leaderboard_payload,
)
from web.scripts.build_leaderboard import model_row


def _official_payload(*, repeats: int = 1, failure_rate: float = 0.0, seeds: list[int] | None = None) -> dict:
    leaderboard = PRESETS["leaderboard"]
    seeds = list(seeds or leaderboard["seeds"])
    seasons = int(leaderboard["seasons"])
    decisions = len(seeds) * repeats * seasons * 3
    failed = round(decisions * failure_rate)
    candidate = {
        "agent": "openai:gpt-test",
        "seeds": seeds,
        "seasons": seasons,
        "repeats": repeats,
        "episodes": [
            {
                "seed": seed,
                "repeat": repeat,
                "seasons": seasons,
                "final_score": 350.0,
                "strategy_score": 350.0,
                "protocol_penalty": 0.0,
                "wins": 120,
                "championships": 2,
                "illegal_actions": 0,
            }
            for seed in seeds
            for repeat in range(1, repeats + 1)
        ],
        "summary": {
            "mean_score": 350.0,
            "score_stddev": 10.0,
            "illegal_actions": 0,
            "decisions": decisions,
            "failed_decisions": failed,
            "decision_failure_rate": round(failed / decisions, 3),
            "usage": {
                "decisions_with_usage": decisions,
                "cost_usd": 1.23,
            },
        },
    }
    baselines = [
        {
            "agent": name,
            "seeds": seeds,
            "seasons": seasons,
            "episodes": [
                {
                    "seed": seed,
                    "seasons": seasons,
                    "final_score": 300.0 if name == "shrewd" else 100.0,
                    "strategy_score": 300.0 if name == "shrewd" else 100.0,
                    "protocol_penalty": 0.0,
                    "wins": 90,
                    "championships": 1,
                    "illegal_actions": 0,
                }
                for seed in seeds
            ],
            "summary": {
                "mean_score": 300.0 if name == "shrewd" else 100.0,
                "score_stddev": 0.0,
            },
        }
        for name in leaderboard["baselines"]
    ]
    return {
        "agent": "openai:gpt-test",
        "seeds": seeds,
        "seasons": seasons,
        "candidate": candidate,
        "baselines": baselines,
        "normalized": {
            "candidate_mean_score": 350.0,
            "baseline_panel_mean_score": 133.333,
            "score_lift": 216.667,
        },
        "paired": {
            "num_seeds": len(seeds),
            "per_seed": [],
            "paired_lift_mean": 216.667,
            "paired_lift_ci95": [200.0, 230.0],
            "sign_flip_p_value": 0.0078,
            "significant_at_95": True,
            "candidate_seed_win_rate": 1.0,
            "best_baseline": {
                "agent": "shrewd",
                "mean_score": 300.0,
                "paired_lift_mean": 50.0,
                "seed_win_rate": 1.0,
            },
        },
        "run_info": {
            "command": "model",
            "agent": "openai:gpt-test",
            "provider": "openai",
            "model": "gpt-test",
            "preset": "leaderboard",
            "profile": "compact",
            "gm_bench_version": "0.1.0",
            "benchmark_contract": benchmark_contract(),
            "seed_panel": seed_panel_metadata(seeds, "leaderboard"),
        },
    }


def test_public_leaderboard_policy_accepts_single_repeat_payload() -> None:
    report = validate_leaderboard_payload(_official_payload(), policy=PUBLIC_LEADERBOARD_POLICY)
    assert report.ok


def test_sota_v1_policy_requires_repeats() -> None:
    report = validate_leaderboard_payload(_official_payload(repeats=1), policy=SOTA_V1_POLICY)
    assert not report.ok
    assert "candidate.repeats must be >= 3 for sota-v1" in report.errors


def test_sota_v1_policy_rejects_high_failure_rate() -> None:
    report = validate_leaderboard_payload(_official_payload(repeats=3, failure_rate=0.05), policy=SOTA_V1_POLICY)
    assert not report.ok
    assert any("decision_failure_rate" in error for error in report.errors)


def test_sota_v1_policy_requires_contract_provenance() -> None:
    payload = _official_payload(repeats=3)
    del payload["run_info"]["benchmark_contract"]
    report = validate_leaderboard_payload(payload, policy=SOTA_V1_POLICY)
    assert not report.ok
    assert "run_info.benchmark_contract is required for current-contract validation" in report.errors


def test_sota_v1_policy_requires_seed_panel_provenance() -> None:
    payload = _official_payload(repeats=3)
    del payload["run_info"]["seed_panel"]
    report = validate_leaderboard_payload(payload, policy=SOTA_V1_POLICY)
    assert not report.ok
    assert "run_info.seed_panel is required for official seed-panel validation" in report.errors


def test_sota_v1_policy_rejects_contract_fingerprint_mismatch() -> None:
    payload = _official_payload(repeats=3)
    payload["run_info"]["benchmark_contract"]["contract_fingerprint"] = "stale"
    report = validate_leaderboard_payload(payload, policy=SOTA_V1_POLICY)
    assert not report.ok
    assert any("contract_fingerprint" in error for error in report.errors)


def test_sota_v1_policy_accepts_private_panel_when_env_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    private_seeds = [101, 102, 110, 111, 112, 113, 114, 115]
    monkeypatch.setenv(PRIVATE_SEEDS_ENV, "101,102,110-115")
    report = validate_leaderboard_payload(
        _official_payload(repeats=3, seeds=private_seeds),
        policy=SOTA_V1_POLICY,
    )
    assert report.ok


def test_sota_v1_policy_rejects_too_small_private_panel(monkeypatch: pytest.MonkeyPatch) -> None:
    private_seeds = [101, 102, 110, 111]
    monkeypatch.setenv(PRIVATE_SEEDS_ENV, "101,102,110-111")
    report = validate_leaderboard_payload(
        _official_payload(repeats=3, seeds=private_seeds),
        policy=SOTA_V1_POLICY,
    )
    assert not report.ok
    assert "seeds must contain at least 8 seed(s) for sota-v1" in report.errors


def test_sota_v1_policy_rejects_private_panel_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    private_seeds = [101, 102, 110, 111, 112, 113, 114, 115]
    monkeypatch.setenv(PRIVATE_SEEDS_ENV, "101,102,110-115")
    payload = _official_payload(repeats=3, seeds=private_seeds)
    monkeypatch.delenv(PRIVATE_SEEDS_ENV)
    report = validate_leaderboard_payload(payload, policy=SOTA_V1_POLICY)
    assert not report.ok
    assert f"{PRIVATE_SEEDS_ENV} is required to validate a private leaderboard seed panel" in report.errors


def test_sota_v1_policy_rejects_seed_panel_hash_mismatch() -> None:
    payload = _official_payload(repeats=3)
    payload["run_info"]["seed_panel"]["sha256"] = "stale"
    report = validate_leaderboard_payload(payload, policy=SOTA_V1_POLICY)
    assert not report.ok
    assert any("seed_panel.sha256" in error for error in report.errors)


def test_redact_leaderboard_payload_removes_private_seed_details(monkeypatch: pytest.MonkeyPatch) -> None:
    private_seeds = [101, 102, 110, 111, 112, 113, 114, 115]
    monkeypatch.setenv(PRIVATE_SEEDS_ENV, "101,102,110-115")
    redacted, report = redact_leaderboard_payload(_official_payload(repeats=3, seeds=private_seeds))

    assert report.ok
    assert redacted["validation_reports"]["sota-v1"]["ok"] is True
    assert redacted["redaction"]["applied"] is True
    assert redacted["seeds"] == REDACTED_SEEDS_SENTINEL
    assert redacted["candidate"]["seeds"] == REDACTED_SEEDS_SENTINEL
    assert redacted["candidate"]["episodes"] == []
    assert redacted["baselines"][0]["episodes"] == []
    assert redacted["paired"]["per_seed"] == []
    assert redacted["run_info"]["seed_panel"]["sha256"]


def test_cli_redact_result_writes_public_safe_artifact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    private_seeds = [101, 102, 110, 111, 112, 113, 114, 115]
    monkeypatch.setenv(PRIVATE_SEEDS_ENV, "101,102,110-115")
    raw_path = tmp_path / "raw.json"
    redacted_path = tmp_path / "redacted.json"
    raw_path.write_text(json.dumps(_official_payload(repeats=3, seeds=private_seeds)))

    cli_module.main(["redact-result", str(raw_path), "--output", str(redacted_path)])

    payload = json.loads(redacted_path.read_text())
    assert payload["seeds"] == REDACTED_SEEDS_SENTINEL
    assert payload["candidate"]["episodes"] == []
    assert payload["validation_reports"]["sota-v1"]["ok"] is True


def test_leaderboard_builder_accepts_redacted_private_artifact(monkeypatch: pytest.MonkeyPatch) -> None:
    private_seeds = [101, 102, 110, 111, 112, 113, 114, 115]
    monkeypatch.setenv(PRIVATE_SEEDS_ENV, "101,102,110-115")
    redacted, _report = redact_leaderboard_payload(_official_payload(repeats=3, seeds=private_seeds))

    row = model_row(redacted)

    assert row["seeds"] is None
    assert row["seed_panel"] == "private-env"
    assert row["sota_v1_eligible"] is True
    assert row["sota_v1_issues"] == []


def test_result_validation_rejects_wrong_seed_panel() -> None:
    payload = _official_payload()
    payload["seeds"] = [1, 2, 3]
    report = validate_leaderboard_payload(payload, policy=PUBLIC_LEADERBOARD_POLICY)
    assert not report.ok
    assert any(error.startswith("seeds must be") for error in report.errors)


def test_cli_validate_result_exits_nonzero_for_sota_policy_failure(tmp_path: Path) -> None:
    path = tmp_path / "result.json"
    path.write_text(json.dumps(_official_payload()))
    with pytest.raises(SystemExit) as excinfo:
        cli_module.main(["validate-result", str(path), "--policy", "sota-v1"])
    assert excinfo.value.code == 1
