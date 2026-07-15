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


def test_compact_result_rejects_already_compacted_artifact() -> None:
    compact = compact_result(_payload())
    with pytest.raises(ValueError, match="already has publication metadata"):
        compact_result(compact)


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
    config["models"] = []
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


def test_budget_analysis_rejects_uncapped_cell_with_numeric_provider_max(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("analyze_output_budget", Path("scripts/analyze_output_budget.py"))
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    monkeypatch.setattr(module, "validate_leaderboard_payload", lambda *args, **kwargs: type("R", (), {"ok": True})())
    config = json.loads(Path("config/output_budget_sweep.json").read_text())
    config["models"] = [
        {
            "id": "openai-demo-model",
            "provider": "openai",
            "model": "demo-model",
            "transport": "direct-api",
            "fixed_options": {},
            "absent_options": [],
        }
    ]
    payload = {
        "run_info": {
            "model": "demo-model",
            "provider": "openai",
            "transport": "direct-api",
            "profile": "compact",
            "preset": "leaderboard",
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
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cost_usd": 0.01,
                    "cost_decisions": 20,
                },
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


def test_budget_analysis_rejects_mixed_pre_registered_provenance(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("analyze_output_budget", Path("scripts/analyze_output_budget.py"))
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "validate_leaderboard_payload", lambda *args, **kwargs: type("R", (), {"ok": True})())
    config = {
        "contract": "sota-v2",
        "profile": "compact",
        "preset": "leaderboard",
        "output_token_caps": [256],
        "repeats": 3,
        "require_complete_cost": True,
        "decision_rule": {"required_models": 1},
        "models": [
            {
                "id": "openrouter-demo",
                "provider": "openrouter",
                "model": "demo/model",
                "transport": "gateway-api",
                "upstream_provider": "ExpectedProvider",
                "fixed_options": {
                    "OPENROUTER_PROVIDER_ONLY": "ExpectedProvider",
                    "GM_BENCH_PROTOCOL_REPAIR_ATTEMPTS": "1",
                },
                "absent_options": ["OPENROUTER_REASONING_EFFORT"],
            }
        ],
    }
    payload = {
        "run_info": {
            "provider": "openrouter",
            "model": "demo/model",
            "transport": "gateway-api",
            "profile": "compact",
            "preset": "leaderboard",
            "benchmark_contract": {"benchmark_version": "sota-v2"},
            "provider_options": {
                "OPENROUTER_PROVIDER_ONLY": "DifferentProvider",
                "GM_BENCH_PROTOCOL_REPAIR_ATTEMPTS": "0",
                "OPENROUTER_REASONING_EFFORT": "high",
                "GM_BENCH_OUTPUT_BUDGET_CELL": "256",
                "OPENROUTER_MAX_TOKENS": "256",
            },
        },
        "candidate": {
            "repeats": 3,
            "summary": {
                "decisions": 20,
                "mean_score": 1.0,
                "decision_failure_rate": 0.0,
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cost_usd": None,
                    "cost_decisions": 0,
                    "upstream_providers": ["DifferentProvider"],
                },
            },
        },
    }

    result = module.analyze(config, [payload])

    reasons = result["rejected_artifacts"][0]["reasons"]
    assert any("pre-registered value" in reason for reason in reasons)
    assert any("must be absent" in reason for reason in reasons)
    assert any("upstream provider" in reason for reason in reasons)
    assert any("numeric cost" in reason for reason in reasons)
    assert any("cost telemetry" in reason for reason in reasons)


def test_publication_model_registry_is_consistent_with_sweep() -> None:
    sweep = json.loads(Path("config/output_budget_sweep.json").read_text())
    registry = json.loads(Path("config/sota_v2_models.json").read_text())
    lane = json.loads(Path("config/sota_v2_lane.json").read_text())

    models = registry["models"]
    identities = {(row["provider"], row["model"]): row for row in models}
    assert 8 <= len(models) <= 12
    assert len({row["id"] for row in models}) == len(models)
    assert len(identities) == len(models)
    assert len({row["endpoint_name"] for row in models}) == len(models)
    assert registry["selection_status"] == "provisional-awaiting-route-smokes"
    assert registry["selection_frozen_at_utc"] is None
    assert registry["shared_fixed_options"]["OPENROUTER_REASONING_ENABLED"] == "false"
    assert "OPENROUTER_REASONING_EFFORT" in registry["shared_absent_options"]
    assert {row["model"] for row in registry["explicit_exclusions"]} == {
        "google/gemini-3.1-pro-preview",
        "x-ai/grok-4.5",
    }
    assert set(registry["changed_routes_pending_smoke"]) <= {row["id"] for row in models}
    assert lane["model_registry"] == "config/sota_v2_models.json"
    assert lane["minimum_headline_models"] >= 8

    for sweep_model in sweep["models"]:
        registry_model = identities[(sweep_model["provider"], sweep_model["model"])]
        assert sweep_model["id"] == registry_model["id"]
        assert sweep_model["transport"] == registry_model["transport"]
        assert sweep_model["upstream_provider"] == registry_model["upstream_provider"]
        expected_options = {
            **registry["shared_fixed_options"],
            "OPENROUTER_PROVIDER_ONLY": registry_model["upstream_provider"],
            "OPENROUTER_EXPECTED_ENDPOINT_NAME": registry_model["endpoint_name"],
        }
        assert sweep_model["fixed_options"] == expected_options
        assert sweep_model["absent_options"] == registry["shared_absent_options"]


def test_publication_gate_withholds_rows_until_minimum_panel_is_eligible() -> None:
    from web.scripts.build_leaderboard import publication_gate

    analysis = {"status": "complete-needs-interpretation", "reason": "ready"}
    lane = {
        "output_budget_status": "frozen-saturation",
        "output_token_cap": 1024,
        "minimum_headline_models": 2,
    }
    eligible = {
        "id": "one",
        "lane": "api",
        "publication_eligible": True,
        "output_token_cap": 1024,
    }
    models, report = publication_gate([eligible], analysis, lane)
    assert models == []
    assert report["publishable_ranking"] is False
    assert report["eligible_headline_models"] == 1

    second = {**eligible, "id": "two"}
    models, report = publication_gate([eligible, second], analysis, lane)
    assert models == [eligible, second]
    assert report["publishable_ranking"] is True


def test_publication_gate_rejects_wrong_cap_and_unregistered_rows() -> None:
    from web.scripts.build_leaderboard import publication_gate

    analysis = {"status": "complete-needs-interpretation"}
    lane = {
        "output_budget_status": "frozen-fixed-budget",
        "output_token_cap": 1024,
        "minimum_headline_models": 1,
    }
    rows = [
        {"lane": "api", "publication_eligible": True, "output_token_cap": 4096},
        {"lane": "api", "publication_eligible": False, "output_token_cap": 1024},
    ]
    models, report = publication_gate(rows, analysis, lane)
    assert models == []
    assert report["publishable_ranking"] is False


def test_budget_decision_rule_is_deterministic() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("analyze_output_budget", Path("scripts/analyze_output_budget.py"))
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    config = {
        "output_token_caps": [256, 1024, 4096],
        "decision_rule": {
            "material_gain_score_points": 10.0,
            "material_gain_relative": 0.05,
            "non_saturation_output_token_cap": 4096,
        },
    }
    saturated_points = [
        {"experiment_id": model, "output_token_cap": cap, "mean_score": score}
        for model in ("a", "b")
        for cap, score in ((256, 100.0), (1024, 112.0), (4096, 114.0))
    ]
    saturated = module._decision_recommendation(config, saturated_points)
    assert saturated["output_budget_status"] == "frozen-saturation"
    assert saturated["output_token_cap"] == 1024

    elastic_points = [
        {"experiment_id": model, "output_token_cap": cap, "mean_score": score}
        for model in ("a", "b")
        for cap, score in ((256, 100.0), (1024, 115.0), (4096, 130.0))
    ]
    elastic = module._decision_recommendation(config, elastic_points)
    assert elastic["output_budget_status"] == "frozen-fixed-budget"
    assert elastic["output_token_cap"] == 4096
