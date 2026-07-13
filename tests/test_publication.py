from __future__ import annotations

import json
import subprocess
from pathlib import Path

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
    return {"candidate": {"episodes": [episode]}, "baselines": [{"episodes": [episode]}]}


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


def test_budget_analysis_refuses_empty_sweep(tmp_path: Path) -> None:
    output = tmp_path / "analysis.json"
    subprocess.run(["python3", "scripts/analyze_output_budget.py", "--output", str(output)], check=True)
    result = json.loads(output.read_text())
    assert result["status"] == "incomplete"
    assert result["publishable_ranking"] is False
