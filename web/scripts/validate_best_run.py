"""Check the Replay showcase against every currently published comparable episode."""

import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def validate_showcase(showcase: dict, summary: dict) -> None:
    """Public allowlist and arithmetic checks; full reproduction requires operator raw evidence."""
    assert set(showcase) == {"format", "source", "episode_index", "raw_artifact_sha256", "seasons"}
    assert showcase["format"] == "astra-showcase-v1"
    assert showcase["source"] == summary["source"]
    assert showcase["episode_index"] == summary["episode_index"] == 28
    artifact = json.loads((ROOT / summary["source"]).read_text())
    assert showcase["raw_artifact_sha256"] == artifact["publication"]["raw_artifact_sha256"]
    seasons = showcase["seasons"]
    assert len(seasons) == summary["seasons"] == 5
    season_keys = {
        "season",
        "wins",
        "losses",
        "recorded_wins",
        "recorded_losses",
        "standing",
        "champion",
        "finish",
        "score_after_season",
        "payroll",
        "cap_room",
        "cap",
        "roster_start",
        "roster_end",
        "rollover_departures",
        "lineup_calls",
        "moves",
    }
    cumulative_wins = cumulative_losses = accepted = rejected = 0
    kinds = Counter()
    for index, season in enumerate(seasons, 1):
        assert set(season) == season_keys
        assert season["season"] == index
        assert season["wins"] + season["losses"] == 33
        cumulative_wins += season["wins"]
        cumulative_losses += season["losses"]
        assert (season["recorded_wins"], season["recorded_losses"]) == (cumulative_wins, cumulative_losses)
        assert 1 <= season["standing"] <= 12
        assert season["champion"] == (index in (3, 4, 5))
        assert season["finish"] == (
            "Champion · 3 rounds won" if season["champion"] else "First-round exit · 0 rounds won"
        )
        assert abs(season["payroll"] + season["cap_room"] - season["cap"]) < 0.001
        assert season["lineup_calls"] == 4
        assert 18 <= season["roster_start"] <= 23 and 18 <= season["roster_end"] <= 23
        assert all(re.fullmatch(r"[A-Za-z]+ [A-Za-z]+", name) for name in season["rollover_departures"])
        accepted += season["lineup_calls"]
        for move in season["moves"]:
            assert set(move) == {"phase", "kind", "accepted", "detail"}
            assert move["phase"] in {"preseason", "midseason", "trade_deadline", "draft"}
            assert move["kind"] in {"trade", "sign_free_agent", "extend_contract", "draft", "claim_waiver"}
            assert type(move["accepted"]) is bool
            accepted += move["accepted"]
            rejected += not move["accepted"]
            kinds[move["kind"], move["accepted"]] += 1
            assert 0 < len(move["detail"]) < 450
            assert ("Rejected:" in move["detail"]) == (not move["accepted"])
    assert sum(season["recorded_wins"] for season in seasons) == summary["wins"] == 311
    assert sum(season["champion"] for season in seasons) == summary["championships"] == 3
    assert (accepted, rejected) == (summary["moves_accepted"], summary["moves_rejected"]) == (69, 5)
    assert kinds == {
        ("trade", True): 5,
        ("trade", False): 5,
        ("extend_contract", True): 34,
        ("sign_free_agent", True): 7,
        ("draft", True): 1,
        ("claim_waiver", True): 2,
    }
    text = json.dumps(showcase)
    # Fail closed on paths, URLs, raw IDs, long numeric seed candidates and trace fields.
    assert not re.search(
        r"https?://|file:|/home/|/Users/|/tmp/|\b\d{10,}\b|seed|player_id|prospect_id|team_id|ledger|harness|credential",
        text,
    )


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
    validate_showcase(json.loads((ROOT / "web/src/data/astra-showcase.json").read_text()), summary)
    print(f"Best-run summary verified: {row['model']} {score} among {len(candidates)} episodes")


if __name__ == "__main__":
    validate_best_run()
