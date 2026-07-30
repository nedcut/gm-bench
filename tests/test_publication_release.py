from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from gm_bench.contract import contract_fingerprint, scaffold_fingerprint
from gm_bench.official import REDACTED_SEEDS_SENTINEL
from gm_bench.publication import canonical_sha256, v3_route_identity_sha256
from scripts.package_publication_release import build_release, verify_archive


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def _release_fixture(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    run_dir = tmp_path / "run"
    registry = {
        "contract": "sota-v2",
        "output_token_cap": 4096,
        "models": [
            {
                "id": "demo",
                "provider": "openrouter",
                "model": "demo/model",
                "upstream_provider": "Demo",
            }
        ],
    }
    raw = {
        "seeds": [987654321],
        "candidate": {
            "summary": {
                "decisions": 4,
                "mean_score": 12.5,
                "usage": {
                    "decisions_with_usage": 4,
                    "cost_decisions": 4,
                    "cost_usd": 0.01,
                },
            }
        },
    }
    analysis = {
        "models": [{"model_id": "demo"}],
        "rejected_artifacts": [],
    }
    _write_json(repo / "config/sota_v2_models.json", registry)
    for name in ("sota_v2_lane.json", "publication_protocol.json", "sota_v2_smoke_manifest.json"):
        _write_json(repo / "config" / name, {"fixture": True})
    _write_json(repo / "results/analysis/publication-panel-analysis.json", analysis)
    _write_json(
        repo / "results/leaderboard/demo.json",
        {"publication": {"raw_artifact_sha256": canonical_sha256(raw)}},
    )
    _write_json(run_dir / "raw/demo--4096.json", raw)
    _write_json(run_dir / "run-state.json", {"phase": "panel"})
    return repo, run_dir


def _v3_release_fixture(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo-v3"
    run_dir = tmp_path / "run-v3"
    fingerprint = contract_fingerprint()
    model = {
        "id": "demo-v3",
        "provider": "openrouter",
        "model": "demo/v3",
        "canonical_slug": "demo/v3",
        "upstream_provider": "Demo",
        "upstream_provider_slug": "demo",
        "endpoint_tag": "demo",
        "endpoint_name": "Demo | demo/v3",
        "reasoning_policy": "disabled",
        "reasoning_effort": None,
    }
    registry = {
        "contract": "sota-v3",
        "contract_fingerprint": fingerprint,
        "lane": "api",
        "provider": "openrouter",
        "profile": "compact",
        "preset": "leaderboard",
        "session": False,
        "repeats": 1,
        "output_token_cap": 4096,
        "selection_status": "frozen",
        "spend_authorized": True,
        "panel_execution_authorized": True,
        "publication_authorized": True,
        "required_smokes": ["demo-v3"],
        "models": [model],
    }
    route_identity = v3_route_identity_sha256(registry, model)
    registry["exact_route_acceptance"] = {
        "status": "accepted",
        "entries": {
            "demo-v3": {
                "route_identity_sha256": route_identity,
                "authenticated": True,
                "verified_at_utc": "2026-07-30T00:00:00Z",
                "route_evidence_sha256": "d" * 64,
                "privacy_acceptance": {
                    "status": "accepted",
                    "route_identity_sha256": route_identity,
                    "data_collection_policy_accepted": True,
                    "retention_policy_accepted": True,
                    "training_use_policy_accepted": True,
                    "zero_data_retention_policy_accepted": True,
                    "accepted_at_utc": "2026-07-30T00:00:00Z",
                    "evidence_sha256": "e" * 64,
                },
            }
        },
    }
    seed_count = 6
    lane = {
        "contract": "sota-v3",
        "contract_fingerprint": fingerprint,
        "execution_profile_authority": "lane",
        "headline_lane": "api",
        "provider": "openrouter",
        "observation_profile": "compact",
        "preset": "leaderboard",
        "session": False,
        "repeats": 1,
        "preregistration_status": "frozen",
        "panel_design_status": "frozen",
        "minimum_headline_models": 1,
        "reference_agent": "pick-trader",
        "output_token_cap": 4096,
        "output_budget_status": "frozen-native-reasoning-cap",
        "output_policy_basis": "fixed-safety-ceiling",
        "cap_pressure_threshold_tokens": 3072,
        "fallback_output_token_cap": 8192,
        "spend_authorized": True,
        "smoke_execution_authorized": True,
        "panel_execution_authorized": True,
        "publication_authorized": True,
        "statistical_panel_design": {
            "status": "frozen",
            "holm_family_size": 1,
            "target_effect_score_points": -100,
            "selected_allocation": {
                "seed_count": seed_count,
                "repeats": 1,
                "episodes_per_model": seed_count,
            },
        },
        "seed_panel": {
            "status": "frozen",
            "name": "private-env",
            "count": seed_count,
            "sha256": "b" * 64,
            "hiding_commitment_sha256": "c" * 64,
        },
    }
    protocol = {
        "contract": "sota-v3",
        "contract_fingerprint": fingerprint,
        "status": "frozen",
        "publication_authorized": True,
        "budget_policy": {"spend_authorized": True},
        "output_policy": {
            "output_token_cap": 4096,
            "cap_pressure_threshold_tokens": 3072,
            "fallback_output_token_cap": 8192,
        },
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
            "target_effect_score_points": -100,
        },
    }
    pricing = {
        "contract": "sota-v3",
        "contract_fingerprint": fingerprint,
        "status": "frozen",
        "spend_authorized": True,
        "publication_authorized": True,
        "planning_assumptions": {
            "expected_output_tokens_per_decision": 4096,
            "cost_contingency_multiplier": 1.2,
        },
    }
    smoke_manifest = {
        "format": "gm-bench-smoke-manifest-v1",
        "schema_version": 1,
        "contract": "sota-v3",
        "contract_fingerprint": fingerprint,
        "status": "accepted",
        "accepted_for_panel": True,
        "entries": {
            "demo-v3": {
                "provider": "openrouter",
                "model": "demo/v3",
                "upstream_provider": "Demo",
                "upstream_provider_slug": "demo",
                "endpoint_tag": "demo",
                "endpoint_name": "Demo | demo/v3",
                "reasoning_policy": "disabled",
                "reasoning_effort": None,
                "output_token_cap": 4096,
                "api_calls": 4,
                "calls_with_finish_reason": 4,
                "decisions_with_usage": 4,
                "cost_decisions": 4,
                "protocol_repair_attempts": 0,
                "protocol_repairs_succeeded": 0,
                "truncated_calls": 0,
                "max_output_tokens_per_call": 100,
                "reasoning_tokens": 0,
                "decision_failure_rate": 0,
                "strict_fallback": True,
                "contract_fingerprint": fingerprint,
                "scaffold_fingerprint": scaffold_fingerprint("openrouter"),
                "artifact_sha256": "a" * 64,
                "accepted": True,
            }
        },
    }
    raw = {
        "candidate": {
            "summary": {
                "decisions": 20,
                "mean_score": 15.5,
                "usage": {
                    "decisions_with_usage": 20,
                    "cost_decisions": 20,
                    "cost_usd": 0.02,
                },
            }
        }
    }
    analysis = {
        "benchmark_version": "sota-v3",
        "status": "complete",
        "analysis_mode": "reference-only",
        "redaction": {
            "private_seed_panel": True,
            "seed_identifiers_included": False,
            "per_seed_rows_included": False,
            "public_view": "aggregate-only",
        },
        "publication_ready": True,
        "model_tiering": {"status": "not-supported"},
        "registered_model_count": 1,
        "eligible_model_count": 1,
        "holm_family_size": 1,
        "config_errors": [],
        "missing_models": [],
        "models": [{"model_id": "demo-v3", "seed_count": 15, "raw_artifact_sha256": canonical_sha256(raw)}],
        "rejected_artifacts": [],
    }
    _write_json(repo / "config/sota_v3_models.json", registry)
    _write_json(repo / "config/sota_v3_lane.json", lane)
    _write_json(repo / "config/sota_v3_publication_protocol.json", protocol)
    _write_json(repo / "config/sota_v3_smoke_manifest.json", smoke_manifest)
    _write_json(repo / "config/sota_v3_pricing_snapshot.json", pricing)
    _write_json(repo / "results/analysis/publication-panel-analysis-v3.json", analysis)
    _write_json(
        repo / "results/leaderboard/demo-v3.json",
        {
            "seeds": REDACTED_SEEDS_SENTINEL,
            "run_info": {"seed_panel": {"name": "private-env"}},
            "candidate": {
                "seeds": REDACTED_SEEDS_SENTINEL,
                "episodes": [],
                "summary": raw["candidate"]["summary"],
            },
            "baselines": [{"seeds": REDACTED_SEEDS_SENTINEL, "episodes": []}],
            "paired": {"per_seed": []},
            "redaction": {"applied": True},
            "publication": {"raw_artifact_sha256": canonical_sha256(raw)},
        },
    )
    _write_json(run_dir / "raw/demo-v3--4096.json", raw)
    return repo, run_dir


def test_release_archive_is_deterministic_and_verifiable(tmp_path: Path) -> None:
    repo, run_dir = _release_fixture(tmp_path)
    archive = tmp_path / "release.zip"
    generated: list[bytes] = []
    for _ in range(2):
        build_release(
            repo_root=repo,
            run_dir=run_dir,
            archive_path=archive,
            manifest_path=tmp_path / "manifest.json",
            checksums_path=tmp_path / "SHA256SUMS.txt",
        )
        generated.append(archive.read_bytes())

    assert generated[0] == generated[1]
    manifest = verify_archive(archive, repo_root=repo)
    assert manifest["eligible_headline_models"] == 1
    assert manifest["diagnostic_models"] == 0
    assert manifest["artifacts"][0]["compact_artifact"] == "results/leaderboard/demo.json"


def test_release_build_rejects_compact_raw_hash_mismatch(tmp_path: Path) -> None:
    repo, run_dir = _release_fixture(tmp_path)
    _write_json(repo / "results/leaderboard/demo.json", {"publication": {"raw_artifact_sha256": "0" * 64}})

    try:
        build_release(
            repo_root=repo,
            run_dir=run_dir,
            archive_path=tmp_path / "release.zip",
            manifest_path=tmp_path / "manifest.json",
            checksums_path=tmp_path / "SHA256SUMS.txt",
        )
    except ValueError as exc:
        assert "does not hash-link" in str(exc)
    else:
        raise AssertionError("expected compact/raw mismatch to fail")


def test_v3_release_packages_versioned_inputs_without_model_tiers(tmp_path: Path) -> None:
    repo, run_dir = _v3_release_fixture(tmp_path)
    archive = tmp_path / "release-v3.zip"
    manifest = build_release(
        repo_root=repo,
        run_dir=run_dir,
        archive_path=archive,
        manifest_path=tmp_path / "manifest-v3.json",
        checksums_path=tmp_path / "SHA256SUMS-v3.txt",
        contract="sota-v3",
        release_id="sota-v3-test-release",
        release_date="2026-07-30",
    )

    assert manifest["contract"] == "sota-v3"
    assert manifest["release_id"] == "sota-v3-test-release"
    assert any(row["path"] == "config/sota_v3_publication_protocol.json" for row in manifest["files"])
    assert any(row["path"] == "config/sota_v3_pricing_snapshot.json" for row in manifest["files"])
    assert any(row["path"] == "results/analysis/publication-panel-analysis-v3.json" for row in manifest["files"])
    assert any(row["path"] == "results/leaderboard/demo-v3.json" for row in manifest["files"])
    assert "no model-to-model tiers" in manifest["notes"][-1]
    assert "excluded" in manifest["notes"][0]
    with zipfile.ZipFile(archive) as packaged:
        assert not any(name.startswith("raw/") for name in packaged.namelist())
        compact = json.loads(packaged.read("results/leaderboard/demo-v3.json"))
        assert compact["seeds"] == REDACTED_SEEDS_SENTINEL
        assert compact["paired"]["per_seed"] == []
        public_analysis = packaged.read("results/analysis/publication-panel-analysis-v3.json")
        assert b'"per_seed"' not in public_analysis
        public_bytes = b"\n".join(packaged.read(name) for name in packaged.namelist())
        assert b"987654321" not in public_bytes
    assert verify_archive(archive)["artifacts"][0]["model_id"] == "demo-v3"


@pytest.mark.parametrize(
    ("filename", "field_path", "value", "message"),
    [
        ("sota_v3_lane.json", ("preregistration_status",), "provisional-pre-smoke", "provider execution is locked"),
        ("sota_v3_models.json", ("selection_status",), "provisional-blocked", "model registry is frozen"),
        (
            "sota_v3_models.json",
            ("exact_route_acceptance", "status"),
            "unresolved",
            "exact-route acceptance status",
        ),
        (
            "sota_v3_models.json",
            ("exact_route_acceptance", "entries", "demo-v3", "privacy_acceptance", "status"),
            "unresolved",
            "privacy acceptance is unresolved",
        ),
        ("sota_v3_lane.json", ("seed_panel", "status"), "pending-authorized-generation", "seed panel identity"),
        ("sota_v3_smoke_manifest.json", ("accepted_for_panel",), False, "smoke manifest is not accepted"),
        (
            "sota_v3_smoke_manifest.json",
            ("entries", "demo-v3", "accepted"),
            False,
            "smoke manifest entry 'demo-v3' is not accepted",
        ),
        ("sota_v3_publication_protocol.json", ("status",), "provisional", "publication protocol is not frozen"),
        ("sota_v3_pricing_snapshot.json", ("status",), "provisional", "pricing snapshot is not frozen"),
        (
            "sota_v3_lane.json",
            ("output_budget_status",),
            "provisional-pre-smoke-validation",
            "output-budget state",
        ),
        ("sota_v3_lane.json", ("publication_authorized",), False, "lane publication_authorized"),
        ("sota_v3_models.json", ("publication_authorized",), False, "model registry publication_authorized"),
        (
            "sota_v3_publication_protocol.json",
            ("publication_authorized",),
            False,
            "publication protocol publication_authorized",
        ),
        (
            "sota_v3_pricing_snapshot.json",
            ("publication_authorized",),
            False,
            "pricing snapshot publication_authorized",
        ),
    ],
)
def test_v3_release_fails_closed_before_writing_when_authorization_is_incomplete(
    tmp_path: Path,
    filename: str,
    field_path: tuple[str, ...],
    value: object,
    message: str,
) -> None:
    repo, run_dir = _v3_release_fixture(tmp_path)
    config_path = repo / "config" / filename
    config = json.loads(config_path.read_text())
    target = config
    for field in field_path[:-1]:
        target = target[field]
    target[field_path[-1]] = value
    _write_json(config_path, config)
    archive = tmp_path / "release-v3.zip"
    manifest = tmp_path / "manifest-v3.json"
    checksums = tmp_path / "SHA256SUMS-v3.txt"

    with pytest.raises(ValueError, match=message):
        build_release(
            repo_root=repo,
            run_dir=run_dir,
            archive_path=archive,
            manifest_path=manifest,
            checksums_path=checksums,
            contract="sota-v3",
            release_date="2026-07-30",
        )

    assert not archive.exists()
    assert not manifest.exists()
    assert not checksums.exists()


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("benchmark_version", None, "benchmark_version"),
        ("status", "incomplete", "complete and publication_ready"),
        ("publication_ready", False, "complete and publication_ready"),
        ("analysis_mode", "pairwise-tiers", "reference-only"),
        ("model_tiering", {"status": "assigned"}, "not-supported"),
        ("config_errors", ["bad config"], "config_errors"),
    ],
)
def test_v3_release_rejects_nonpublishable_analysis(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    repo, run_dir = _v3_release_fixture(tmp_path)
    analysis_path = repo / "results/analysis/publication-panel-analysis-v3.json"
    analysis = json.loads(analysis_path.read_text())
    analysis[field] = value
    _write_json(analysis_path, analysis)

    with pytest.raises(ValueError, match=message):
        build_release(
            repo_root=repo,
            run_dir=run_dir,
            archive_path=tmp_path / "release-v3.zip",
            manifest_path=tmp_path / "manifest-v3.json",
            checksums_path=tmp_path / "SHA256SUMS-v3.txt",
            contract="sota-v3",
            release_date="2026-07-30",
        )


def test_v3_release_rejects_tiered_or_unlinked_public_evidence(tmp_path: Path) -> None:
    repo, run_dir = _v3_release_fixture(tmp_path)
    analysis_path = repo / "results/analysis/publication-panel-analysis-v3.json"
    analysis = json.loads(analysis_path.read_text())
    analysis["models"][0]["tier"] = 1
    analysis["models"][0]["raw_artifact_sha256"] = "0" * 64
    _write_json(analysis_path, analysis)

    with pytest.raises(ValueError, match="must not assign a tier"):
        build_release(
            repo_root=repo,
            run_dir=run_dir,
            archive_path=tmp_path / "release-v3.zip",
            manifest_path=tmp_path / "manifest-v3.json",
            checksums_path=tmp_path / "SHA256SUMS-v3.txt",
            contract="sota-v3",
            release_date="2026-07-30",
        )

    analysis["models"][0].pop("tier")
    _write_json(analysis_path, analysis)
    with pytest.raises(ValueError, match="must match the analysis row"):
        build_release(
            repo_root=repo,
            run_dir=run_dir,
            archive_path=tmp_path / "release-v3.zip",
            manifest_path=tmp_path / "manifest-v3.json",
            checksums_path=tmp_path / "SHA256SUMS-v3.txt",
            contract="sota-v3",
            release_date="2026-07-30",
        )


def test_v3_release_rejects_analysis_with_private_per_seed_evidence(tmp_path: Path) -> None:
    repo, run_dir = _v3_release_fixture(tmp_path)
    analysis_path = repo / "results/analysis/publication-panel-analysis-v3.json"
    analysis = json.loads(analysis_path.read_text())
    analysis["models"][0]["per_seed"] = [
        {
            "seed": 987654321,
            "candidate_mean_over_repeats": 1.0,
            "pick_trader_score": 2.0,
            "lift": -1.0,
        }
    ]
    _write_json(analysis_path, analysis)

    with pytest.raises(ValueError, match="must not contain private per_seed evidence"):
        build_release(
            repo_root=repo,
            run_dir=run_dir,
            archive_path=tmp_path / "release-v3.zip",
            manifest_path=tmp_path / "manifest-v3.json",
            checksums_path=tmp_path / "SHA256SUMS-v3.txt",
            contract="sota-v3",
            release_date="2026-07-30",
        )


def test_v3_release_rejects_unredacted_private_artifact(tmp_path: Path) -> None:
    repo, run_dir = _v3_release_fixture(tmp_path)
    compact_path = repo / "results/leaderboard/demo-v3.json"
    compact = json.loads(compact_path.read_text())
    compact["seeds"] = [123]
    compact["candidate"]["episodes"] = [{"seed": 123}]
    _write_json(compact_path, compact)

    with pytest.raises(ValueError, match="unsafe"):
        build_release(
            repo_root=repo,
            run_dir=run_dir,
            archive_path=tmp_path / "release-v3.zip",
            manifest_path=tmp_path / "manifest-v3.json",
            checksums_path=tmp_path / "SHA256SUMS-v3.txt",
            contract="sota-v3",
            release_date="2026-07-30",
        )


@pytest.mark.parametrize("location", ["candidate", "baseline"])
def test_v3_release_rejects_nested_private_seed_values(tmp_path: Path, location: str) -> None:
    repo, run_dir = _v3_release_fixture(tmp_path)
    compact_path = repo / "results/leaderboard/demo-v3.json"
    compact = json.loads(compact_path.read_text())
    target = compact["candidate"] if location == "candidate" else compact["baselines"][0]
    target["seeds"] = [123, 456]
    _write_json(compact_path, compact)

    with pytest.raises(ValueError, match=f"{location} seeds must be redacted"):
        build_release(
            repo_root=repo,
            run_dir=run_dir,
            archive_path=tmp_path / "release-v3.zip",
            manifest_path=tmp_path / "manifest-v3.json",
            checksums_path=tmp_path / "SHA256SUMS-v3.txt",
            contract="sota-v3",
            release_date="2026-07-30",
        )


@pytest.mark.parametrize("location", ["candidate", "baseline"])
def test_v3_release_verifier_rejects_nested_private_seed_values(tmp_path: Path, location: str) -> None:
    repo, run_dir = _v3_release_fixture(tmp_path)
    archive_path = tmp_path / "release-v3.zip"
    build_release(
        repo_root=repo,
        run_dir=run_dir,
        archive_path=archive_path,
        manifest_path=tmp_path / "manifest-v3.json",
        checksums_path=tmp_path / "SHA256SUMS-v3.txt",
        contract="sota-v3",
        release_date="2026-07-30",
    )
    with zipfile.ZipFile(archive_path) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    compact_path = "results/leaderboard/demo-v3.json"
    compact = json.loads(entries[compact_path])
    target = compact["candidate"] if location == "candidate" else compact["baselines"][0]
    target["seeds"] = [123, 456]
    compact_bytes = (json.dumps(compact, indent=2, sort_keys=True) + "\n").encode()
    entries[compact_path] = compact_bytes
    manifest = json.loads(entries["manifest.json"])
    file_row = next(row for row in manifest["files"] if row["path"] == compact_path)
    file_row["bytes"] = len(compact_bytes)
    file_row["sha256"] = hashlib.sha256(compact_bytes).hexdigest()
    entries["manifest.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    with zipfile.ZipFile(archive_path, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)

    with pytest.raises(ValueError, match=f"{location} seeds must be redacted"):
        verify_archive(archive_path)


def test_v3_release_requires_explicit_release_date(tmp_path: Path) -> None:
    repo, run_dir = _v3_release_fixture(tmp_path)

    try:
        build_release(
            repo_root=repo,
            run_dir=run_dir,
            archive_path=tmp_path / "release-v3.zip",
            manifest_path=tmp_path / "manifest-v3.json",
            checksums_path=tmp_path / "SHA256SUMS-v3.txt",
            contract="sota-v3",
        )
    except ValueError as exc:
        assert "release_date" in str(exc)
    else:
        raise AssertionError("expected v3 packaging without a release date to fail")
