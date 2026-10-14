"""Check the Replay showcase against every currently published comparable episode."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def validate_best_run() -> None:
    leaderboard = json.loads((ROOT / "web/src/data/leaderboard.json").read_text())
    summary = json.loads((ROOT / "web/src/data/best-run-summary.json").read_text())
    rows = leaderboard["agentic_lane"]
    candidates = []
    first_contract = json.loads((ROOT / rows[0]["artifact_path"]).read_text())["contract"]
    for row in rows:
        artifact = json.loads((ROOT / row["artifact_path"]).read_text())
        # A record claim is restricted to the site's published, matched panel.
        assert artifact["grade"] == row["grade"] == "panel"
        assert artifact["lane"] == row["lane"] == "agentic"
        assert artifact["seasons"] == row["seasons"] == summary["seasons"]
        assert artifact["contract"] == first_contract
        assert row["contract"] == rows[0]["contract"]
        assert all(artifact["contract"][key] == value for key, value in row["contract"].items())
        assert artifact["panel"]["sha256"] == row["panel"]["sha256"] == rows[0]["panel"]["sha256"]
        assert artifact["publication"]["format"] == "gm-bench-agentic-summary-v1"
        assert artifact["publication"]["traces_included"] is False
        assert artifact["panel"]["seeds"] == "<redacted>"
        assert len(artifact["episodes"]) == row["panel"]["episodes"]
        for episode in artifact["episodes"]:
            assert "seed" not in episode
            candidates.append((episode["final_score"], row, artifact, episode))
    score, row, artifact, episode = max(candidates, key=lambda candidate: candidate[0])
    expected = {
        "source": row["artifact_path"],
        "episode_index": episode["index"],
        "model": row["model"],
        "harness": row["harness"]["name"],
        "harness_version": row["harness"]["version"],
        "seasons": artifact["seasons"],
        "final_score": score,
        "strategy_score": episode["strategy_score"],
        "protocol_penalty": episode["protocol_penalty"],
        "championships": episode["championships"],
        "wins": episode["wins"],
        "tool_calls": episode["agentic"]["tool_calls"],
        "moves_accepted": episode["agentic"]["moves_accepted"],
        "moves_rejected": episode["agentic"]["moves_rejected"],
        "panel_mean_score": artifact["summary"]["mean_score"],
        "panel_episodes": len(artifact["episodes"]),
        "selection_episodes": len(candidates),
        "selection_rows": len(rows),
    }
    assert summary == expected, "Best-run showcase is stale or disagrees with published evidence"
    assert abs(score - (episode["strategy_score"] - episode["protocol_penalty"])) < 0.001
    print(f"Best-run summary verified: {row['model']} {score} among {len(candidates)} episodes")


if __name__ == "__main__":
    validate_best_run()
