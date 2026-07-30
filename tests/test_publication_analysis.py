from __future__ import annotations

import itertools
import json
import random
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
    default_output_path,
    holm_adjust,
    per_seed_pick_trader_lifts,
    sign_flip_p_value,
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


def test_default_analysis_outputs_are_contract_versioned() -> None:
    assert default_output_path("sota-v2").name == "publication-panel-analysis.json"
    assert default_output_path("sota-v3").name == "publication-panel-analysis-v3.json"


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


def _exhaustive_sign_flip_p_value(values: list[float]) -> float:
    observed = abs(sum(values) / len(values))
    hits = sum(
        abs(sum(sign * value for sign, value in zip(signs, values, strict=True)) / len(values)) >= observed - 1e-12
        for signs in itertools.product((-1, 1), repeat=len(values))
    )
    return hits / 2 ** len(values)


def test_optimized_exact_sign_flip_matches_exhaustive_enumeration() -> None:
    values = [-3.5, 1.25, 2.0, 4.75, 8.0, 9.5]

    assert sign_flip_p_value(values) == pytest.approx(_exhaustive_sign_flip_p_value(values))


@pytest.mark.parametrize(
    "values",
    [
        [4.0, -4.0],  # zero observed sum
        [0.0, 0.0],  # every assignment is tied at zero
        [1.0, 1.0],  # boundary ties at the observed statistic
        [1.0, -1.0, 2.0, -2.0],
        [3.0, 3.0, 3.0, 3.0],
    ],
)
def test_optimized_exact_sign_flip_handles_zero_and_boundary_ties(values: list[float]) -> None:
    assert sign_flip_p_value(values) == pytest.approx(_exhaustive_sign_flip_p_value(values))
    assert 0.0 <= sign_flip_p_value(values) <= 1.0


def test_optimized_exact_sign_flip_matches_deterministic_integer_fuzz() -> None:
    rng = random.Random(20260728)
    for size in range(2, 11):
        for _case in range(40):
            values = [float(rng.randint(-8, 8)) for _ in range(size)]
            assert sign_flip_p_value(values) == pytest.approx(_exhaustive_sign_flip_p_value(values))


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


def _registered_payload(*, seed_count: int = 2) -> dict:
    seeds = list(range(11, 11 + seed_count))
    payload = _payload(
        {seed: [float(seed), float(seed + 1), float(seed + 2)] for seed in seeds},
        {seed: float(seed - 1) for seed in seeds},
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
    payload["candidate"]["summary"] = {
        "decisions": seed_count * 3,
        "usage": {"cost_decisions": seed_count * 3, "upstream_providers": ["DemoProvider"]},
    }
    return payload


def _frozen_v3_analysis_inputs(payload: dict) -> tuple[dict, dict]:
    fingerprint = "f" * 16
    payload["run_info"]["benchmark_contract"]["contract_fingerprint"] = fingerprint
    seed_count = len({episode["seed"] for episode in payload["candidate"]["episodes"]})
    seed_panel = {
        "name": "private-env",
        "count": seed_count,
        "sha256": "b" * 64,
        "hiding_commitment_sha256": "c" * 64,
        "preset": "leaderboard",
    }
    payload["run_info"]["seed_panel"] = dict(seed_panel)
    lane = {
        "contract": "sota-v3",
        "contract_fingerprint": fingerprint,
        "reference_agent": "pick-trader",
        "seed_panel": {"status": "frozen", **seed_panel},
    }
    protocol = {
        "contract": "sota-v3",
        "contract_fingerprint": fingerprint,
        "statistical_analysis_plan": {
            "status": "frozen",
            "unit_of_inference": "seed",
            "primary_contrast": "paired lift versus pick-trader",
            "reference_agent": "pick-trader",
            "multiplicity_method": "holm-bonferroni",
            "alpha": 0.05,
            "analysis_mode": "reference-only",
            "inference_method": "exact-enumeration-sign-flip",
            "holm_family_size": 1,
        },
    }
    return lane, protocol


def test_analysis_rejects_artifact_from_unregistered_route(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        publication_analysis,
        "validate_leaderboard_payload",
        lambda payload, policy: SimpleNamespace(ok=True, errors=[]),
    )
    payload = _registered_payload(seed_count=6)
    payload["run_info"]["provider_options"]["OPENROUTER_PROVIDER_ONLY"] = "WrongProvider"

    result = analyze(_frozen_registry(), [payload])

    assert result["status"] == "no-eligible-artifacts"
    assert result["eligible_model_count"] == 0
    assert any("OPENROUTER_PROVIDER_ONLY" in reason for reason in result["rejected_artifacts"][0]["reasons"])


def test_analysis_rejects_incomplete_cost_telemetry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        publication_analysis,
        "validate_leaderboard_payload",
        lambda payload, policy: SimpleNamespace(ok=True, errors=[]),
    )
    payload = _registered_payload(seed_count=6)
    payload["candidate"]["summary"]["usage"]["cost_decisions"] = 5

    result = analyze(_frozen_registry(), [payload])

    assert result["eligible_model_count"] == 0
    assert "candidate cost telemetry must cover every decision point" in result["rejected_artifacts"][0]["reasons"]


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
    assert result["models"][0]["tier"] == 1
    assert "analysis_mode" not in result
    assert len(result["models"][0]["artifact_sha256"]) == 64
    assert result["models"][0]["raw_artifact_sha256"] == "a" * 64


def test_v3_reference_only_analysis_does_not_assign_model_tiers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        publication_analysis,
        "validate_leaderboard_payload",
        lambda payload, policy: SimpleNamespace(ok=True, errors=[]),
    )
    registry = _frozen_registry()
    registry["contract"] = "sota-v3"
    registry["contract_fingerprint"] = "f" * 16
    payload = _registered_payload(seed_count=6)
    payload["run_info"]["benchmark_contract"]["benchmark_version"] = "sota-v3"
    lane, protocol = _frozen_v3_analysis_inputs(payload)

    result = analyze(registry, [payload], lane=lane, protocol=protocol)

    assert result["status"] == "complete"
    assert result["analysis_mode"] == "reference-only"
    assert result["publication_ready"] is True
    assert result["model_tiering"]["status"] == "not-supported"
    assert result["sign_flip_inference"] == "primary; exact under the symmetry assumption"
    assert "tier" not in result["models"][0]
    assert "per_seed" not in result["models"][0]
    assert result["models"][0]["seed_count"] == 6
    assert result["redaction"] == {
        "private_seed_panel": True,
        "seed_identifiers_included": False,
        "per_seed_rows_included": False,
        "public_view": "aggregate-only",
    }
    rendered = json.dumps(result, sort_keys=True)
    assert '"per_seed"' not in rendered
    for private_seed in range(11, 17):
        assert f'"seed": {private_seed}' not in rendered


def test_v3_analysis_missing_frozen_inputs_yields_no_publishable_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        publication_analysis,
        "validate_leaderboard_payload",
        lambda payload, policy: SimpleNamespace(ok=True, errors=[]),
    )
    registry = _frozen_registry()
    registry.update({"contract": "sota-v3", "contract_fingerprint": "f" * 16})
    payload = _registered_payload(seed_count=6)
    payload["run_info"]["benchmark_contract"]["benchmark_version"] = "sota-v3"

    result = analyze(registry, [payload])

    assert result["eligible_model_count"] == 0
    assert result["publication_ready"] is False
    assert result["config_errors"]


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("analysis_mode", "pairwise-tiers", "analysis mode"),
        ("inference_method", "deterministic-monte-carlo-sign-flip", "inference_method"),
        ("holm_family_size", 2, "Holm family size"),
        ("unit_of_inference", "episode", "unit_of_inference"),
    ],
)
def test_v3_analysis_rejects_frozen_stat_plan_mutation(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
    expected: str,
) -> None:
    monkeypatch.setattr(
        publication_analysis,
        "validate_leaderboard_payload",
        lambda payload, policy: SimpleNamespace(ok=True, errors=[]),
    )
    registry = _frozen_registry()
    registry.update({"contract": "sota-v3", "contract_fingerprint": "f" * 16})
    payload = _registered_payload(seed_count=6)
    payload["run_info"]["benchmark_contract"]["benchmark_version"] = "sota-v3"
    lane, protocol = _frozen_v3_analysis_inputs(payload)
    protocol["statistical_analysis_plan"][field] = value

    result = analyze(registry, [payload], lane=lane, protocol=protocol)

    assert result["eligible_model_count"] == 0
    assert result["publication_ready"] is False
    assert any(expected in error for error in result["config_errors"])


def test_v3_analysis_rejects_contract_fingerprint_mismatch_and_infeasible_exact_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        publication_analysis,
        "validate_leaderboard_payload",
        lambda payload, policy: SimpleNamespace(ok=True, errors=[]),
    )
    registry = _frozen_registry()
    registry.update({"contract": "sota-v3", "contract_fingerprint": "wrong"})
    payload = _registered_payload(seed_count=6)
    payload["run_info"]["benchmark_contract"]["benchmark_version"] = "sota-v3"
    lane, protocol = _frozen_v3_analysis_inputs(payload)

    mismatch = analyze(registry, [payload], lane=lane, protocol=protocol)
    assert mismatch["publication_ready"] is False
    assert mismatch["eligible_model_count"] == 0
    assert any("contract_fingerprint" in error for error in mismatch["config_errors"])

    registry["contract_fingerprint"] = "f" * 16
    lane["seed_panel"]["count"] = 5
    payload["run_info"]["seed_panel"]["count"] = 5
    infeasible = analyze(registry, [payload], lane=lane, protocol=protocol)
    assert infeasible["publication_ready"] is False
    assert infeasible["eligible_model_count"] == 0
    assert any("cannot clear Holm step one" in error for error in infeasible["config_errors"])


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", "public-leaderboard"),
        ("count", 7),
        ("sha256", "c" * 64),
    ],
)
def test_v3_analysis_rejects_artifact_seed_panel_identity_mutation(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    monkeypatch.setattr(
        publication_analysis,
        "validate_leaderboard_payload",
        lambda payload, policy: SimpleNamespace(ok=True, errors=[]),
    )
    registry = _frozen_registry()
    registry["contract"] = "sota-v3"
    registry["contract_fingerprint"] = "f" * 16
    payload = _registered_payload(seed_count=6)
    payload["run_info"]["benchmark_contract"]["benchmark_version"] = "sota-v3"
    lane, protocol = _frozen_v3_analysis_inputs(payload)
    payload["run_info"]["seed_panel"][field] = value

    result = analyze(registry, [payload], lane=lane, protocol=protocol)

    assert result["status"] == "no-eligible-artifacts"
    assert result["publication_ready"] is False
    assert f"run_info.seed_panel.{field} does not match" in result["rejected_artifacts"][0]["reasons"][0]


def test_analysis_rejects_compact_publication_block_without_raw_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        publication_analysis,
        "validate_leaderboard_payload",
        lambda payload, policy: SimpleNamespace(ok=True, errors=[]),
    )
    payload = _registered_payload()
    payload["publication"] = {}

    result = analyze(_frozen_registry(), [payload])

    assert result["status"] == "no-eligible-artifacts"
    assert any("raw_artifact_sha256" in reason for reason in result["rejected_artifacts"][0]["reasons"])


def test_analysis_accepts_genuinely_raw_artifact_without_publication_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        publication_analysis,
        "validate_leaderboard_payload",
        lambda payload, policy: SimpleNamespace(ok=True, errors=[]),
    )
    result = analyze(_frozen_registry(), [_registered_payload()])

    assert result["status"] == "complete"


def test_v3_cli_returns_nonzero_for_current_provisional_configuration(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/analyze_publication_panel.py",
            "--contract",
            "sota-v3",
            "--artifacts-dir",
            str(tmp_path),
            "--output",
            str(tmp_path / "analysis.json"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    result = json.loads(completed.stdout)
    assert result["publication_ready"] is False
    assert not (tmp_path / "analysis.json").exists()


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
