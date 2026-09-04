from __future__ import annotations

from pathlib import Path

from scripts.sota_v5_rehearsal import run_rehearsal, synthetic_private_artifact


def frozen_site_bytes() -> bytes:
    return Path("web/src/data/leaderboard.json").read_bytes()


def test_synthetic_private_v5_artifact_is_deterministic() -> None:
    assert synthetic_private_artifact() == synthetic_private_artifact()


def test_v5_rehearsal_is_zero_spend_locked_and_leaves_v2_site_unchanged(tmp_path: Path) -> None:
    frozen_site = Path("web/src/data/leaderboard.json").read_bytes()
    result = run_rehearsal(tmp_path / "rehearsal", run_web_build=False)

    assert result["status"] == "passed"
    assert result["mode"] == "synthetic-private"
    assert result["evidence_class"] == "synthetic-non-evidence"
    assert result["spend_usd"] == 0.0
    assert result["analysis"]["publication_ready"] is False
    assert "authorization" in result["analysis"]["authorization_lock"]
    assert result["release"]["registered"] is True
    assert result["site_data_build"] == {
        "status": "passed",
        "contract": "sota-v2",
        "v5_selected": False,
        "matches_checked_in_dataset": True,
    }
    assert result["web_build"] == {"status": "skipped"}
    assert Path(result["artifacts"]["raw"]).is_file()
    assert Path(result["artifacts"]["redacted"]).is_file()
    assert Path("web/src/data/leaderboard.json").read_bytes() == frozen_site


def test_v5_rehearsal_proves_the_accounted_for_release_without_writing_the_records(tmp_path: Path) -> None:
    guarded = [
        Path("config/sota_v5_lane.json"),
        Path("config/sota_v5_models.json"),
        Path("config/sota_v5_publication_protocol.json"),
        Path("config/sota_v5_pricing_snapshot.json"),
        Path("config/sota_v5_panel_exclusions.json"),
    ]
    before = [path.read_bytes() for path in guarded]
    result = run_rehearsal(tmp_path / "rehearsal", run_web_build=False)

    proof = result["accounted_for_release"]
    assert proof["status"] == "passed"
    assert proof["records_authorized_in_memory_only"] is True
    assert proof["analysis"] == {
        "publication_ready": True,
        "status": "complete",
        "eligible_model_count": 11,
        "accounted_for_model_count": 16,
        "holm_family_size": 16,
        "registered_model_count": 16,
        "minimum_headline_models": 8,
    }
    assert proof["release"]["eligible_headline_models"] == 11
    assert proof["release"]["diagnostic_models"] == 3
    assert proof["release"]["excluded_models"] == 5
    assert proof["release"]["verified"] is True
    assert Path(proof["release"]["archive"]).is_file()
    assert [path.read_bytes() for path in guarded] == before
    assert Path("web/src/data/leaderboard.json").read_bytes() == frozen_site_bytes()
