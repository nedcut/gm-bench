"""The committed decision-lane analysis is aggregate-only and matches its artifact.

The raw artifact behind it stays with the operator, so ``--check`` cannot run
in CI; what CI can hold is that the published numbers agree with the redacted
artifact and that no private key leaked.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from decision_lane_analysis import PRIVATE_KEYS, _contains_private_keys, render_markdown  # noqa: E402

ARTIFACT = ROOT / "results" / "leaderboard" / "decision-lane" / "typesafe-jev-1.13-openrouter.json"
ANALYSIS_JSON = ROOT / "results" / "analysis" / "decision-lane-typesafe-jev-1.13-openrouter.json"
ANALYSIS_MD = ROOT / "results" / "analysis" / "decision-lane-typesafe-jev-1.13-openrouter.md"


def test_analysis_carries_no_private_keys() -> None:
    analysis = json.loads(ANALYSIS_JSON.read_text())
    assert not _contains_private_keys(analysis)
    assert "seeds" in PRIVATE_KEYS and "per_seed" in PRIVATE_KEYS
    assert analysis["redaction"]["public_view"] == "aggregate-only"
    assert analysis["family"]["holm_family"] is None


def test_analysis_matches_the_redacted_artifact() -> None:
    analysis = json.loads(ANALYSIS_JSON.read_text())
    artifact = json.loads(ARTIFACT.read_text())
    row = analysis["row"]
    summary = artifact["candidate"]["summary"]
    run_info = artifact["run_info"]
    assert row["id"] == artifact["agent"]
    assert row["mean_score"] == summary["mean_score"]
    assert row["illegal_actions"] == summary["illegal_actions"]
    assert row["decisions"] == summary["decisions"]
    assert row["scaffold_fingerprint"] == run_info["scaffold_fingerprint"]
    assert row["contract_fingerprint"] == run_info["benchmark_contract"]["contract_fingerprint"]
    assert row["seed_panel"]["sha256"] == run_info["seed_panel"]["sha256"]
    assert row["raw_artifact_sha256"] == artifact["publication"]["raw_artifact_sha256"]
    assert analysis["panel_mean_contrast"]["paired_lift_mean"] == artifact["paired"]["paired_lift_mean"]
    assert analysis["efficiency"]["cost_usd"] == round(summary["usage"]["cost_usd"], 5)
    pick = analysis["pick_trader_contrast"]
    assert pick["seeds_total"] == run_info["seed_panel"]["count"]
    assert abs(pick["full_panel_mean_lift"] - artifact["paired"]["best_baseline"]["paired_lift_mean"]) < 1e-3


def test_markdown_is_rendered_from_the_committed_json() -> None:
    analysis = json.loads(ANALYSIS_JSON.read_text())
    assert ANALYSIS_MD.read_text() == render_markdown(analysis)
