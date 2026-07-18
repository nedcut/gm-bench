from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.analyze_publication_panel as publication_analysis
from scripts.analyze_publication_panel import (
    analyze,
    assign_tiers,
    bootstrap_mean_ci,
    holm_adjust,
    per_seed_pick_trader_lifts,
)


def _payload(candidate_scores: dict[int, list[float]], pick_trader_scores: dict[int, float]) -> dict:
    episodes = [
        {"seed": seed, "repeat": repeat, "seasons": 5, "final_score": score}
        for seed, scores in candidate_scores.items()
        for repeat, score in enumerate(scores, start=1)
    ]
    baseline_episodes = [
        {"seed": seed, "seasons": 5, "final_score": score} for seed, score in pick_trader_scores.items()
    ]
    return {
        "run_info": {"provider": "openrouter", "model": "demo/model"},
        "candidate": {"repeats": 3, "episodes": episodes},
        "baselines": [{"agent": "pick-trader", "episodes": baseline_episodes}],
    }


def _tier_row(model_id: str, mean_lift: float, interval: tuple[float, float]) -> dict:
    return {
        "model_id": model_id,
        "mean_lift": mean_lift,
        "bootstrap_ci95": list(interval),
        "holm_adjusted_p_value": 0.5,
    }


def test_pick_trader_differencing_averages_repeats_within_seed() -> None:
    payload = _payload(
        {11: [10.0, 13.0, 16.0], 12: [17.0, 20.0, 23.0]},
        {11: 11.0, 12: 25.0},
    )

    assert per_seed_pick_trader_lifts(payload) == [
        {
            "seed": 11,
            "candidate_mean_over_repeats": 13.0,
            "pick_trader_score": 11.0,
            "lift": 2.0,
        },
        {
            "seed": 12,
            "candidate_mean_over_repeats": 20.0,
            "pick_trader_score": 25.0,
            "lift": -5.0,
        },
    ]


def test_holm_adjustment_preserves_sorted_step_down_order() -> None:
    adjusted = holm_adjust({"small": 0.01, "large": 0.04, "middle": 0.03}, family_size=3)

    assert adjusted == {"small": 0.03, "middle": 0.06, "large": 0.06}
    assert adjusted["small"] <= adjusted["middle"] <= adjusted["large"]


def test_tiers_merge_transitively_when_intervals_overlap() -> None:
    rows = [
        _tier_row("a", 10.0, (8.0, 12.0)),
        _tier_row("b", 7.0, (6.0, 9.0)),
        _tier_row("c", 5.0, (4.0, 6.5)),
    ]

    tiered = assign_tiers(rows)

    assert [row["model_id"] for row in tiered] == ["a", "b", "c"]
    assert [row["tier"] for row in tiered] == [1, 1, 1]


def test_tiers_split_when_intervals_are_disjoint() -> None:
    rows = [
        _tier_row("a", 10.0, (9.0, 11.0)),
        _tier_row("b", 5.0, (4.0, 6.0)),
        _tier_row("c", 0.0, (-1.0, 1.0)),
    ]

    assert [row["tier"] for row in assign_tiers(rows)] == [1, 2, 3]


def test_bootstrap_interval_is_deterministic() -> None:
    values = [-4.0, -1.0, 2.0, 8.0, 10.0, 11.0, 15.0, 21.0]

    first = bootstrap_mean_ci(values)
    second = bootstrap_mean_ci(values)

    assert first == second
    assert first[0] < first[1]


def test_zero_artifact_path_reports_cleanly_without_writing_output(tmp_path: Path) -> None:
    output = tmp_path / "publication-panel-analysis.json"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/analyze_publication_panel.py",
            "--artifacts-dir",
            str(tmp_path),
            "--output",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    result = json.loads(completed.stdout)
    assert result["status"] == "no-eligible-artifacts"
    assert result["eligible_model_count"] == 0
    assert len(result["missing_models"]) == result["registered_model_count"] == 10
    assert not output.exists()


def _frozen_registry() -> dict:
    return {
        "selection_status": "frozen",
        "contract": "sota-v2",
        "preset": "leaderboard",
        "profile": "compact",
        "repeats": 3,
        "output_token_cap": 1024,
        "shared_fixed_options": {"OPENROUTER_REASONING_ENABLED": "false"},
        "shared_absent_options": ["OPENROUTER_TEMPERATURE"],
        "models": [
            {
                "id": "demo",
                "provider": "openrouter",
                "model": "demo/model",
                "transport": "gateway-api",
                "upstream_provider": "DemoProvider",
                "upstream_provider_slug": "demo-provider/fp8",
                "endpoint_tag": "demo-provider/fp8",
                "endpoint_name": "DemoProvider | demo/model-20260716",
                "fixed_options": {"OPENROUTER_REASONING_ENABLED": "false"},
                "absent_options": [],
            }
        ],
    }


def _registered_payload() -> dict:
    payload = _payload(
        {11: [10.0, 11.0, 12.0], 12: [20.0, 21.0, 22.0]},
        {11: 9.0, 12: 19.0},
    )
    payload["run_info"].update(
        {
            "transport": "gateway-api",
            "profile": "compact",
            "preset": "leaderboard",
            "benchmark_contract": {"benchmark_version": "sota-v2"},
            "provider_options": {
                "OPENROUTER_REASONING_ENABLED": "false",
                "OPENROUTER_PROVIDER_ONLY": "demo-provider/fp8",
                "OPENROUTER_EXPECTED_UPSTREAM_PROVIDER": "DemoProvider",
                "OPENROUTER_EXPECTED_ENDPOINT_NAME": "DemoProvider | demo/model-20260716",
                "OPENROUTER_MAX_TOKENS": "1024",
                "GM_BENCH_OUTPUT_BUDGET_CELL": "1024",
            },
        }
    )
    payload["candidate"]["summary"] = {"usage": {"upstream_providers": ["DemoProvider"]}}
    return payload


def test_analysis_rejects_artifact_from_unregistered_route(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        publication_analysis,
        "validate_leaderboard_payload",
        lambda payload, policy: SimpleNamespace(ok=True, errors=[]),
    )
    payload = _registered_payload()
    payload["run_info"]["provider_options"]["OPENROUTER_PROVIDER_ONLY"] = "WrongProvider"

    result = analyze(_frozen_registry(), [payload])

    assert result["status"] == "no-eligible-artifacts"
    assert result["eligible_model_count"] == 0
    assert any("OPENROUTER_PROVIDER_ONLY" in reason for reason in result["rejected_artifacts"][0]["reasons"])


def test_analysis_binds_eligible_row_to_raw_artifact_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        publication_analysis,
        "validate_leaderboard_payload",
        lambda payload, policy: SimpleNamespace(ok=True, errors=[]),
    )
    payload = _registered_payload()
    payload["publication"] = {"raw_artifact_sha256": "a" * 64}

    result = analyze(_frozen_registry(), [payload])

    assert result["status"] == "complete"
    assert len(result["models"][0]["artifact_sha256"]) == 64
    assert result["models"][0]["raw_artifact_sha256"] == "a" * 64


def test_analysis_rejects_invalid_raw_artifact_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        publication_analysis,
        "validate_leaderboard_payload",
        lambda payload, policy: SimpleNamespace(ok=True, errors=[]),
    )
    payload = _registered_payload()
    payload["publication"] = {"raw_artifact_sha256": "not-a-hash"}

    result = analyze(_frozen_registry(), [payload])

    assert result["status"] == "no-eligible-artifacts"
    assert any("raw_artifact_sha256" in reason for reason in result["rejected_artifacts"][0]["reasons"])
