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
        "score_components": {"recent_wins": 4.0, "recent_wins_contribution": 14.5, "protocol_penalty": -2.0},
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
    assert episode["score_components"] == raw["candidate"]["episodes"][0]["score_components"]
    assert compact["baseline_cache"] == {"enabled": True, "hits": 1, "total": 1}


def test_score_components_survive_the_run_to_compact_artifact_round_trip() -> None:
    from gm_bench.agents import AGENTS
    from gm_bench.runner import run_many
    from gm_bench.scoring import SCORE_COMPONENT_KEYS

    payload = run_many(AGENTS["value"](), seeds=[11], seasons=2, workers=1)
    compact = compact_result({"candidate": payload, "baselines": []})
    episode = compact["candidate"]["episodes"][0]

    # A published row must be reweightable on its own: every term present, and
    # the contributions still adding up to the score the row was ranked on.
    assert tuple(episode["score_components"]) == SCORE_COMPONENT_KEYS
    rebuilt = sum(value for name, value in episode["score_components"].items() if name.endswith("_contribution"))
    assert rebuilt == pytest.approx(episode["strategy_score"], abs=1e-3)
    assert episode["score_components"]["protocol_penalty"] == pytest.approx(episode["protocol_penalty"], abs=1e-3)
    # The artifact is JSON evidence, so it must survive the canonical encoder.
    assert canonical_sha256(compact)


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
            # The primary point estimate and interval must accompany the Holm
            # verdict; the site publishes all three from this one row.
            "mean_lift": -100.0,
            "bootstrap_ci95": [-150.0, -50.0],
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


def _reference_only_panel_analysis(rows: list[dict], *, family_size: int) -> dict:
    analysis = _panel_analysis(rows, family_size=family_size)
    analysis.update(
        {
            "benchmark_version": "sota-v3",
            "analysis_mode": "reference-only",
            "publication_ready": True,
            "model_tiering": {"status": "not-supported"},
        }
    )
    for row in analysis["models"]:
        row.pop("tier", None)
    return analysis


def test_site_ingestion_requires_primary_estimate_beside_holm_verdict() -> None:
    """A Holm p-value without its own contrast's estimate is unpublishable.

    Publishing the pick-trader Holm verdict next to the baseline-panel lift and
    interval is the specific mismatch this guard exists to prevent.
    """
    from web.scripts.build_leaderboard import _panel_analysis_rows

    candidate = {"id": "demo", "provider": "openrouter", "model": "demo/model"}
    for dropped, expected in (
        ("mean_lift", "publication panel analysis row is missing its primary mean lift"),
        ("bootstrap_ci95", "publication panel analysis row is missing a valid primary bootstrap interval"),
    ):
        analysis = _panel_analysis([candidate], family_size=1)
        analysis["models"][0].pop(dropped)
        _rows, issues = _panel_analysis_rows([candidate], analysis, family_size=1, minimum_models=1)
        assert expected in issues, f"dropping {dropped} must block publication"


def test_site_ingestion_rejects_inverted_primary_interval() -> None:
    from web.scripts.build_leaderboard import _panel_analysis_rows

    candidate = {"id": "demo", "provider": "openrouter", "model": "demo/model"}
    analysis = _panel_analysis([candidate], family_size=1)
    analysis["models"][0]["bootstrap_ci95"] = [-50.0, -150.0]

    _rows, issues = _panel_analysis_rows([candidate], analysis, family_size=1, minimum_models=1)

    assert "publication panel analysis row is missing a valid primary bootstrap interval" in issues


def test_published_site_dataset_plots_the_frozen_primary_contrast() -> None:
    """The committed dataset's primary fields must equal the frozen analysis.

    This is the numeric cross-surface check: it pins the published numbers to
    scripts/analyze_publication_panel.py rather than merely asserting the fields
    exist. It also pins the *protocol* -- the primary contrast is versus
    pick-trader, and the panel contrast must remain a separately named field.
    """
    root = Path(__file__).resolve().parents[1]
    # The site publishes sota-v5; this check is the frozen v2 cross-surface
    # pin, so it reads the archived v2 dataset beside the v2 analysis.
    dataset = json.loads((root / "web" / "src" / "data" / "leaderboard-sota-v2.json").read_text())
    analysis = json.loads((root / "results" / "analysis" / "publication-panel-analysis.json").read_text())
    protocol = json.loads((root / "config" / "publication_protocol.json").read_text())

    assert "pick-trader" in protocol["statistical_analysis_plan"]["primary_contrast"]
    assert analysis["primary_contrast"] == "paired lift versus pick-trader"

    by_model = {row["model"]: row for row in analysis["models"]}
    assert dataset["models"], "committed dataset must have published rows to check"
    for row in dataset["models"]:
        expected = by_model[row["model"]]
        assert row["primary_lift"] == expected["mean_lift"]
        assert row["primary_ci95"] == list(expected["bootstrap_ci95"])
        assert row["holm_adjusted_p_value"] == expected["holm_adjusted_p_value"]
        # The panel contrast must stay present, distinct, and separately named.
        assert row["full_panel_lift"] != row["primary_lift"]
        # A bare `significant` flag derived from the panel bootstrap is exactly
        # what previously contradicted the primary Holm verdict on every row.
        assert "significant" not in row
        assert "paired_lift" not in row and "ci95" not in row


def test_published_rows_never_claim_significance_the_primary_test_refuses() -> None:
    """No row may advertise significance that the preregistered test denies.

    At eight seeds the sign-flip floor is 2/2**8, so against the frozen family
    of ten the smallest achievable Holm-adjusted p is 0.078 -- above 0.05 by
    construction. Any row claiming significance is therefore reading some other
    contrast's flag.
    """
    root = Path(__file__).resolve().parents[1]
    dataset = json.loads((root / "web" / "src" / "data" / "leaderboard-sota-v2.json").read_text())
    for row in dataset["models"]:
        if row.get("holm_reject_at_0_05") is False:
            assert row.get("full_panel_significant_at_95") is not None
            assert "significant" not in row


def test_v3_site_ingestion_requires_analyzer_publication_readiness() -> None:
    from web.scripts.build_leaderboard import _panel_analysis_rows

    candidate = {
        "benchmark_version": "sota-v3",
        "id": "demo",
        "provider": "openrouter",
        "model": "demo/model",
    }
    analysis = _panel_analysis([candidate], family_size=1)
    analysis["publication_ready"] = False

    _rows, issues = _panel_analysis_rows([candidate], analysis, family_size=1, minimum_models=1)

    assert "sota-v3 publication panel analysis is not publication-ready" in issues


def test_v3_site_ingestion_requires_exact_analysis_contract() -> None:
    from web.scripts.build_leaderboard import _panel_analysis_rows

    candidate = {
        "benchmark_version": "sota-v3",
        "id": "demo",
        "provider": "openrouter",
        "model": "demo/model",
    }
    analysis = _reference_only_panel_analysis([candidate], family_size=1)
    analysis["benchmark_version"] = "sota-v2"

    _rows, issues = _panel_analysis_rows([candidate], analysis, family_size=1, minimum_models=1)

    assert "sota-v3 publication panel analysis declares the wrong benchmark version" in issues


def test_v3_site_ingestion_accepts_reference_only_rows_without_tiers() -> None:
    from web.scripts.build_leaderboard import _panel_analysis_rows

    candidate = {
        "benchmark_version": "sota-v3",
        "id": "demo",
        "provider": "openrouter",
        "model": "demo/model",
    }
    analysis = _reference_only_panel_analysis([candidate], family_size=1)

    rows, issues = _panel_analysis_rows([candidate], analysis, family_size=1, minimum_models=1)

    assert issues == []
    assert "tier" not in rows[("openrouter", "demo/model")]


def test_v3_publication_gate_exposes_results_without_claiming_a_ranking() -> None:
    from web.scripts.build_leaderboard import publication_gate

    candidate = {
        "benchmark_version": "sota-v3",
        "id": "demo",
        "provider": "openrouter",
        "model": "demo/model",
        "lane": "api",
        "publication_eligible": True,
        "output_token_cap": 4096,
    }
    lane = {
        "output_budget_status": "frozen-fixed-budget",
        "output_policy_basis": "fixed-safety-ceiling",
        "output_token_cap": 4096,
        "minimum_headline_models": 1,
    }
    registry = {
        "selection_status": "frozen",
        "models": [{"id": "demo", "provider": "openrouter", "model": "demo/model"}],
    }
    analysis = _reference_only_panel_analysis([candidate], family_size=1)

    models, report = publication_gate(
        [candidate],
        {"status": "incomplete"},
        lane,
        registry,
        panel_analysis=analysis,
        smoke_issues=[],
    )

    assert models == [candidate]
    assert report["publishable_results"] is True
    assert report["publishable_ranking"] is False
    assert report["analysis_mode"] == "reference-only"
    assert "tier" not in candidate
    assert candidate["holm_adjusted_p_value"] == 0.5


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
    assert report["publishable_results"] is False
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
    assert report["publishable_results"] is True
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
