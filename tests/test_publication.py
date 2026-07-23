from __future__ import annotations

import json
import math
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
    return {
        "baseline_cache": {
            "enabled": True,
            "hits": 1,
            "path": "/Users/example/project/data/baseline_cache.json",
            "total": 1,
        },
        "candidate": {"episodes": [episode]},
        "baselines": [{"episodes": [episode]}],
    }


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
    assert compact["baseline_cache"] == {"enabled": True, "hits": 1, "total": 1}


def test_compact_result_rejects_already_compacted_artifact() -> None:
    compact = compact_result(_payload())
    with pytest.raises(ValueError, match="already has publication metadata"):
        compact_result(compact)


def test_canonical_hash_refuses_non_finite_publication_json() -> None:
    with pytest.raises(ValueError, match="Out of range float values"):
        canonical_sha256({"score": math.nan})


def test_budget_analysis_refuses_empty_sweep(tmp_path: Path) -> None:
    output = tmp_path / "analysis.json"
    subprocess.run(["python3", "scripts/analyze_output_budget.py", "--output", str(output)], check=True)
    result = json.loads(output.read_text())
    assert result["status"] == "retired"
    assert result["publishable_ranking"] is False
    assert result["missing"] == []


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
    assert result["status"] == "retired"
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


def test_publication_model_registry_is_consistent_with_revised_lane() -> None:
    sweep = json.loads(Path("config/output_budget_sweep.json").read_text())
    registry = json.loads(Path("config/sota_v2_models.json").read_text())
    lane = json.loads(Path("config/sota_v2_lane.json").read_text())
    protocol = json.loads(Path("config/publication_protocol.json").read_text())

    models = registry["models"]
    identities = {(row["provider"], row["model"]): row for row in models}
    assert len(models) == 10
    assert len({row["id"] for row in models}) == len(models)
    assert len(identities) == len(models)
    assert len({row["endpoint_name"] for row in models}) == len(models)
    assert registry["selection_status"] == "frozen"
    assert registry["selection_frozen_at_utc"] == "2026-07-18T19:50:59Z"
    assert registry["selection_revision"] == "2026-07-18-glm-novita-route-amendment"
    assert registry["output_token_cap"] == lane["output_token_cap"] == 4096
    assert registry["output_budget_status"] == lane["output_budget_status"] == "frozen-native-reasoning-cap"
    assert (
        registry["output_policy_basis"]
        == lane["output_policy_basis"]
        == "common-safety-ceiling-with-native-minimum-reasoning"
    )
    assert {row["cohort"] for row in models} == {"big-american-lab-proprietary", "open-weight"}
    assert sum(row["cohort"] == "big-american-lab-proprietary" for row in models) == 5
    assert sum(row["cohort"] == "open-weight" for row in models) == 5
    assert {row["model"] for row in registry["explicit_exclusions"]} == {
        "moonshotai/kimi-k3",
        "nvidia/nemotron-3-ultra-550b-a55b:free",
        "deepseek/deepseek-v4-pro",
    }
    assert set(registry["changed_routes_pending_smoke"]) <= {row["id"] for row in models}
    assert set(registry["required_smokes"]) == {row["id"] for row in models}
    assert lane["model_registry"] == "config/sota_v2_models.json"
    assert lane["minimum_headline_models"] >= 8

    output_policy = protocol["output_policy"]
    assert output_policy["status"] == lane["output_budget_status"]
    assert output_policy["basis"] == lane["output_policy_basis"]
    assert output_policy["reasoning_policy"] == lane["reasoning_policy"]
    assert output_policy["output_token_cap"] == lane["output_token_cap"]
    assert output_policy["cap_pressure_threshold_tokens"] == lane["cap_pressure_threshold_tokens"]
    assert output_policy["fallback_output_token_cap"] == lane["fallback_output_token_cap"]

    glm = identities[("openrouter", "z-ai/glm-5.2")]
    assert glm["id"] == "openrouter-glm-5.2-novita"
    assert glm["upstream_provider"] == "Novita"
    assert glm["endpoint_tag"] == "novita/fp8"

    assert sweep["status"] == "retired-fixed-safety-cap"
    for model in models:
        assert model["upstream_provider_slug"] == model["endpoint_tag"]
        assert model["fixed_options"]["OPENROUTER_REASONING_ENABLED"] in {"true", "false"}
        if model["reasoning_policy"] == "mandatory-minimum":
            assert model["reasoning_effort"] in {"minimal", "low", "max"}
            assert model["fixed_options"]["OPENROUTER_REASONING_EFFORT"] == model["reasoning_effort"]
        else:
            assert model["reasoning_policy"] == "disabled"
            assert model["reasoning_effort"] is None
            assert "OPENROUTER_REASONING_EFFORT" in model["absent_options"]


def _panel_analysis(rows: list[dict], *, family_size: int = 0) -> dict:
    models = []
    for index, row in enumerate(rows, start=1):
        analysis_row = {
            "model_id": row["id"],
            "tier": index,
            "holm_adjusted_p_value": 0.5,
            "holm_reject_at_0_05": False,
        }
        if row.get("provider") and row.get("model"):
            analysis_row.update({"provider": row["provider"], "model": row["model"]})
        if row.get("raw_artifact_sha256"):
            analysis_row["raw_artifact_sha256"] = row["raw_artifact_sha256"]
        models.append(analysis_row)
    return {
        "eligible_model_count": len(models),
        "holm_family_size": family_size,
        "models": models,
    }


def test_publication_identity_issues_flags_missing_upstream_slug_without_crashing() -> None:
    from web.scripts.build_leaderboard import _publication_identity_issues

    config = {
        "profile": "compact",
        "session": False,
        "shared_fixed_options": {},
        "shared_absent_options": [],
        "models": [
            {
                "provider": "openrouter",
                "model": "demo/model",
                "transport": "gateway-api",
                "upstream_provider": "Demo",
                # upstream_provider_slug intentionally omitted: a registered
                # model can declare upstream_provider without a slug.
                "endpoint_name": "",
                "fixed_options": {},
                "absent_options": [],
            }
        ],
    }
    payload = {
        "run_info": {
            "provider": "openrouter",
            "model": "demo/model",
            "transport": "gateway-api",
            "profile": "compact",
            "session": False,
            "provider_options": {
                "OPENROUTER_PROVIDER_ONLY": "demo",
                "OPENROUTER_EXPECTED_UPSTREAM_PROVIDER": "Demo",
            },
        },
        "candidate": {
            "summary": {
                "decisions": 4,
                "usage": {
                    "cost_usd": 0.01,
                    "cost_decisions": 4,
                    "upstream_providers": ["demo"],
                },
            }
        },
    }

    issues = _publication_identity_issues(payload, config)
    assert any("OPENROUTER_PROVIDER_ONLY" in issue for issue in issues)


def test_publication_gate_withholds_rows_until_minimum_panel_is_eligible() -> None:
    from web.scripts.build_leaderboard import publication_gate

    analysis = {"status": "complete-needs-interpretation", "reason": "ready"}
    lane = {
        "output_budget_status": "frozen-saturation",
        "output_token_cap": 1024,
        "minimum_headline_models": 2,
    }
    registry = {"selection_status": "frozen"}
    eligible = {
        "id": "one",
        "lane": "api",
        "publication_eligible": True,
        "output_token_cap": 1024,
    }
    models, report = publication_gate([eligible], analysis, lane, registry, panel_analysis=_panel_analysis([eligible]))
    assert models == []
    assert report["publishable_ranking"] is False
    assert report["eligible_headline_models"] == 1
    assert report["duplicate_headline_rows"] == 0
    assert report["smoke_gate_issues"] is None

    second = {**eligible, "id": "two"}
    models, report = publication_gate(
        [eligible, second],
        analysis,
        lane,
        registry,
        panel_analysis=_panel_analysis([eligible, second]),
    )
    assert models == [eligible, second]
    assert report["publishable_ranking"] is True
    assert report["eligible_headline_models"] == 2
    assert report["duplicate_headline_rows"] == 0


def test_publication_gate_recognizes_frozen_native_reasoning_cap_status() -> None:
    """A new frozen-* status string must not silently stop cap detection."""
    from web.scripts.build_leaderboard import publication_gate

    analysis = {"status": "retired"}
    lane = {
        "output_budget_status": "frozen-native-reasoning-cap",
        "output_policy_basis": "common-safety-ceiling-with-native-minimum-reasoning",
        "output_token_cap": 4096,
        "minimum_headline_models": 1,
    }
    eligible = {
        "id": "one",
        "provider": "openrouter",
        "model": "demo/one",
        "lane": "api",
        "publication_eligible": True,
        "output_token_cap": 4096,
    }
    models, report = publication_gate(
        [eligible],
        analysis,
        lane,
        {"selection_status": "frozen"},
        panel_analysis=_panel_analysis([eligible]),
        smoke_issues=[],
    )
    assert models == [eligible]
    assert report["frozen_output_token_cap"] == 4096
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
    models, report = publication_gate(rows, analysis, lane, {"selection_status": "frozen"})
    assert models == []
    assert report["publishable_ranking"] is False


def test_publication_gate_accepts_fixed_safety_policy_without_completed_sweep() -> None:
    from web.scripts.build_leaderboard import publication_gate

    analysis = {"status": "incomplete", "reason": "retired sweep"}
    lane = {
        "output_budget_status": "frozen-fixed-budget",
        "output_policy_basis": "fixed-safety-ceiling",
        "output_token_cap": 1024,
        "minimum_headline_models": 1,
    }
    eligible = {
        "id": "one",
        "lane": "api",
        "publication_eligible": True,
        "output_token_cap": 1024,
    }
    models, report = publication_gate(
        [eligible],
        analysis,
        lane,
        {"selection_status": "frozen"},
        panel_analysis=_panel_analysis([eligible]),
    )
    assert models == [eligible]
    assert report["publishable_ranking"] is True
    assert report["output_policy_basis"] == "fixed-safety-ceiling"


def test_publication_gate_rejects_provisional_model_registry() -> None:
    from web.scripts.build_leaderboard import publication_gate

    analysis = {"status": "incomplete"}
    lane = {
        "output_budget_status": "frozen-fixed-budget",
        "output_policy_basis": "fixed-safety-ceiling",
        "output_token_cap": 1024,
        "minimum_headline_models": 1,
    }
    eligible = {
        "id": "one",
        "lane": "api",
        "publication_eligible": True,
        "output_token_cap": 1024,
    }
    models, report = publication_gate(
        [eligible], analysis, lane, {"selection_status": "provisional-awaiting-route-smokes"}
    )
    assert models == []
    assert report["publishable_ranking"] is False
    assert report["model_registry_frozen"] is False
    assert "provisional" in report["reason"]


def test_publication_gate_rejects_aliased_rows_for_one_model() -> None:
    from web.scripts.build_leaderboard import publication_gate

    analysis = {"status": "incomplete"}
    lane = {
        "output_budget_status": "frozen-fixed-budget",
        "output_policy_basis": "fixed-safety-ceiling",
        "output_token_cap": 1024,
        "minimum_headline_models": 8,
    }
    rows = [
        {
            "id": f"alias-{index}",
            "provider": "openrouter",
            "model": "demo/model",
            "lane": "api",
            "publication_eligible": True,
            "output_token_cap": 1024,
        }
        for index in range(8)
    ]
    models, report = publication_gate(
        rows,
        analysis,
        lane,
        {"selection_status": "frozen"},
        panel_analysis=_panel_analysis(rows),
        smoke_issues=[],
    )
    assert models == []
    assert report["publishable_ranking"] is False
    assert report["eligible_headline_models"] == 1
    assert report["duplicate_headline_rows"] == 7
    assert "duplicate" in report["reason"]


def test_publication_gate_publishes_distinct_provider_model_identities() -> None:
    from web.scripts.build_leaderboard import publication_gate

    analysis = {"status": "incomplete"}
    lane = {
        "output_budget_status": "frozen-fixed-budget",
        "output_policy_basis": "fixed-safety-ceiling",
        "output_token_cap": 1024,
        "minimum_headline_models": 2,
    }
    rows = [
        {
            "id": "a",
            "provider": "openrouter",
            "model": "demo/one",
            "lane": "api",
            "publication_eligible": True,
            "output_token_cap": 1024,
        },
        {
            "id": "b",
            "provider": "openrouter",
            "model": "demo/two",
            "lane": "api",
            "publication_eligible": True,
            "output_token_cap": 1024,
        },
    ]
    models, report = publication_gate(
        rows,
        analysis,
        lane,
        {"selection_status": "frozen"},
        panel_analysis=_panel_analysis(rows),
        smoke_issues=[],
    )
    assert models == rows
    assert report["publishable_ranking"] is True
    assert report["eligible_headline_models"] == 2
    assert report["duplicate_headline_rows"] == 0
    assert report["smoke_gate_issues"] == []


def test_publication_gate_rejects_analysis_for_different_artifact() -> None:
    from web.scripts.build_leaderboard import publication_gate

    analysis = {"status": "incomplete"}
    lane = {
        "output_budget_status": "frozen-fixed-budget",
        "output_policy_basis": "fixed-safety-ceiling",
        "output_token_cap": 1024,
        "minimum_headline_models": 1,
    }
    row = {
        "id": "one",
        "provider": "openrouter",
        "model": "demo/one",
        "lane": "api",
        "publication_eligible": True,
        "output_token_cap": 1024,
        "raw_artifact_sha256": "a" * 64,
    }
    panel_analysis = _panel_analysis([row])
    panel_analysis["models"][0]["raw_artifact_sha256"] = "b" * 64

    models, report = publication_gate(
        [row],
        analysis,
        lane,
        {"selection_status": "frozen"},
        panel_analysis=panel_analysis,
        smoke_issues=[],
    )

    assert models == []
    assert report["panel_analysis_ready"] is False
    assert "hash" in report["reason"]


def test_publication_gate_blocks_on_incomplete_smoke_evidence() -> None:
    from web.scripts.build_leaderboard import publication_gate

    analysis = {"status": "incomplete"}
    lane = {
        "output_budget_status": "frozen-fixed-budget",
        "output_policy_basis": "fixed-safety-ceiling",
        "output_token_cap": 1024,
        "minimum_headline_models": 1,
    }
    eligible = {
        "id": "one",
        "provider": "openrouter",
        "model": "demo/one",
        "lane": "api",
        "publication_eligible": True,
        "output_token_cap": 1024,
    }
    smoke_issues = ["smoke manifest is missing; record every registered-model smoke before the panel"]
    models, report = publication_gate(
        [eligible],
        analysis,
        lane,
        {"selection_status": "frozen"},
        smoke_issues=smoke_issues,
    )
    assert models == []
    assert report["publishable_ranking"] is False
    assert "smoke evidence" in report["reason"]
    assert report["smoke_gate_issues"] == smoke_issues


def test_publication_gate_protocol_minimum_overrides_lower_lane_floor() -> None:
    from web.scripts.build_leaderboard import publication_gate

    analysis = {"status": "incomplete"}
    lane = {
        "output_budget_status": "frozen-fixed-budget",
        "output_policy_basis": "fixed-safety-ceiling",
        "output_token_cap": 1024,
        "minimum_headline_models": 2,
    }
    rows = [
        {
            "id": f"m{index}",
            "provider": "openrouter",
            "model": f"demo/{index}",
            "lane": "api",
            "publication_eligible": True,
            "output_token_cap": 1024,
        }
        for index in range(2)
    ]
    models, report = publication_gate(
        rows,
        analysis,
        lane,
        {"selection_status": "frozen"},
        smoke_issues=[],
        protocol_minimum=8,
    )
    assert models == []
    assert report["publishable_ranking"] is False
    assert report["minimum_headline_models"] == 8
    assert report["eligible_headline_models"] == 2
    assert "at least 8" in report["reason"]


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
