from __future__ import annotations

import json
from pathlib import Path

import pytest

from gm_bench import cli as cli_module
from gm_bench.benchmark_config import PRESETS, PRIVATE_SEEDS_ENV, seed_panel_metadata
from gm_bench.contract import benchmark_contract, scaffold_fingerprint
from gm_bench.official import (
    ARCHIVE_V1_POLICY,
    OUTPUT_BUDGET_SWEEP_POLICY,
    PUBLIC_LEADERBOARD_POLICY,
    REDACTED_SEEDS_SENTINEL,
    SOTA_V1_CONTRACT,
    SOTA_V1_POLICY,
    SOTA_V2_POLICY,
    redact_leaderboard_payload,
    validate_leaderboard_payload,
)
from gm_bench.publication import compact_result
from scripts.analyze_output_budget import analyze
from web.scripts.build_leaderboard import model_row


def _official_payload(*, repeats: int = 1, failure_rate: float = 0.0, seeds: list[int] | None = None) -> dict:
    leaderboard = PRESETS["leaderboard"]
    seeds = list(seeds or leaderboard["seeds"])
    seasons = int(leaderboard["seasons"])
    # Default episode is 4 phases (incl. midseason).
    decisions = len(seeds) * repeats * seasons * 4
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
                    "final_score": 300.0 if name == "pick-trader" else 100.0,
                    "strategy_score": 300.0 if name == "pick-trader" else 100.0,
                    "protocol_penalty": 0.0,
                    "wins": 90,
                    "championships": 1,
                    "illegal_actions": 0,
                }
                for seed in seeds
            ],
            "summary": {
                "mean_score": 300.0 if name == "pick-trader" else 100.0,
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
            "baseline_panel_mean_score": 125.0,
            "score_lift": 225.0,
        },
        "paired": {
            "num_seeds": len(seeds),
            "per_seed": [],
            "paired_lift_mean": 225.0,
            "paired_lift_ci95": [200.0, 230.0],
            "sign_flip_p_value": 0.0078,
            "significant_at_95": True,
            "candidate_seed_win_rate": 1.0,
            "best_baseline": {
                "agent": "pick-trader",
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
            "scaffold_fingerprint": scaffold_fingerprint("openai"),
            "seed_panel": seed_panel_metadata(seeds, "leaderboard"),
            "protocol_repair_attempts": 1,
            "provider_options": {"GM_BENCH_PROTOCOL_REPAIR_ATTEMPTS": "1"},
        },
    }


def test_public_leaderboard_policy_accepts_single_repeat_payload() -> None:
    report = validate_leaderboard_payload(_official_payload(), policy=PUBLIC_LEADERBOARD_POLICY)
    assert report.ok


def test_compact_artifact_rejects_tampered_episode_and_aggregate() -> None:
    payload = compact_result(_official_payload(repeats=3))
    payload["candidate"]["episodes"][0]["final_score"] = 9999.0
    payload["candidate"]["summary"]["mean_score"] = 9999.0
    payload["normalized"]["candidate_mean_score"] = 9999.0
    report = validate_leaderboard_payload(payload, policy=SOTA_V2_POLICY)
    assert not report.ok
    assert any("episode-derived" in error for error in report.errors)


def test_output_budget_policy_preserves_high_failure_cells() -> None:
    payload = _official_payload(repeats=3, failure_rate=1.0)
    report = validate_leaderboard_payload(payload, policy=OUTPUT_BUDGET_SWEEP_POLICY)
    assert report.ok
    assert any("adapter fallback" in warning for warning in report.warnings)


def test_historical_baseline_panel_is_diagnostic_but_not_sota() -> None:
    payload = _official_payload(repeats=3)
    payload["baselines"] = [
        baseline for baseline in payload["baselines"] if baseline["agent"] not in {"strategic", "pick-trader"}
    ]
    payload["paired"]["best_baseline"]["agent"] = "shrewd"

    public_report = validate_leaderboard_payload(payload, policy=PUBLIC_LEADERBOARD_POLICY)
    assert public_report.ok
    assert "historical baseline panel differs from the current official panel" in public_report.warnings

    sota_report = validate_leaderboard_payload(payload, policy=SOTA_V2_POLICY)
    assert not sota_report.ok
    assert any(error.startswith("baselines must be") for error in sota_report.errors)


def test_sota_v2_policy_requires_repeats() -> None:
    report = validate_leaderboard_payload(_official_payload(repeats=1), policy=SOTA_V2_POLICY)
    assert not report.ok
    assert "candidate.repeats must be >= 3 for sota-v2" in report.errors


def test_sota_v2_policy_rejects_high_failure_rate() -> None:
    report = validate_leaderboard_payload(_official_payload(repeats=3, failure_rate=0.05), policy=SOTA_V2_POLICY)
    assert not report.ok
    assert any("decision_failure_rate" in error for error in report.errors)


def test_sota_v2_policy_rejects_runaway_failed_queries() -> None:
    # The v1 scout-contract break produced 1,124 silently-rejected lookups across
    # 480 decisions (2.34/decision) while reporting a clean summary. That row must
    # not be publishable again.
    payload = _official_payload(repeats=3)
    decisions = int(payload["candidate"]["summary"]["decisions"])
    payload["candidate"]["summary"]["failed_queries"] = decisions * 2 + 1
    report = validate_leaderboard_payload(payload, policy=SOTA_V2_POLICY)
    assert not report.ok
    assert any("failed queries" in error for error in report.errors)


def test_failed_queries_warn_below_the_hard_gate() -> None:
    payload = _official_payload(repeats=3)
    decisions = int(payload["candidate"]["summary"]["decisions"])
    payload["candidate"]["summary"]["failed_queries"] = int(decisions * 0.5)
    report = validate_leaderboard_payload(payload, policy=SOTA_V2_POLICY)
    assert report.ok
    assert any("failed queries" in warning for warning in report.warnings)

    # A handful of misfired lookups is normal exploration, not a signal.
    payload["candidate"]["summary"]["failed_queries"] = int(decisions * 0.1)
    quiet = validate_leaderboard_payload(payload, policy=SOTA_V2_POLICY)
    assert quiet.ok
    assert not any("failed queries" in warning for warning in quiet.warnings)


def test_archive_v1_policy_asserts_provenance_not_eligibility() -> None:
    # `archive-v1` exists to prove an artifact is a genuine v1 artifact. It must
    # accept rows that never cleared the strict sota-v1 bar -- two real archived
    # rows (ollama-gemma4-e4b, ollama-qwen3-5-latest) did not -- because the
    # archive preserves evidence rather than endorsing it.
    payload = _official_payload(repeats=3, failure_rate=0.05)
    payload["run_info"]["benchmark_contract"] = dict(SOTA_V1_CONTRACT)

    lenient = validate_leaderboard_payload(payload, policy=ARCHIVE_V1_POLICY)
    assert lenient.ok, lenient.errors

    strict = validate_leaderboard_payload(payload, policy=SOTA_V1_POLICY)
    assert not strict.ok
    assert any("decision_failure_rate" in error for error in strict.errors)


def test_archive_v1_policy_rejects_a_non_v1_artifact() -> None:
    # The archive must not silently drift onto a newer contract.
    payload = _official_payload(repeats=3)  # carries the current (v2) contract
    report = validate_leaderboard_payload(payload, policy=ARCHIVE_V1_POLICY)
    assert not report.ok
    assert any("contract" in error.lower() for error in report.errors)


def test_sota_v2_policy_requires_full_usage() -> None:
    payload = _official_payload(repeats=3)
    payload["candidate"]["summary"]["usage"]["decisions_with_usage"] = 0
    report = validate_leaderboard_payload(payload, policy=SOTA_V2_POLICY)
    assert not report.ok
    assert "candidate usage must cover every decision point" in report.errors

    payload = _official_payload(repeats=3)
    payload["candidate"]["summary"]["usage"]["cost_usd"] = "missing"
    report = validate_leaderboard_payload(payload, policy=SOTA_V2_POLICY)
    assert not report.ok
    assert "candidate usage.cost_usd is required, use null only when pricing is unknown" in report.errors


@pytest.mark.parametrize(
    ("run_value", "option_value"),
    [(None, "1"), (1, None), (-1, "-1"), (2, "2"), (0, "1"), ("bad", "1")],
)
def test_sota_v2_requires_matching_bounded_repair_provenance(run_value: object, option_value: object) -> None:
    payload = _official_payload(repeats=3)
    payload["run_info"]["protocol_repair_attempts"] = run_value
    payload["run_info"]["provider_options"]["GM_BENCH_PROTOCOL_REPAIR_ATTEMPTS"] = option_value
    report = validate_leaderboard_payload(payload, policy=SOTA_V2_POLICY)
    assert not report.ok
    assert any("repair" in error for error in report.errors)


def test_output_budget_analysis_rejects_duplicate_cells() -> None:
    payload = _official_payload(repeats=3)
    payload["run_info"]["profile"] = "compact"
    payload["run_info"]["transport"] = "direct-api"
    payload["run_info"]["provider_options"] = {
        "OPENAI_MAX_TOKENS": "256",
        "GM_BENCH_OUTPUT_BUDGET_CELL": "256",
        "GM_BENCH_PROTOCOL_REPAIR_ATTEMPTS": "1",
    }
    usage = payload["candidate"]["summary"]["usage"]
    usage.update({"input_tokens": 1000, "output_tokens": 500, "cost_decisions": usage["decisions_with_usage"]})
    config = {
        "contract": "sota-v2",
        "profile": "compact",
        "preset": "leaderboard",
        "models": [
            {
                "id": "openai-gpt-test",
                "provider": payload["run_info"]["provider"],
                "model": "gpt-test",
                "transport": "direct-api",
                "fixed_options": {},
                "absent_options": [],
            }
        ],
        "output_token_caps": [256],
        "repeats": 3,
        "decision_rule": {"required_models": 1},
    }

    result = analyze(config, [payload, payload])

    assert result["status"] == "incomplete"
    assert result["publishable_ranking"] is False
    assert result["duplicate_cells"] == [{"experiment_id": "openai-gpt-test", "output_token_cap": 256}]


def test_openrouter_price_route_is_public_diagnostic_but_not_sota() -> None:
    payload = _official_payload(repeats=3)
    payload["agent"] = "openrouter:openai/gpt-test"
    payload["candidate"]["agent"] = payload["agent"]
    payload["run_info"].update(
        {
            "agent": payload["agent"],
            "provider": "openrouter",
            "model": "openai/gpt-test",
            "scaffold_fingerprint": scaffold_fingerprint("openrouter"),
            "provider_options": {
                "OPENROUTER_PROVIDER_SORT": "price",
                "OPENROUTER_ALLOW_FALLBACKS": "false",
            },
        }
    )
    payload["candidate"]["summary"]["usage"]["upstream_providers"] = ["OpenAI"]

    public = validate_leaderboard_payload(payload, policy=PUBLIC_LEADERBOARD_POLICY)
    assert public.ok
    assert any("price-routed OpenRouter diagnostic" in warning for warning in public.warnings)

    sota = validate_leaderboard_payload(payload, policy=SOTA_V2_POLICY)
    assert not sota.ok
    assert any("OPENROUTER_PROVIDER_ONLY" in error for error in sota.errors)


def test_sota_v2_accepts_pinned_single_upstream_openrouter_route() -> None:
    payload = _official_payload(repeats=3)
    payload["agent"] = "openrouter:openai/gpt-test"
    payload["candidate"]["agent"] = payload["agent"]
    payload["run_info"].update(
        {
            "agent": payload["agent"],
            "provider": "openrouter",
            "model": "openai/gpt-test",
            "scaffold_fingerprint": scaffold_fingerprint("openrouter"),
            "provider_options": {
                "OPENROUTER_PROVIDER_ONLY": "openai",
                "OPENROUTER_EXPECTED_ENDPOINT_NAME": "OpenAI | openai/gpt-test-20260714",
                "OPENROUTER_ALLOW_FALLBACKS": "false",
                "GM_BENCH_PROTOCOL_REPAIR_ATTEMPTS": "1",
            },
        }
    )
    payload["candidate"]["summary"]["usage"]["upstream_providers"] = ["OpenAI"]

    report = validate_leaderboard_payload(payload, policy=SOTA_V2_POLICY)
    assert report.ok


def test_sota_v2_rejects_openrouter_upstream_that_differs_from_pin() -> None:
    payload = _official_payload(repeats=3)
    payload["agent"] = "openrouter:openai/gpt-test"
    payload["candidate"]["agent"] = payload["agent"]
    payload["run_info"].update(
        {
            "agent": payload["agent"],
            "provider": "openrouter",
            "model": "openai/gpt-test",
            "scaffold_fingerprint": scaffold_fingerprint("openrouter"),
            "provider_options": {
                "OPENROUTER_PROVIDER_ONLY": "OpenAI",
                "OPENROUTER_EXPECTED_ENDPOINT_NAME": "OpenAI | openai/gpt-test-20260714",
                "OPENROUTER_ALLOW_FALLBACKS": "false",
                "GM_BENCH_PROTOCOL_REPAIR_ATTEMPTS": "1",
            },
        }
    )
    payload["candidate"]["summary"]["usage"]["upstream_providers"] = ["Azure"]

    report = validate_leaderboard_payload(payload, policy=SOTA_V2_POLICY)

    assert not report.ok
    assert any("does not match" in error for error in report.errors)


def test_sota_v2_policy_requires_contract_provenance() -> None:
    payload = _official_payload(repeats=3)
    del payload["run_info"]["benchmark_contract"]
    report = validate_leaderboard_payload(payload, policy=SOTA_V2_POLICY)
    assert not report.ok
    assert "run_info.benchmark_contract is required for current-contract validation" in report.errors


def test_sota_v2_policy_rejects_missing_scaffold_fingerprint() -> None:
    payload = _official_payload(repeats=3)
    del payload["run_info"]["scaffold_fingerprint"]
    sota_report = validate_leaderboard_payload(payload, policy=SOTA_V2_POLICY)
    assert not sota_report.ok
    assert any("scaffold_fingerprint is required for sota-v2 rows" in error for error in sota_report.errors)

    public_report = validate_leaderboard_payload(payload, policy=PUBLIC_LEADERBOARD_POLICY)
    assert public_report.ok
    assert any("scaffold_fingerprint missing" in warning for warning in public_report.warnings)


def test_sota_v2_policy_requires_seed_panel_provenance() -> None:
    payload = _official_payload(repeats=3)
    del payload["run_info"]["seed_panel"]
    report = validate_leaderboard_payload(payload, policy=SOTA_V2_POLICY)
    assert not report.ok
    assert "run_info.seed_panel is required for official seed-panel validation" in report.errors


def test_sota_v2_policy_rejects_contract_fingerprint_mismatch() -> None:
    payload = _official_payload(repeats=3)
    payload["run_info"]["benchmark_contract"]["contract_fingerprint"] = "stale"
    report = validate_leaderboard_payload(payload, policy=SOTA_V2_POLICY)
    assert not report.ok
    assert any("contract_fingerprint" in error for error in report.errors)


def test_sota_v2_policy_accepts_private_panel_when_env_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    private_seeds = [101, 102, 110, 111, 112, 113, 114, 115]
    monkeypatch.setenv(PRIVATE_SEEDS_ENV, "101,102,110-115")
    report = validate_leaderboard_payload(
        _official_payload(repeats=3, seeds=private_seeds),
        policy=SOTA_V2_POLICY,
    )
    assert report.ok


def test_sota_v2_policy_rejects_too_small_private_panel(monkeypatch: pytest.MonkeyPatch) -> None:
    private_seeds = [101, 102, 110, 111]
    monkeypatch.setenv(PRIVATE_SEEDS_ENV, "101,102,110-111")
    report = validate_leaderboard_payload(
        _official_payload(repeats=3, seeds=private_seeds),
        policy=SOTA_V2_POLICY,
    )
    assert not report.ok
    assert "seeds must contain at least 8 seed(s) for sota-v2" in report.errors


def test_sota_v2_policy_rejects_private_panel_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    private_seeds = [101, 102, 110, 111, 112, 113, 114, 115]
    monkeypatch.setenv(PRIVATE_SEEDS_ENV, "101,102,110-115")
    payload = _official_payload(repeats=3, seeds=private_seeds)
    monkeypatch.delenv(PRIVATE_SEEDS_ENV)
    report = validate_leaderboard_payload(payload, policy=SOTA_V2_POLICY)
    assert not report.ok
    assert f"{PRIVATE_SEEDS_ENV} is required to validate a private leaderboard seed panel" in report.errors


def test_sota_v2_policy_rejects_seed_panel_hash_mismatch() -> None:
    payload = _official_payload(repeats=3)
    payload["run_info"]["seed_panel"]["sha256"] = "stale"
    report = validate_leaderboard_payload(payload, policy=SOTA_V2_POLICY)
    assert not report.ok
    assert any("seed_panel.sha256" in error for error in report.errors)


def test_redact_leaderboard_payload_removes_private_seed_details(monkeypatch: pytest.MonkeyPatch) -> None:
    private_seeds = [101, 102, 110, 111, 112, 113, 114, 115]
    monkeypatch.setenv(PRIVATE_SEEDS_ENV, "101,102,110-115")
    redacted, report = redact_leaderboard_payload(_official_payload(repeats=3, seeds=private_seeds))

    assert report.ok
    assert redacted["validation_reports"]["sota-v2"]["ok"] is True
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
    assert payload["validation_reports"]["sota-v2"]["ok"] is True


def test_leaderboard_builder_accepts_redacted_private_artifact(monkeypatch: pytest.MonkeyPatch) -> None:
    private_seeds = [101, 102, 110, 111, 112, 113, 114, 115]
    monkeypatch.setenv(PRIVATE_SEEDS_ENV, "101,102,110-115")
    redacted, _report = redact_leaderboard_payload(_official_payload(repeats=3, seeds=private_seeds))
    monkeypatch.delenv(PRIVATE_SEEDS_ENV)

    # Revalidation must succeed without the private seed env: only the commitment remains.
    report = validate_leaderboard_payload(redacted, policy=SOTA_V2_POLICY)
    assert report.ok

    row = model_row(redacted)

    assert row["seeds"] is None
    assert row["seed_panel"] == "private-env"
    assert row["sota_v2_eligible"] is True
    assert row["sota_v2_issues"] == []


def test_leaderboard_builder_revalidates_forged_sota_report() -> None:
    payload = _official_payload(repeats=1, failure_rate=0.05)
    payload["validation_reports"] = {"sota-v2": {"ok": True, "errors": []}}

    row = model_row(payload)

    assert row["sota_v2_eligible"] is False


def test_leaderboard_builder_rejects_forged_redacted_sota_report() -> None:
    payload = _official_payload(repeats=1, failure_rate=1.0)
    payload["seeds"] = REDACTED_SEEDS_SENTINEL
    payload["candidate"]["seeds"] = REDACTED_SEEDS_SENTINEL
    payload["candidate"]["episodes"] = []
    payload["candidate"]["repeats"] = 1
    for baseline in payload["baselines"]:
        baseline["seeds"] = REDACTED_SEEDS_SENTINEL
        baseline["episodes"] = []
    payload["paired"]["per_seed"] = []
    payload["run_info"]["seed_panel"] = {
        "name": "private-env",
        "count": 8,
        "sha256": "a" * 64,
        "preset": "leaderboard",
    }
    payload["redaction"] = {"applied": True, "seed_panel": "private-env", "removed": ["seeds"]}
    payload["validation_reports"] = {"sota-v2": {"policy": "sota-v2", "ok": True, "errors": [], "warnings": []}}

    report = validate_leaderboard_payload(payload, policy=SOTA_V2_POLICY)
    assert not report.ok
    assert any("candidate.repeats" in error for error in report.errors)
    assert any("decision_failure_rate" in error for error in report.errors)

    row = model_row(payload)
    assert row["sota_v2_eligible"] is False


def test_sota_v2_policy_accepts_valid_redacted_private_artifact(monkeypatch: pytest.MonkeyPatch) -> None:
    private_seeds = [101, 102, 110, 111, 112, 113, 114, 115]
    monkeypatch.setenv(PRIVATE_SEEDS_ENV, "101,102,110-115")
    redacted, report = redact_leaderboard_payload(_official_payload(repeats=3, seeds=private_seeds))
    assert report.ok
    monkeypatch.delenv(PRIVATE_SEEDS_ENV)

    revalidated = validate_leaderboard_payload(redacted, policy=SOTA_V2_POLICY)
    assert revalidated.ok


def test_cli_redact_result_skips_write_when_invalid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    private_seeds = [101, 102, 110, 111, 112, 113, 114, 115]
    monkeypatch.setenv(PRIVATE_SEEDS_ENV, "101,102,110-115")
    raw_path = tmp_path / "raw.json"
    redacted_path = tmp_path / "redacted.json"
    raw_path.write_text(json.dumps(_official_payload(repeats=1, seeds=private_seeds)))

    with pytest.raises(SystemExit) as excinfo:
        cli_module.main(["redact-result", str(raw_path), "--output", str(redacted_path)])
    assert excinfo.value.code == 1
    assert not redacted_path.exists()


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
