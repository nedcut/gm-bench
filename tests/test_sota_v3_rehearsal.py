from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

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
    assert result["analysis"]["tier"] == 1
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


def test_panel_like_action_fails_closed_on_both_authorization_locks() -> None:
    lane = {
        "contract": "sota-v3",
        "preregistration_status": "provisional-blocked",
        "panel_design_status": "unresolved-pre-data",
        "output_policy_basis": "pending-live-route-smokes",
        "output_token_cap": None,
        "spend_authorized": False,
        "smoke_execution_authorized": False,
        "panel_execution_authorized": False,
    }
    registry = {
        "contract": "sota-v3",
        "selection_status": "provisional-blocked",
        "models": [],
        "required_smokes": [],
        "output_token_cap": None,
        "spend_authorized": False,
        "panel_execution_authorized": False,
    }
    manifest = {"status": "not-started", "accepted_for_panel": False, "entries": {}}

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
    assert "publication output_token_cap must be a positive frozen integer" in issues
    assert "publication output policy basis is not frozen" in issues
    assert "v3 smoke manifest is not accepted for panel execution" in issues
    ready_lane = {
        "contract": "sota-v3",
        "preregistration_status": "frozen",
        "panel_design_status": "frozen",
        "output_policy_basis": "fixed-safety-ceiling",
        "output_token_cap": 4096,
        "spend_authorized": True,
        "panel_execution_authorized": True,
    }
    ready_registry = {
        "contract": "sota-v3",
        "selection_status": "frozen",
        "models": [{"id": "demo"}],
        "required_smokes": ["demo"],
        "output_token_cap": 4096,
        "spend_authorized": True,
        "panel_execution_authorized": True,
    }
    frozen_record = {"contract": "sota-v3", "status": "frozen"}
    ready_issues = execution_authorization_issues(
        ready_lane,
        mode="panel",
        registry=ready_registry,
        manifest={"accepted_for_panel": True, "entries": {"demo": {"accepted": True}}},
        protocol=frozen_record,
        pricing=frozen_record,
    )
    assert not any("locked" in issue for issue in ready_issues)
    assert "smoke manifest format must be 'gm-bench-smoke-manifest-v1'" in ready_issues


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
