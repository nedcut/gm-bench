from __future__ import annotations

from pathlib import Path

from scripts.sota_v4_rehearsal import run_rehearsal, synthetic_private_artifact


def test_synthetic_private_v4_artifact_is_deterministic() -> None:
    assert synthetic_private_artifact() == synthetic_private_artifact()


def test_v4_rehearsal_is_zero_spend_locked_and_excluded_from_v2_site(tmp_path: Path) -> None:
    frozen_site_bytes = Path("web/src/data/leaderboard.json").read_bytes()

    result = run_rehearsal(tmp_path / "rehearsal", run_web_build=False)

    assert result["status"] == "passed"
    assert result["mode"] == "synthetic-private"
    assert result["spend_usd"] == 0.0
    assert result["policy_selection"] == {
        "sota_v4": "accepted",
        "sota_v3": "rejected",
        "sota_v2": "rejected",
    }
    assert result["analysis"]["publication_ready"] is False
    assert "authorization-locked" in result["analysis"]["authorization_lock"]
    assert result["release"]["registered"] is True
    assert "authorization-locked" in result["release"]["authorization_lock"]
    assert result["site_data_build"] == {
        "status": "passed",
        "contract": "sota-v2",
        "synthetic_sota_v4_excluded": True,
        "matches_checked_in_dataset": True,
        "shared_row_ingestion": "passed",
        "public_sota_v4_strategy_selected": False,
    }
    assert result["web_build"] == {"status": "skipped"}
    assert Path(result["artifacts"]["raw"]).is_file()
    assert Path(result["artifacts"]["redacted"]).is_file()
    assert Path("web/src/data/leaderboard.json").read_bytes() == frozen_site_bytes
