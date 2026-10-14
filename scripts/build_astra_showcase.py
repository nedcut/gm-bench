"""Derive a deliberately non-replayable showcase from operator-held evidence.

Usage: python3 scripts/build_astra_showcase.py --raw <run directory> [--check]
No model is invoked. Never copy the raw input into the repository. Publication
is an allowlist: prose move summaries, financial totals and season outcomes;
no seeds, entity IDs, initial rosters, ratings, tool replies or harness text.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gm_bench.agentic.episode import AgenticEpisode  # noqa: E402
from gm_bench.agentic.tools import TOOLS_BY_NAME  # noqa: E402
from gm_bench.agentic.validate import replayable_ledger  # noqa: E402
from gm_bench.publication import canonical_sha256  # noqa: E402
from gm_bench.simulator import PLAYOFF_SPOTS  # noqa: E402

SOURCE = "results/agentic/codex-0.162.1-gpt-6-astra-panel-32x5.json"
OUTPUT = ROOT / "web/src/data/astra-showcase.json"
DIGEST = "091fff8d623165c0fe98538cf10a9c243e03bcd5f89a32dc506455aad2c25154"
INDEX = 28


def move_text(tool: str, args: dict, league) -> str:
    """Build prose from typed fields, never from an untrusted raw message."""

    def names(key: str) -> str:
        return ", ".join(league.players[pid].name for pid in args.get(key, [])) or "no players"

    def picks(key: str) -> str:
        years = args.get(key, [])
        return " + season " + ", ".join(map(str, years)) + " draft picks" if years else ""

    if tool == "trade":
        return (
            f"Offered {names('give_player_ids')}{picks('give_pick_seasons')} to "
            f"{league.teams[args['partner_team_id']].name} for "
            f"{names('receive_player_ids')}{picks('receive_pick_seasons')}."
        )
    if tool in {"extend_contract", "sign_free_agent"}:
        verb = "Extended" if tool == "extend_contract" else "Signed"
        return f"{verb} {league.players[args['player_id']].name}: ${args['salary']:.2f}M/year, {args['years']} years."
    if tool == "claim_waiver":
        player = league.players[args["player_id"]]
        return f"Claimed {player.name}: inherited ${player.salary:.2f}M/year, {player.contract_years} years remaining."
    if tool == "draft":
        player = league.prospects[args["prospect_id"]]
        return f"Drafted {player.name}."
    raise ValueError("Unreviewed move type; update the disclosure allowlist before exporting")


def extract(raw_path: Path) -> dict:
    if raw_path.is_dir():
        raw_path /= "run.json"
    raw = json.loads(raw_path.read_text())
    artifact = json.loads((ROOT / SOURCE).read_text())
    if canonical_sha256(raw) != DIGEST or artifact["publication"]["raw_artifact_sha256"] != DIGEST:
        raise ValueError("Raw evidence is not the published Astra run")
    published = artifact["episodes"][INDEX]
    retained = raw["episodes"][INDEX]
    assert (published["index"], published["final_score"], published["championships"], published["wins"]) == (
        INDEX,
        409.132,
        3,
        311,
    )
    assert retained["final_score"] == published["final_score"]
    # Resolve only within the supplied run directory; recorded operator paths
    # may refer to a different machine and are never output.
    records = [
        json.loads(line) for line in (raw_path.parent / f"episode-{INDEX:02d}/ledger.jsonl").read_text().splitlines()
    ]
    records, _ = replayable_ledger(records)
    header = records[0]
    assert header["seed"] == retained["seed"]
    episode = AgenticEpisode(header["seed"], header["seasons"], header["user_team_id"], write_header=False)
    episode._replaying = True
    league = episode.league
    seasons = []
    moves: list[dict] = []
    counts: Counter = Counter()
    lineups = 0
    previous_wins = previous_losses = 0
    start_count = len(league.user_team.roster)
    for record in records[1:]:
        if record["event"] != "tool_call" or not record.get("executed", True):
            continue
        tool = record["tool"]
        args = record.get("arguments") or {}
        phase = episode.phase
        season = episode.season
        if TOOLS_BY_NAME.get(tool, {}).get("kind") == "move":
            counts["accepted" if record["ok"] else "rejected"] += 1
            if tool == "set_lineup":
                assert record["ok"]
                lineups += 1
            else:
                item = {"phase": phase, "kind": tool, "accepted": record["ok"], "detail": move_text(tool, args, league)}
                if not record["ok"]:
                    # Only the two observed, reviewed refusal categories.
                    message = record["message"]
                    assert message in {"pick seasons must be between 2 and 4", "partner rejects the offer as too light"}
                    item["detail"] += " Rejected: " + message + "."
                moves.append(item)
        before_roster = set(league.user_team.roster)
        reply = episode._execute(tool, args)
        if bool(reply.get("ok")) != record["ok"] or str(reply.get("message", ""))[:300] != record["message"]:
            raise ValueError("Tool reply did not reproduce; no showcase exported")
        if tool == "draft" and record["ok"]:
            player = league.players[args["prospect_id"]]
            moves[-1]["detail"] += f" Rookie contract: ${player.salary:.2f}M/year, {player.contract_years} years."
        if tool == "end_phase" and phase == "draft":
            summary = league.summaries[-1]
            assert summary.__dict__ == retained["season_summaries"][season - 1]
            ordered = sorted(league.teams.values(), key=lambda team: team.wins, reverse=True)
            rank = [team.id for team in ordered].index(header["user_team_id"]) + 1
            champion = summary.champion_team_id == header["user_team_id"]
            assert champion or (rank <= PLAYOFF_SPOTS and summary.playoff_rounds == 0)
            removed = before_roster - set(league.user_team.roster)
            added = set(league.user_team.roster) - before_roster
            assert not added, "Unreviewed automatic roster additions"
            seasons.append(
                {
                    "season": season,
                    "wins": summary.wins - previous_wins,
                    "losses": summary.losses - previous_losses,
                    "recorded_wins": summary.wins,
                    "recorded_losses": summary.losses,
                    "standing": rank,
                    "champion": champion,
                    "finish": "Champion · 3 rounds won" if champion else "First-round exit · 0 rounds won",
                    "score_after_season": summary.score_after_season,
                    "payroll": summary.payroll,
                    "cap_room": summary.cap_room,
                    "cap": round(summary.payroll + summary.cap_room, 2),
                    "roster_start": start_count,
                    "roster_end": len(league.user_team.roster),
                    "rollover_departures": sorted(league.players[pid].name for pid in removed),
                    "lineup_calls": lineups,
                    "moves": moves,
                }
            )
            previous_wins, previous_losses = summary.wins, summary.losses
            start_count = len(league.user_team.roster)
            moves = []
            lineups = 0
    assert episode.done and len(seasons) == 5
    result = episode.result()
    assert [transaction.__dict__ for transaction in league.transactions] == retained["transactions"]
    for key in ("final_score", "strategy_score", "protocol_penalty", "championships", "wins"):
        assert result[key] == published[key]
    assert counts == {
        "accepted": published["agentic"]["moves_accepted"],
        "rejected": published["agentic"]["moves_rejected"],
    }
    return {
        "format": "astra-showcase-v1",
        "source": SOURCE,
        "episode_index": INDEX,
        "raw_artifact_sha256": DIGEST,
        "seasons": seasons,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", required=True, type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    data = extract(args.raw)
    if args.check:
        assert json.loads(OUTPUT.read_text()) == data, "Committed showcase differs from raw evidence"
    else:
        OUTPUT.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print("Astra showcase reproduced: canonical binding, tool replies, season summaries and published totals agree.")


if __name__ == "__main__":
    main()
