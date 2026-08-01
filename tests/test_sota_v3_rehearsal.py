from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import sota_v3_rehearsal as rehearsal_mod
from scripts.sota_v3_rehearsal import (
    execution_authorization_issues,
    run_rehearsal,
    synthetic_raw_artifact,
)


def test_synthetic_artifact_is_deterministic() -> None:
    assert synthetic_raw_artifact() == synthetic_raw_artifact()


def test_rehearsal_proves_v3_gates_and_site_isolation(tmp_path: Path) -> None:
    result = run_rehearsal(tmp_path / "rehearsal", run_web_build=False)

    assert result["status"] == "passed"
    assert result["mode"] == "synthetic"
    assert result["evidence_class"] == "synthetic-non-evidence"
    assert result["spend_usd"] == 0.0
    assert result["policy_selection"] == {"sota_v3": "accepted", "sota_v2": "rejected"}
    assert result["analysis"]["status"] == "complete"
    assert result["analysis"]["eligible_model_count"] == 1
    assert result["analysis"]["holm_family_size"] == 1
    assert result["analysis"]["bootstrap_ci95"][0] < result["analysis"]["bootstrap_ci95"][1]
    assert result["analysis"]["analysis_mode"] == "reference-only"
    assert result["analysis"]["model_tiering"]["status"] == "not-supported"
    assert result["live_v3_readiness"]["coherence_issues"] == []
    assert {row["name"] for row in result["mutations"]} == {
        "wrong-contract",
        "soft-fallback",
        "stale-scaffold",
        "unknown-version-dispatch",
        "unregistered-route",
        "tampered-compact-score",
        "raw-link-mismatch",
    }
    assert all(row["status"] == "rejected" for row in result["mutations"])
    assert result["site_data_build"] == {
        "status": "passed",
        "contract": "sota-v2",
        "synthetic_v3_excluded": True,
        "matches_checked_in_dataset": True,
        "shared_row_ingestion": "passed",
        "public_v3_strategy_selected": False,
    }
    assert result["web_build"] == {"status": "skipped"}
    assert Path(result["artifacts"]["raw"]).is_file()
    assert Path(result["artifacts"]["compact"]).is_file()


def test_rehearsal_fails_when_live_preregistration_is_incoherent(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        rehearsal_mod,
        "_live_v3_readiness",
        lambda: {
            "coherence_issues": ["sota-v3 model registry repeats does not match lane-authoritative repeats"],
            "smoke_execution_issues": [],
            "panel_execution_issues": [],
            "synthetic_validation_issues": [],
        },
    )

    with pytest.raises(AssertionError, match="live sota-v3 preregistration records contradict"):
        rehearsal_mod.run_rehearsal(tmp_path / "rehearsal", run_web_build=False)


def test_panel_like_action_fails_closed_on_both_authorization_locks() -> None:
    lane = {
        "contract": "sota-v3",
        "contract_fingerprint": "test-fingerprint",
        "execution_profile_authority": "lane",
        "headline_lane": "api",
        "provider": "openrouter",
        "observation_profile": "compact",
        "preset": "leaderboard",
        "session": False,
        "repeats": 3,
        "preregistration_status": "provisional-blocked",
        "panel_design_status": "unresolved-pre-data",
        "minimum_headline_models": 8,
        "reference_agent": "pick-trader",
        "output_policy_basis": "pending-live-route-smokes",
        "output_token_cap": None,
        "spend_authorized": False,
        "route_preflight_authorized": False,
        "smoke_execution_authorized": False,
        "panel_execution_authorized": False,
    }
    registry = {
        "contract": "sota-v3",
        "contract_fingerprint": "test-fingerprint",
        "lane": "api",
        "provider": "openrouter",
        "profile": "compact",
        "preset": "leaderboard",
        "session": False,
        "repeats": 3,
        "output_token_cap": None,
        "selection_status": "provisional-blocked",
        "models": [],
        "required_smokes": [],
        "spend_authorized": False,
        "panel_execution_authorized": False,
    }
    manifest = {
        "contract": "sota-v3",
        "contract_fingerprint": "test-fingerprint",
        "status": "not-started",
        "accepted_for_panel": False,
        "entries": {},
    }

    assert (
        execution_authorization_issues(
            lane,
            mode="synthetic",
            registry=registry,
            manifest=manifest,
        )
        == []
    )
    issues = execution_authorization_issues(lane, mode="panel", registry=registry, manifest=manifest)
    assert "sota-v3 publication protocol is not frozen" in issues
    assert "sota-v3 pricing snapshot is not frozen" in issues
    assert "sota-v3 lane is provisional-blocked; provider execution is locked" in issues
    assert "publication panel design is not frozen" in issues
    assert "publication model registry contains no models" in issues
    assert "publication model registry has 0 models; minimum_headline_models requires 8" in issues
    assert "publication output_token_cap must be a positive frozen integer" in issues
    assert "publication output policy basis is not frozen" in issues
    assert "provider execution is locked by the publication protocol budget policy" in issues
    assert "provider execution is locked by the pricing snapshot" in issues
    assert "v3 smoke manifest is not accepted for panel execution" in issues
    ready_lane = {
        "contract": "sota-v3",
        "contract_fingerprint": "test-fingerprint",
        "execution_profile_authority": "lane",
        "headline_lane": "api",
        "provider": "openrouter",
        "observation_profile": "compact",
        "preset": "leaderboard",
        "session": False,
        "repeats": 3,
        "preregistration_status": "frozen",
        "panel_design_status": "frozen",
        "minimum_headline_models": 1,
        "reference_agent": "pick-trader",
        "seed_panel": {
            "status": "frozen",
            "name": "public-leaderboard",
            "count": 8,
            "sha256": "a" * 64,
        },
        "output_policy_basis": "fixed-safety-ceiling",
        "output_token_cap": 4096,
        "spend_authorized": True,
        "panel_execution_authorized": True,
    }
    ready_registry = {
        "contract": "sota-v3",
        "contract_fingerprint": "test-fingerprint",
        "lane": "api",
        "provider": "openrouter",
        "profile": "compact",
        "preset": "leaderboard",
        "session": False,
        "repeats": 3,
        "output_token_cap": 4096,
        "selection_status": "frozen",
        "models": [{"id": "demo"}],
        "required_smokes": ["demo"],
        "spend_authorized": True,
        "panel_execution_authorized": True,
    }
    ready_manifest = {
        "contract": "sota-v3",
        "contract_fingerprint": "test-fingerprint",
        "accepted_for_panel": True,
        "entries": {"demo": {"accepted": True}},
    }
    ready_protocol = {
        "contract": "sota-v3",
        "contract_fingerprint": "test-fingerprint",
        "status": "frozen",
        "statistical_analysis_plan": {
            "status": "frozen",
            "analysis_mode": "reference-only",
            "inference_method": "exact-enumeration-sign-flip",
            "unit_of_inference": "seed",
            "primary_contrast": "paired lift versus pick-trader",
            "reference_agent": "pick-trader",
            "multiplicity_method": "holm-bonferroni",
            "alpha": 0.05,
            "holm_family_size": 1,
        },
        "budget_policy": {"spend_authorized": True},
    }
    ready_pricing = {
        "contract": "sota-v3",
        "contract_fingerprint": "test-fingerprint",
        "status": "frozen",
        "spend_authorized": True,
    }
    ready_issues = execution_authorization_issues(
        ready_lane,
        mode="panel",
        registry=ready_registry,
        manifest=ready_manifest,
        protocol=ready_protocol,
        pricing=ready_pricing,
    )
    assert not any("locked" in issue for issue in ready_issues)
    assert "smoke manifest format must be 'gm-bench-smoke-manifest-v1'" in ready_issues

    mismatched_registry = {**ready_registry, "contract_fingerprint": "wrong"}
    assert "sota-v3 model registry contract_fingerprint does not match the lane" in execution_authorization_issues(
        ready_lane,
        mode="panel",
        registry=mismatched_registry,
        manifest=ready_manifest,
        protocol=ready_protocol,
        pricing=ready_pricing,
    )
    mismatched_manifest = {**ready_manifest, "contract": "wrong"}
    assert "sota-v3 smoke manifest contract does not match the lane" in execution_authorization_issues(
        ready_lane,
        mode="panel",
        registry=ready_registry,
        manifest=mismatched_manifest,
        protocol=ready_protocol,
        pricing=ready_pricing,
    )
    blocked_protocol = {**ready_protocol, "budget_policy": {"spend_authorized": False}}
    assert "provider execution is locked by the publication protocol budget policy" in execution_authorization_issues(
        ready_lane,
        mode="panel",
        registry=ready_registry,
        manifest=ready_manifest,
        protocol=blocked_protocol,
        pricing=ready_pricing,
    )
    blocked_pricing = {**ready_pricing, "spend_authorized": False}
    assert "provider execution is locked by the pricing snapshot" in execution_authorization_issues(
        ready_lane,
        mode="panel",
        registry=ready_registry,
        manifest=ready_manifest,
        protocol=ready_protocol,
        pricing=blocked_pricing,
    )
    undersized_lane = {**ready_lane, "minimum_headline_models": 2}
    assert (
        "publication model registry has 1 models; minimum_headline_models requires 2"
        in execution_authorization_issues(
            undersized_lane,
            mode="panel",
            registry=ready_registry,
            manifest=ready_manifest,
            protocol=ready_protocol,
            pricing=ready_pricing,
        )
    )
    stale_profile = {**ready_registry, "profile": "tiny"}
    assert (
        "sota-v3 model registry profile does not match lane-authoritative observation_profile"
        in execution_authorization_issues(
            ready_lane,
            mode="panel",
            registry=stale_profile,
            manifest=ready_manifest,
            protocol=ready_protocol,
            pricing=ready_pricing,
        )
    )

    contradictory_lane = {
        **ready_lane,
        "statistical_panel_design": {
            "status": "frozen",
            "holm_family_size": 1,
            "target_effect_score_points": -100,
            "selected_allocation": {
                "seed_count": 8,
                "repeats": 1,
                "episodes_per_model": 8,
            },
        },
    }
    contradiction_issues = execution_authorization_issues(
        contradictory_lane,
        mode="panel",
        registry=ready_registry,
        manifest=ready_manifest,
        protocol=ready_protocol,
        pricing=ready_pricing,
    )
    assert "sota-v3 selected allocation repeats must match the lane" in contradiction_issues
    unresolved_statistics = {
        **ready_protocol,
        "statistical_analysis_plan": {
            **ready_protocol["statistical_analysis_plan"],
            "status": "unresolved-pre-data",
        },
    }
    assert "sota-v3 statistical analysis plan is not frozen" in execution_authorization_issues(
        ready_lane,
        mode="smoke",
        registry=ready_registry,
        manifest=ready_manifest,
        protocol=unresolved_statistics,
        pricing=ready_pricing,
    )
    statistical_mutations = (
        ("unit_of_inference", "episode", "sota-v3 unit_of_inference must be 'seed'"),
        (
            "primary_contrast",
            "model versus model",
            "sota-v3 primary_contrast must be 'paired lift versus pick-trader'",
        ),
        (
            "reference_agent",
            "value",
            "sota-v3 statistical reference_agent must match the lane reference_agent",
        ),
        (
            "multiplicity_method",
            "none",
            "sota-v3 multiplicity_method must be 'holm-bonferroni'",
        ),
        ("alpha", 0.10, "sota-v3 statistical alpha must be 0.05"),
    )
    for field, value, expected_issue in statistical_mutations:
        mutated_protocol = {
            **ready_protocol,
            "statistical_analysis_plan": {
                **ready_protocol["statistical_analysis_plan"],
                field: value,
            },
        }
        assert expected_issue in execution_authorization_issues(
            ready_lane,
            mode="smoke",
            registry=ready_registry,
            manifest=ready_manifest,
            protocol=mutated_protocol,
            pricing=ready_pricing,
        )
    oversized_exact_lane = {
        **ready_lane,
        "seed_panel": {**ready_lane["seed_panel"], "count": 21},
    }
    assert "sota-v3 exact-enumeration-sign-flip requires at most 20 seeds" in execution_authorization_issues(
        oversized_exact_lane,
        mode="smoke",
        registry=ready_registry,
        manifest=ready_manifest,
        protocol=ready_protocol,
        pricing=ready_pricing,
    )
    infeasible_lane = {
        **ready_lane,
        "seed_panel": {**ready_lane["seed_panel"], "count": 8},
    }
    infeasible_protocol = {
        **ready_protocol,
        "statistical_analysis_plan": {
            **ready_protocol["statistical_analysis_plan"],
            "holm_family_size": 8,
        },
    }
    infeasible_registry = {
        **ready_registry,
        "models": [{"id": f"demo-{index}"} for index in range(8)],
        "required_smokes": [f"demo-{index}" for index in range(8)],
    }
    infeasible_manifest = {
        **ready_manifest,
        "entries": {f"demo-{index}": {"accepted": True} for index in range(8)},
    }
    assert (
        "sota-v3 exact sign-flip test cannot clear Holm step one with the frozen 8-seed/8-model design"
        in execution_authorization_issues(
            infeasible_lane,
            mode="panel",
            registry=infeasible_registry,
            manifest=infeasible_manifest,
            protocol=infeasible_protocol,
            pricing=ready_pricing,
        )
    )


def test_cli_uses_a_disposable_directory_by_default() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/sota_v3_rehearsal.py", "--skip-web-build"],
        check=True,
        capture_output=True,
        text=True,
    )

    result = json.loads(completed.stdout)
    assert result["status"] == "passed"
    assert result["workdir"] == "<temporary-directory-removed>"
    assert result["artifacts"]["raw"] == "<temporary-directory-removed>"
    assert result["artifacts"]["compact"] == "<temporary-directory-removed>"


def test_rehearsal_can_reuse_an_explicit_workdir(tmp_path: Path) -> None:
    workdir = tmp_path / "rehearsal"
    first = run_rehearsal(workdir, run_web_build=False)
    second = run_rehearsal(workdir, run_web_build=False)

    assert first["status"] == second["status"] == "passed"
    assert first["artifacts"]["canonical_raw_sha256"] == second["artifacts"]["canonical_raw_sha256"]


def test_missing_node_modules_triggers_a_frozen_lockfile_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A clean checkout has no web/node_modules; the harness must install it.

    Before this was handled, `bun run build` exited 127 on a fresh clone and
    aborted the whole rehearsal, so the clean-checkout gate required by
    docs/PUBLISH_READINESS.md could not pass unassisted.
    """
    staging = tmp_path / "staging"
    (staging / "web").mkdir(parents=True)
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="40 packages installed")

    monkeypatch.setattr(rehearsal_mod.subprocess, "run", fake_run)
    result = rehearsal_mod._ensure_web_dependencies(staging, "bun")

    assert result["status"] == "installed"
    assert calls == [["bun", "install", "--frozen-lockfile"]]


def test_present_node_modules_is_reused_without_installing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staging = tmp_path / "staging"
    (staging / "web" / "node_modules").mkdir(parents=True)

    def fail_run(cmd, **kwargs):  # pragma: no cover - must not be reached
        raise AssertionError(f"unexpected install in a populated staging copy: {cmd}")

    monkeypatch.setattr(rehearsal_mod.subprocess, "run", fail_run)
    result = rehearsal_mod._ensure_web_dependencies(staging, "bun")

    assert result == {"status": "reused", "source": "staged-directory"}


def test_failed_install_raises_an_actionable_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    staging = tmp_path / "staging"
    (staging / "web").mkdir(parents=True)

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="lockfile out of date")

    monkeypatch.setattr(rehearsal_mod.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="lockfile out of date"):
        rehearsal_mod._ensure_web_dependencies(staging, "bun")
