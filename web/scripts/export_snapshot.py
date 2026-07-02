"""Export a GM-Bench results snapshot for the web app.

Runs a deterministic evaluation of the value agent against the scripted
baseline panel, then writes the standings, paired-lift analysis, and a sample
of the transaction audit trail to ``web/src/data/snapshot.json``.

Usage (from the repository root):

    python web/scripts/export_snapshot.py [--seeds 1 2 3 4 5] [--seasons 5]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from gm_bench.agents import AGENTS  # noqa: E402
from gm_bench.runner import evaluate_against_baselines, run_many  # noqa: E402

OUTPUT_PATH = ROOT / "web" / "src" / "data" / "snapshot.json"
BASELINES = ["random", "conservative", "win-now", "rebuild"]
CANDIDATE = "value"


def build_snapshot(seeds: list[int], seasons: int) -> dict:
    evaluation = evaluate_against_baselines(AGENTS[CANDIDATE](), seeds=seeds, seasons=seasons, baseline_names=BASELINES)

    all_results = [evaluation["candidate"], *evaluation["baselines"]]
    standings = sorted(
        (
            {
                "agent": result["agent"],
                "mean_score": result["summary"]["mean_score"],
                "score_stddev": result["summary"]["score_stddev"],
                "mean_wins": result["summary"]["mean_total_wins"],
                "titles": result["summary"]["championships"],
                "illegal_actions": result["summary"]["illegal_actions"],
                "episodes": len(result["episodes"]),
                "best_score": max(episode["final_score"] for episode in result["episodes"]),
                "worst_score": min(episode["final_score"] for episode in result["episodes"]),
            }
            for result in all_results
        ),
        key=lambda row: row["mean_score"],
        reverse=True,
    )

    # A compact season-by-season trace of the winning agent on the first seed,
    # used by the front end to show a single franchise trajectory.
    trace_run = run_many(AGENTS[CANDIDATE](), seeds=[seeds[0]], seasons=seasons)
    trace_episode = trace_run["episodes"][0]
    season_trace = [
        {
            "season": summary["season"],
            "wins": summary["wins"],
            "losses": summary["losses"],
            "playoff_rounds": summary["playoff_rounds"],
            "champion": summary["champion_team_id"] == 0,
            "cap_room": round(summary["cap_room"], 2),
            "score_after_season": summary["score_after_season"],
        }
        for summary in trace_episode["season_summaries"]
    ]
    sample_transactions = [
        {
            "season": transaction["season"],
            "phase": transaction["phase"],
            "accepted": transaction["accepted"],
            "message": transaction["message"],
            "action": transaction["action"],
        }
        for transaction in trace_episode["transactions"][:14]
    ]

    return {
        "config": {
            "candidate": CANDIDATE,
            "baselines": BASELINES,
            "seeds": seeds,
            "seasons": seasons,
        },
        "normalized": evaluation["normalized"],
        "paired": evaluation["paired"],
        "standings": standings,
        "season_trace": {
            "agent": CANDIDATE,
            "seed": seeds[0],
            "seasons": season_trace,
        },
        "sample_transactions": sample_transactions,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    parser.add_argument("--seasons", type=int, default=5)
    args = parser.parse_args()

    snapshot = build_snapshot(args.seeds, args.seasons)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
