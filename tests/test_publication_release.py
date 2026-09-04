from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path

import pytest

from gm_bench.contract import contract_fingerprint, scaffold_fingerprint
from gm_bench.official import REDACTED_SEEDS_SENTINEL
from gm_bench.publication import canonical_sha256, v3_route_identity_sha256
from scripts.package_publication_release import _v3_analysis_rows, build_release, verify_archive


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
        "privacy_standard": {
            "data_classification": "synthetic-benchmark-no-personal-or-confidential-data",
            "provider_data_collection": "deny",
            "provider_training_use_allowed": False,
            "zero_data_retention_required": False,
        },
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
                    "zero_data_retention_endpoint": True,
                    "zero_data_retention_requirement_satisfied": True,
                    "accepted_at_utc": "2026-07-30T00:00:00Z",
                    "evidence_sha256": "e" * 64,
                },
            }
        },
    }
    route = {
        "route_identity_sha256": route_identity,
        "zero_data_retention_endpoint": True,
        "provider_policy": {},
    }
    evidence = {
        "format": "gm-bench-route-acceptance-evidence-v1",
        "contract": "sota-v3",
        "contract_fingerprint": fingerprint,
        "completion_calls": 0,
        "privacy_standard": registry["exact_route_acceptance"]["privacy_standard"],
        "official_policy_sources": [],
        "routes": {"demo-v3": route},
    }
    entry = registry["exact_route_acceptance"]["entries"]["demo-v3"]
    entry["route_evidence_sha256"] = canonical_sha256(route)
    entry["privacy_acceptance"]["evidence_sha256"] = canonical_sha256(
        {
            "route_identity_sha256": route_identity,
            "privacy_standard": evidence["privacy_standard"],
            "zero_data_retention_endpoint": True,
            "provider_policy": {},
            "official_policy_sources": [],
        }
    )
    evidence_path = repo / "results/analysis/route-evidence.json"
    _write_json(evidence_path, evidence)
    registry["exact_route_acceptance"]["evidence_artifact"] = "results/analysis/route-evidence.json"
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
        "models": [
            {
                "model_id": "demo-v3",
                "seed_count": seed_count,
                "raw_artifact_sha256": canonical_sha256(raw),
            }
        ],
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


def _replace_archived_json(archive_path: Path, member: str, payload: dict) -> None:
    with zipfile.ZipFile(archive_path) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    data = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    entries[member] = data
    manifest = json.loads(entries["manifest.json"])
    file_row = next(row for row in manifest["files"] if row["path"] == member)
    file_row["bytes"] = len(data)
    file_row["sha256"] = hashlib.sha256(data).hexdigest()
    entries["manifest.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    with zipfile.ZipFile(archive_path, "w") as archive:
        for name, entry in entries.items():
            archive.writestr(name, entry)


def _replace_archived_manifest(archive_path: Path, mutate) -> None:
    with zipfile.ZipFile(archive_path) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(entries["manifest.json"])
    mutate(manifest)
    entries["manifest.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    with zipfile.ZipFile(archive_path, "w") as archive:
        for name, entry in entries.items():
            archive.writestr(name, entry)


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


def test_v4_release_dispatch_is_registered_but_authorization_locked(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="sota-v4 release packaging is authorization-locked"):
        build_release(
            repo_root=tmp_path,
            run_dir=tmp_path,
            archive_path=tmp_path / "release-v4.zip",
            manifest_path=tmp_path / "manifest-v4.json",
            checksums_path=tmp_path / "SHA256SUMS-v4.txt",
            contract="sota-v4",
            release_date="2026-08-12",
        )

    assert not (tmp_path / "release-v4.zip").exists()


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


def test_v3_release_binds_analysis_seed_count_to_frozen_lane(tmp_path: Path) -> None:
    repo, run_dir = _v3_release_fixture(tmp_path)
    analysis_path = repo / "results/analysis/publication-panel-analysis-v3.json"
    analysis = json.loads(analysis_path.read_text())
    analysis["models"][0]["seed_count"] += 1
    _write_json(analysis_path, analysis)

    with pytest.raises(ValueError, match="seed_count must equal frozen lane seed_panel.count"):
        build_release(
            repo_root=repo,
            run_dir=run_dir,
            archive_path=tmp_path / "release-v3.zip",
            manifest_path=tmp_path / "manifest-v3.json",
            checksums_path=tmp_path / "SHA256SUMS-v3.txt",
            contract="sota-v3",
            release_date="2026-07-30",
        )


@pytest.mark.parametrize(
    ("private_field", "private_value", "message"),
    [
        (
            "per_seed",
            [{"seed": 987654321, "lift": -1.0}],
            "must not contain private per_seed evidence",
        ),
        ("tier", 1, "must not assign a tier"),
    ],
)
def test_v3_archive_verifier_revalidates_public_analysis(
    tmp_path: Path,
    private_field: str,
    private_value: object,
    message: str,
) -> None:
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
    analysis_member = "results/analysis/publication-panel-analysis-v3.json"
    with zipfile.ZipFile(archive_path) as archive:
        analysis = json.loads(archive.read(analysis_member))
    analysis["models"][0][private_field] = private_value
    _replace_archived_json(archive_path, analysis_member, analysis)

    with pytest.raises(ValueError, match=message):
        verify_archive(archive_path)


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


# --- sota-v5 accounted-for rule ------------------------------------------------


def _v5_analysis_fixture() -> tuple[dict, set[str], dict]:
    registered = {f"m{index:02d}" for index in range(16)}
    eligible_ids = sorted(registered)[:11]
    excluded_ids = sorted(registered)[11:]
    rows = [
        {
            "model_id": model_id,
            "seed_count": 29,
            "raw_artifact_sha256": "a" * 64,
            "within_seed_score_stddev": None,
            "within_seed_score_stddev_status": "unmeasured-one-repeat",
        }
        for model_id in eligible_ids
    ]
    register_entries = []
    excluded_rows = []
    for index, model_id in enumerate(excluded_ids):
        infrastructure = index >= 3
        digest = str(index) * 64
        register_entries.append(
            {
                "id": model_id,
                "status": "excluded-infrastructure-limit" if infrastructure else "ineligible-model-behavior",
                "rule": "frozen rule",
                "reason": "plain sentence",
                "attempts": 2 if infrastructure else 1,
                "decisions_completed": 0 if infrastructure else 100,
                "cost_usd": 0.0,
                "evidence": {"checkpoint": f"checkpoints/{model_id}--4096.json", "checkpoint_sha256": digest},
            }
        )
        excluded_rows.append(
            {
                "model_id": model_id,
                "status": register_entries[-1]["status"],
                "rule": "frozen rule",
                "reason": "plain sentence",
                "attempts": register_entries[-1]["attempts"],
                "decisions_completed": register_entries[-1]["decisions_completed"],
                "cost_usd": 0.0,
                "checkpoint_sha256": digest,
            }
        )
    analysis = {
        "benchmark_version": "sota-v5",
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
        "registered_model_count": 16,
        "eligible_model_count": 11,
        "holm_family_size": 16,
        "minimum_headline_models": 8,
        "accounted_for_model_count": 16,
        "config_errors": [],
        "missing_models": [],
        "rejected_artifacts": [],
        "within_seed_noise": {"statistic": "within_seed_score_stddev", "models_missing_the_statistic": []},
        "models": rows,
        "excluded_models": excluded_rows,
    }
    register = {
        "format": "gm-bench-panel-exclusion-register-v1",
        "schema_version": 1,
        "contract": "sota-v5",
        "status": "frozen",
        "entries": register_entries,
    }
    return analysis, registered, register


def test_v5_analysis_rows_accept_the_accounted_for_family() -> None:
    analysis, registered, register = _v5_analysis_fixture()
    rows = _v3_analysis_rows(analysis, registered, 29, contract="sota-v5", register=register, minimum_headline_models=8)
    assert sorted(rows) == sorted(registered)[:11]


def _mutate(payload: dict, path: tuple, value: object) -> None:
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda a, r: _mutate(a, ("holm_family_size",), 11), "holm_family_size must equal the registered model count"),
        (lambda a, r: _mutate(a, ("eligible_model_count",), 16), "eligible_model_count must equal the number"),
        (lambda a, r: _mutate(a, ("accounted_for_model_count",), 15), "accounted_for_model_count must equal"),
        (lambda a, r: a["excluded_models"].pop(), "every registered model must appear exactly once"),
        (lambda a, r: a["excluded_models"].append(dict(a["excluded_models"][0], model_id="m00")), "both eligible"),
        (lambda a, r: r["entries"].pop(), "exactly the committed exclusion register entries"),
        (
            lambda a, r: _mutate(r, ("entries", 0, "evidence", "checkpoint_sha256"), "f" * 64),
            "does not match the committed exclusion register entry",
        ),
        (
            lambda a, r: _mutate(r, ("entries", 0, "status"), "excluded-infrastructure-limit"),
            "does not match the committed exclusion register entry",
        ),
        (lambda a, r: _mutate(r, ("status",), "draft"), "exclusion register status must be frozen"),
        (lambda a, r: _mutate(a, ("within_seed_noise", "per_seed"), []), "within_seed_noise must be an aggregate"),
        (lambda a, r: _mutate(a, ("excluded_models", 0, "seeds"), [1]), "exactly the public register fields"),
        (lambda a, r: _mutate(a, ("models", 0, "per_seed"), []), "must not contain private per_seed evidence"),
        (lambda a, r: _mutate(a, ("unexpected",), 1), "unexpected public fields"),
        (lambda a, r: _mutate(a, ("minimum_headline_models",), 9), "must equal the protocol exclusion_policy floor"),
    ],
)
def test_v5_analysis_rows_reject_unaccounted_or_leaking_analysis(mutation, message: str) -> None:
    analysis, registered, register = _v5_analysis_fixture()
    mutation(analysis, register)
    with pytest.raises(ValueError, match=message):
        _v3_analysis_rows(analysis, registered, 29, contract="sota-v5", register=register, minimum_headline_models=8)


def test_v5_analysis_rows_enforce_the_protocol_headline_floor() -> None:
    analysis, registered, register = _v5_analysis_fixture()
    with pytest.raises(ValueError, match="below the headline floor of 12"):
        _v3_analysis_rows(analysis, registered, 29, contract="sota-v5", register=register, minimum_headline_models=12)
    with pytest.raises(ValueError, match="requires the committed exclusion register"):
        _v3_analysis_rows(analysis, registered, 29, contract="sota-v5", register=None, minimum_headline_models=8)


def test_v3_analysis_rows_still_reject_the_v5_public_fields() -> None:
    analysis, registered, register = _v5_analysis_fixture()
    analysis["benchmark_version"] = "sota-v3"
    with pytest.raises(ValueError, match="unexpected public fields"):
        _v3_analysis_rows(analysis, registered, 29, contract="sota-v3")


@pytest.fixture(scope="module")
def staged_v5_release(tmp_path_factory: pytest.TempPathFactory) -> dict:
    from scripts.sota_v5_rehearsal import stage_accounted_for_inputs

    return stage_accounted_for_inputs(tmp_path_factory.mktemp("staged-v5"))


def _copy_staged(staged: dict, tmp_path: Path) -> tuple[Path, Path]:
    staging = tmp_path / "repo-v5"
    results_root = tmp_path / "results-v5"
    shutil.copytree(staged["staging"], staging)
    shutil.copytree(staged["results_root"], results_root)
    return staging, results_root


def _build_v5(tmp_path: Path, staging: Path, results_root: Path) -> tuple[dict, Path]:
    archive = tmp_path / "release-v5.zip"
    manifest = build_release(
        repo_root=staging,
        run_dir=staging,
        archive_path=archive,
        manifest_path=tmp_path / "manifest-v5.json",
        checksums_path=tmp_path / "SHA256SUMS-v5.txt",
        contract="sota-v5",
        release_id="sota-v5-test-release",
        release_date="2026-09-03",
        results_root=results_root,
    )
    return manifest, archive


def test_v5_release_packages_the_accounted_for_family(staged_v5_release: dict, tmp_path: Path) -> None:
    staging, results_root = _copy_staged(staged_v5_release, tmp_path)
    manifest, archive = _build_v5(tmp_path, staging, results_root)
    register_entries = staged_v5_release["register_entries"]

    assert manifest["eligible_headline_models"] == 11
    assert manifest["diagnostic_models"] == 3
    assert manifest["excluded_models"] == 5
    assert manifest["exclusion_register"] == "config/sota_v5_panel_exclusions.json"
    statuses = {row["model_id"]: row["status"] for row in manifest["artifacts"]}
    assert sorted(k for k, v in statuses.items() if v == "excluded") == sorted(register_entries)
    assert sum(status == "headline" for status in statuses.values()) == 11
    paths = {row["path"]: row["role"] for row in manifest["files"]}
    assert paths["config/sota_v5_panel_exclusions.json"] == "exclusion-register"
    for model_id, entry in register_entries.items():
        artifact = next(row for row in manifest["artifacts"] if row["model_id"] == model_id)
        assert artifact["exclusion_status"] == entry["status"]
        assert artifact["checkpoint_sha256"] == entry["evidence"]["checkpoint_sha256"]
        assert artifact["rejection_reasons"] == [entry["reason"]]
        assert artifact["decisions"] == entry["decisions_completed"]
        assert artifact["cost_usd"] == entry["cost_usd"]
        assert artifact["raw_path"] is None
        if entry["status"] == "ineligible-model-behavior":
            assert artifact["compact_artifact"] == f"results/diagnostics/{model_id}.json"
            assert paths[artifact["compact_artifact"]] == "redacted-diagnostic-artifact"
        else:
            assert artifact["compact_artifact"] is None
    headline = next(row for row in manifest["artifacts"] if row["status"] == "headline")
    assert headline["compact_artifact"] == f"results/leaderboard/{headline['model_id']}.json"
    with zipfile.ZipFile(archive) as packaged:
        names = packaged.namelist()
        assert not any(name.startswith("raw/") for name in names)
        assert not any("/sota-v5/" in name for name in names)
        public_bytes = b"\n".join(packaged.read(name) for name in names)
    assert not any(str(seed).encode() in public_bytes for seed in staged_v5_release["seeds"])
    assert verify_archive(archive)["excluded_models"] == 5


def test_v5_release_reads_contract_scoped_artifact_directories(staged_v5_release: dict, tmp_path: Path) -> None:
    staging, results_root = _copy_staged(staged_v5_release, tmp_path)
    model_id = staged_v5_release["analysis"]["models"][0]["model_id"]
    scoped = results_root / "results/leaderboard/sota-v5" / f"{model_id}.json"
    top_level = results_root / "results/leaderboard" / f"{model_id}.json"
    top_level.write_bytes(scoped.read_bytes())
    scoped.unlink()

    with pytest.raises(FileNotFoundError):
        _build_v5(tmp_path, staging, results_root)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda c: c["publication"].__setitem__("source_checkpoint_sha256", "f" * 64), "source_checkpoint_sha256"),
        (lambda c: c["publication"].pop("source_checkpoint_sha256"), "source_checkpoint_sha256"),
        (lambda c: c["candidate"].__setitem__("episodes", [{"seed": 1}]), "episode traces must be removed"),
        (lambda c: c.__setitem__("seeds", [1, 2]), "top-level seeds must be redacted"),
    ],
)
def test_v5_release_rejects_unlinked_or_unredacted_diagnostics(
    staged_v5_release: dict, tmp_path: Path, mutate, message: str
) -> None:
    staging, results_root = _copy_staged(staged_v5_release, tmp_path)
    model_id = next(
        model_id
        for model_id, entry in staged_v5_release["register_entries"].items()
        if entry["status"] == "ineligible-model-behavior"
    )
    diagnostic_path = results_root / "results/diagnostics/sota-v5" / f"{model_id}.json"
    diagnostic = json.loads(diagnostic_path.read_text())
    mutate(diagnostic)
    diagnostic_path.write_text(json.dumps(diagnostic))

    with pytest.raises(ValueError, match=message):
        _build_v5(tmp_path, staging, results_root)
    assert not (tmp_path / "release-v5.zip").exists()


def test_v5_release_rejects_a_register_that_disagrees_with_the_analysis(
    staged_v5_release: dict, tmp_path: Path
) -> None:
    staging, results_root = _copy_staged(staged_v5_release, tmp_path)
    register_path = staging / "config/sota_v5_panel_exclusions.json"
    register = json.loads(register_path.read_text())
    register["entries"][0]["evidence"]["checkpoint_sha256"] = "f" * 64
    register_path.write_text(json.dumps(register))

    with pytest.raises(ValueError, match="does not match the committed exclusion register entry"):
        _build_v5(tmp_path, staging, results_root)


def test_v5_verifier_rejects_an_incomplete_manifest(staged_v5_release: dict, tmp_path: Path) -> None:
    staging, results_root = _copy_staged(staged_v5_release, tmp_path)
    _, archive = _build_v5(tmp_path, staging, results_root)

    def remove_headline(manifest: dict) -> None:
        manifest["artifacts"].remove(next(row for row in manifest["artifacts"] if row["status"] == "headline"))

    _replace_archived_manifest(archive, remove_headline)

    with pytest.raises(ValueError, match="every registered model exactly once"):
        verify_archive(archive)


def test_v5_verifier_binds_each_headline_manifest_row_to_the_analysis(staged_v5_release: dict, tmp_path: Path) -> None:
    staging, results_root = _copy_staged(staged_v5_release, tmp_path)
    _, archive = _build_v5(tmp_path, staging, results_root)

    def replace_hash(manifest: dict) -> None:
        headline = next(row for row in manifest["artifacts"] if row["status"] == "headline")
        headline["raw_canonical_sha256"] = "f" * 64
        headline["compact_raw_artifact_sha256"] = "f" * 64

    _replace_archived_manifest(archive, replace_hash)

    with pytest.raises(ValueError, match="does not match the archived analysis"):
        verify_archive(archive)


def test_v5_verifier_revalidates_the_archived_register_and_diagnostics(staged_v5_release: dict, tmp_path: Path) -> None:
    staging, results_root = _copy_staged(staged_v5_release, tmp_path)
    _, archive = _build_v5(tmp_path, staging, results_root)
    register_member = "config/sota_v5_panel_exclusions.json"
    with zipfile.ZipFile(archive) as packaged:
        register = json.loads(packaged.read(register_member))
    ineligible = next(entry for entry in register["entries"] if entry["status"] == "ineligible-model-behavior")
    diagnostic_member = f"results/diagnostics/{ineligible['id']}.json"

    drifted = json.loads(json.dumps(register))
    drifted["entries"][0]["status"] = "excluded-infrastructure-limit"
    drifted_archive = tmp_path / "drifted.zip"
    shutil.copy(archive, drifted_archive)
    _replace_archived_json(drifted_archive, register_member, drifted)
    with pytest.raises(ValueError, match="does not match the committed exclusion register entry"):
        verify_archive(drifted_archive)

    with zipfile.ZipFile(archive) as packaged:
        diagnostic = json.loads(packaged.read(diagnostic_member))
    diagnostic["publication"]["source_checkpoint_sha256"] = "f" * 64
    unlinked_archive = tmp_path / "unlinked.zip"
    shutil.copy(archive, unlinked_archive)
    _replace_archived_json(unlinked_archive, diagnostic_member, diagnostic)
    with pytest.raises(ValueError, match="source_checkpoint_sha256"):
        verify_archive(unlinked_archive)

    with zipfile.ZipFile(archive) as packaged:
        analysis = json.loads(packaged.read("results/analysis/publication-panel-analysis-v5.json"))
    analysis["excluded_models"][0]["seeds"] = [1]
    leaking_archive = tmp_path / "leaking.zip"
    shutil.copy(archive, leaking_archive)
    _replace_archived_json(leaking_archive, "results/analysis/publication-panel-analysis-v5.json", analysis)
    with pytest.raises(ValueError, match="exactly the public register fields"):
        verify_archive(leaking_archive)
