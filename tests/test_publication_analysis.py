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
from gm_bench.publication import (
    WITHIN_SEED_MEASURED,
    WITHIN_SEED_UNMEASURED_ONE_REPEAT,
    WITHIN_SEED_UNREPORTED,
    within_seed_stddev_measurement,
)
from scripts.analyze_publication_panel import (
    analyze,
    assign_tiers,
    bootstrap_mean_ci,
    default_output_path,
    holm_adjust,
    per_seed_pick_trader_lifts,
    sign_flip_p_value,
    within_seed_separation_caveats,
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
    assert default_output_path("sota-v4").name == "publication-panel-analysis-v4.json"
    assert default_output_path("sota-v5").name == "publication-panel-analysis-v5.json"


@pytest.mark.parametrize(
    ("target", "expected_error"),
    (
        ("lane", "sota-v5 publication lane is not frozen"),
        ("protocol", "sota-v5 publication protocol is not frozen"),
        ("pricing", "sota-v5 pricing snapshot is not frozen"),
    ),
)
def test_v5_analysis_requires_frozen_configuration(target: str, expected_error: str) -> None:
    registry = {
        "contract": "sota-v5",
        "selection_status": "frozen",
        "publication_authorized": True,
        "preset": "leaderboard",
        "models": [],
    }
    lane = {
        "contract": "sota-v5",
        "preregistration_status": "frozen",
        "publication_authorized": True,
        "seed_panel": {"status": "frozen", "name": "private-env", "count": 16, "sha256": "a" * 64},
    }
    protocol = {
        "contract": "sota-v5",
        "status": "frozen",
        "publication_authorized": True,
        "statistical_analysis_plan": {"status": "frozen"},
    }
    pricing = {"contract": "sota-v5", "status": "frozen", "publication_authorized": True}
    if target == "lane":
        lane["preregistration_status"] = "draft"
    elif target == "protocol":
        protocol["status"] = "draft"
    else:
        pricing["status"] = "draft"

    result = analyze(registry, [], lane=lane, protocol=protocol, pricing=pricing)

    assert result["publication_ready"] is False
    assert expected_error in result["config_errors"]


def test_v4_analysis_dispatch_is_explicitly_authorization_locked() -> None:
    registry = {
        "contract": "sota-v4",
        "selection_status": "frozen",
        "preset": "leaderboard",
        "models": [],
    }
    lane = {
        "contract": "sota-v4",
        "seed_panel": {"status": "frozen", "name": "private-env", "count": 16, "sha256": "a" * 64},
    }
    protocol = {"contract": "sota-v4", "statistical_analysis_plan": {"status": "frozen"}}

    result = analyze(registry, [], lane=lane, protocol=protocol)

    assert result["benchmark_version"] == "sota-v4"
    assert result["publication_ready"] is False
    assert any("sota-v4 analysis is authorization-locked" in issue for issue in result["config_errors"])


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


def _noise_rows(*pairs: tuple[str, float | None]) -> list[dict]:
    return [{"model_id": model_id, "within_seed_score_stddev": stddev} for model_id, stddev in pairs]


def test_quiet_rows_support_separation_claims() -> None:
    caveat = within_seed_separation_caveats(_noise_rows(("a", 12.0), ("b", 25.0), ("c", 0.0)))

    assert caveat["separation_claims_supported"] is True
    assert caveat["models_exceeding_threshold"] == []
    assert caveat["unclaimable_separation_pairs"] == []
    assert caveat["threshold"] == 25.0


def test_a_noisy_row_blocks_only_the_pairs_it_is_in() -> None:
    caveat = within_seed_separation_caveats(_noise_rows(("a", 12.0), ("b", 41.5), ("c", 3.0)))

    assert caveat["separation_claims_supported"] is False
    assert caveat["models_exceeding_threshold"] == [{"model_id": "b", "within_seed_score_stddev": 41.5}]
    # Every pair containing b is unclaimable; a-versus-c is untouched.
    assert caveat["unclaimable_separation_pairs"] == [["a", "b"], ["b", "c"]]


def test_an_unmeasured_spread_cannot_clear_the_bound() -> None:
    caveat = within_seed_separation_caveats(_noise_rows(("a", 5.0), ("b", None)))

    assert caveat["models_missing_the_statistic"] == ["b"]
    assert caveat["unclaimable_separation_pairs"] == [["a", "b"]]
    assert caveat["separation_claims_supported"] is False


def test_the_threshold_follows_the_frozen_analysis_plan() -> None:
    rows = _noise_rows(("a", 30.0))

    assert within_seed_separation_caveats(rows, threshold=40.0)["models_exceeding_threshold"] == []
    assert within_seed_separation_caveats(rows, threshold=20.0)["models_exceeding_threshold"] == [
        {"model_id": "a", "within_seed_score_stddev": 30.0}
    ]


def test_analysis_publishes_a_noisy_row_and_caveats_its_tier(monkeypatch: pytest.MonkeyPatch) -> None:
    """A noisy row is a reported caveat, never a withheld row."""
    monkeypatch.setattr(
        publication_analysis,
        "validate_leaderboard_payload",
        lambda payload, policy: SimpleNamespace(ok=True, errors=[]),
    )
    payload = _registered_payload(seed_count=6)
    payload["candidate"]["summary"]["within_seed_score_stddev"] = 56.7

    result = analyze(_frozen_registry(), [payload])

    assert result["status"] == "complete"
    assert result["eligible_model_count"] == 1
    assert result["models"][0]["within_seed_score_stddev"] == 56.7
    assert result["models"][0]["tier"] == 1
    noise = result["within_seed_noise"]
    assert noise["separation_claims_supported"] is False
    assert noise["models_exceeding_threshold"] == [{"model_id": "demo", "within_seed_score_stddev": 56.7}]
    # The tiers are the only separation claim this analyzer makes, so the
    # caveat has to travel with them.
    assert result["model_tiering"]["status"] == "supported-with-within-seed-caveat"
    assert result["model_tiering"]["within_seed_noise_caveat"] is noise


def test_analysis_reports_a_quiet_panel_as_separable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        publication_analysis,
        "validate_leaderboard_payload",
        lambda payload, policy: SimpleNamespace(ok=True, errors=[]),
    )
    payload = _registered_payload(seed_count=6)
    payload["candidate"]["summary"]["within_seed_score_stddev"] = 4.2

    result = analyze(_frozen_registry(), [payload])

    assert result["within_seed_noise"]["separation_claims_supported"] is True
    assert result["model_tiering"]["status"] == "supported"


def test_the_v5_analysis_plan_carries_the_within_seed_threshold() -> None:
    protocol = json.loads((Path("config") / "sota_v5_publication_protocol.json").read_text())
    caveat = protocol["statistical_analysis_plan"]["within_seed_noise_caveat"]

    assert caveat["statistic"] == "within_seed_score_stddev"
    assert caveat["threshold"] == publication_analysis.WITHIN_SEED_SEPARATION_THRESHOLD == 25.0
    assert "within_seed_score_stddev" in protocol["statistical_analysis_plan"]["required_outputs"]


def test_a_one_repeat_row_reads_as_unmeasured_rather_than_zero() -> None:
    """The runner writes 0.0 when nothing repeated; that is an absence, not a spread."""
    payload = {"candidate": {"repeats": 1, "summary": {"within_seed_score_stddev": 0.0}}}

    assert within_seed_stddev_measurement(payload) == (None, WITHIN_SEED_UNMEASURED_ONE_REPEAT)


def test_a_repeated_row_reads_as_measured() -> None:
    payload = {"candidate": {"repeats": 3, "summary": {"within_seed_score_stddev": 18.4}}}

    assert within_seed_stddev_measurement(payload) == (18.4, WITHIN_SEED_MEASURED)


def test_one_repeat_is_read_from_episodes_when_repeats_is_absent() -> None:
    payload = {
        "candidate": {
            "episodes": [{"seed": 11, "final_score": 1.0}, {"seed": 12, "final_score": 2.0}],
            "summary": {"within_seed_score_stddev": 0.0},
        }
    }

    assert within_seed_stddev_measurement(payload) == (None, WITHIN_SEED_UNMEASURED_ONE_REPEAT)


def test_a_row_that_never_carried_the_field_reads_as_unreported() -> None:
    payload = {"candidate": {"repeats": 3, "summary": {}}}

    assert within_seed_stddev_measurement(payload) == (None, WITHIN_SEED_UNREPORTED)


def test_unmeasured_one_repeat_rows_stay_claimable_under_the_assumed_repeat_noise() -> None:
    """The MDD table already prices repeat noise by assumption, so name the assumption."""
    rows = [
        {"model_id": "a", "within_seed_score_stddev": 12.0, "within_seed_score_stddev_status": WITHIN_SEED_MEASURED},
        {
            "model_id": "b",
            "within_seed_score_stddev": None,
            "within_seed_score_stddev_status": WITHIN_SEED_UNMEASURED_ONE_REPEAT,
        },
    ]

    caveat = within_seed_separation_caveats(rows)

    assert caveat["models_with_unmeasured_within_seed_noise"] == ["b"]
    assert caveat["models_missing_the_statistic"] == []
    assert caveat["unclaimable_separation_pairs"] == []
    assert caveat["separation_claims_supported"] is True
    assert caveat["separation_claims_rest_on_assumed_repeat_noise"] is True
    assert "assumed repeat noise" in caveat["unmeasured_basis"]


def test_an_unreported_row_still_blocks_its_pairs_when_others_are_unmeasured() -> None:
    """Unmeasured-by-lane is covered by an assumption; unreported is covered by nothing."""
    rows = [
        {
            "model_id": "a",
            "within_seed_score_stddev": None,
            "within_seed_score_stddev_status": WITHIN_SEED_UNMEASURED_ONE_REPEAT,
        },
        {"model_id": "b", "within_seed_score_stddev": None, "within_seed_score_stddev_status": WITHIN_SEED_UNREPORTED},
    ]

    caveat = within_seed_separation_caveats(rows)

    assert caveat["models_missing_the_statistic"] == ["b"]
    assert caveat["unclaimable_separation_pairs"] == [["a", "b"]]
    assert caveat["separation_claims_supported"] is False


def test_analysis_marks_a_one_repeat_panel_row_unmeasured_instead_of_quiet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End to end: a `repeats: 1` lane must not publish sixteen trivially clean rows."""
    monkeypatch.setattr(
        publication_analysis,
        "validate_leaderboard_payload",
        lambda payload, policy: SimpleNamespace(ok=True, errors=[]),
    )
    seeds = list(range(11, 17))
    payload = _payload({seed: [float(seed)] for seed in seeds}, {seed: float(seed - 1) for seed in seeds})
    payload["candidate"]["repeats"] = 1
    payload["run_info"].update(_registered_payload(seed_count=6)["run_info"])
    payload["candidate"]["summary"] = {
        "decisions": 6,
        "usage": {"cost_decisions": 6, "upstream_providers": ["DemoProvider"]},
        # What the runner actually writes for a one-repeat lane.
        "within_seed_score_stddev": 0.0,
    }
    registry = {**_frozen_registry(), "repeats": 1}

    result = analyze(registry, [payload])

    assert result["status"] == "complete"
    row = result["models"][0]
    assert row["within_seed_score_stddev"] is None
    assert row["within_seed_score_stddev_status"] == WITHIN_SEED_UNMEASURED_ONE_REPEAT
    noise = result["within_seed_noise"]
    assert noise["models_with_unmeasured_within_seed_noise"] == ["demo"]
    assert noise["models_exceeding_threshold"] == []
    assert noise["separation_claims_supported"] is True
    assert noise["separation_claims_rest_on_assumed_repeat_noise"] is True
    assert result["model_tiering"]["status"] == "supported-under-assumed-repeat-noise"


def test_the_v5_plan_records_the_one_repeat_claimability_decision() -> None:
    lane = json.loads((Path("config") / "sota_v5_lane.json").read_text())
    protocol = json.loads((Path("config") / "sota_v5_publication_protocol.json").read_text())
    caveat = protocol["statistical_analysis_plan"]["within_seed_noise_caveat"]

    # The rule text has to match the lane it runs under.
    assert lane["repeats"] == 1
    assert caveat["measurable_under_this_lane"] is False
    assert caveat["unmeasured_status"] == WITHIN_SEED_UNMEASURED_ONE_REPEAT
    assert caveat["unmeasured_claimability"] == "claimable-with-explicit-assumption-caveat"
    assert caveat["unmeasured_basis"] == publication_analysis.WITHIN_SEED_ONE_REPEAT_BASIS
