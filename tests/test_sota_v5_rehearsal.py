from __future__ import annotations

from pathlib import Path

from scripts.sota_v5_rehearsal import run_rehearsal, synthetic_private_artifact


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
