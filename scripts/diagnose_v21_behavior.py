"""How the committed 2.1 model rows play: where the OpenAI-Claude gap comes from.

Replays every episode of each given 2.1 run directory with the frozen 2.1
engine (``AgenticEpisode21``; no model calls, nothing written to the run),
asserts that each replayed final score matches the run's committed row in
``results/agentic_v21/``, and measures, per model:

- empty phases (``validate.EMPTY_PHASE_DEFINITION``) split into drafts with
  no pick to use and everything else, and the two proposed replacements:
  drafts closed while holding an unused current-season pick, and phases
  ended without reading the status;
- the end of the run: roster size after the final rollover, season-5
  extensions and signings, extensions that expire before the final credit,
  and how often the final score is below the score after season 4;
- the lineup at the close of each draft (when the rest of the regular season
  and the playoffs are played): its gap to the engine's default lineup,
  draftees left benched while outranking a dressed player, second goalies;
- penalized rejections, clustered by message.

And, paired seed by seed, the OpenAI (Codex) minus Claude family gap split by
score-v2 term. A run directory without a committed row (a panel still
running) is listed under ``skipped_runs`` and not measured. Writes
aggregates only: no seed and no per-episode score leaves this script.

    python scripts/diagnose_v21_behavior.py ~/gmb-runs/<2.1 run> [...] \\
        [--out results/diagnostics/v21_behavior/behavior.json]
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "scripts"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from score_v2 import paired  # noqa: E402

from gm_bench.agentic.validate import (  # noqa: E402
    EMPTY_PHASE_DEFINITION,
    EMPTY_PHASE_TOOLS,
    empty_phases,
    replayable_ledger,
)
from gm_bench.models import LINEUP_MIN_POSITIONS  # noqa: E402
from gm_bench.v21.contract import BENCHMARK_VERSION  # noqa: E402
from gm_bench.v21.episode import AgenticEpisode21, ledger_benchmark_version  # noqa: E402

ROWS = ROOT / "results" / "agentic_v21"
OUT = ROOT / "results" / "diagnostics" / "v21_behavior" / "behavior.json"
OPENAI = ("gpt-6-astra", "gpt-6.1-sol", "gpt-6-luna")
CLAUDE = ("claude-opus-5-5", "claude-sonnet-5-5")
FINAL_SEASON = 5
# score-v2 contributions grouped as the gap decomposition reports them.
TERM_GROUPS = {
    "winning": ("season_wins", "expected_playoff_rounds", "expected_championships"),
    "end_roster": ("total_assets", "young_assets", "roster_depth"),
    "current_strength": ("current_strength",),
    "future_picks": ("future_pick_assets",),
    "cap_room": ("cap_room",),
}


class _Probe(AgenticEpisode21):
    """The 2.1 episode with read-only snapshots at each phase open and close and around each call."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.phases: list[dict[str, Any]] = []
        self.calls: list[dict[str, Any]] = []
        self.roster_before_final_rollover: int | None = None
        super().__init__(*args, **kwargs)

    def _open_phase(self) -> None:
        super()._open_phase()
        if not self.phase_open:
            return
        league = self.league
        offers = league.current_offers
        self.phases.append(
            {
                "season": self.season_index,
                "phase": self.phase,
                "calls": [],
                "drafted": set(),
                "picks_at_open": len(league.user_team.draft_picks.get(self.season_index, [])),
                "live_offers": len(offers),
                "stale_offers": sum(1 for offer in offers.values() if _offer_stale(league, offer)),
            }
        )

    def _close_phase(self, ended_by: str) -> dict[str, Any]:
        phase = self.phases[-1]
        league, team = self.league, self.league.user_team
        phase["picks_at_close"] = len(team.draft_picks.get(self.season_index, []))
        phase["lineup"] = _lineup_snapshot(league, team, phase["drafted"] if self.phase == "draft" else None)
        if self.phase == "preseason" and self.season_index == FINAL_SEASON:
            phase["final_year_players"] = sum(1 for pid in team.roster if league.players[pid].contract_years == 1)
        if self.phase == "draft" and self.season_index == FINAL_SEASON:
            self.roster_before_final_rollover = len(team.roster)
        return super()._close_phase(ended_by)

    def _execute(self, name: str, arguments: Any) -> dict[str, Any]:
        args = arguments if isinstance(arguments, dict) else {}
        phase = self.phases[-1]  # the open phase; end_phase closes it
        whereabouts = _free_agent_whereabouts(self.league, args.get("player_id")) if name == "sign_free_agent" else None
        roster = set(self.league.user_team.roster)
        reply = super()._execute(name, arguments)
        if name == "draft" and reply.get("ok"):
            phase["drafted"].update(set(self.league.user_team.roster) - roster)
        message = str(reply.get("message", ""))
        if not reply.get("ok"):
            message = _scrub_names(self.league, message)
        call = {
            "tool": name,
            "season": phase["season"],
            "phase": phase["phase"],
            "ok": bool(reply.get("ok")),
            "penalized": bool(reply.get("penalized")),
            "message": message,
            "years": args.get("years"),
            "gives_current_pick": self.season_index in (args.get("give_pick_seasons") or []),
            "whereabouts": whereabouts,
        }
        phase["calls"].append(call)
        self.calls.append(call)
        return reply


def _scrub_names(league: Any, message: str) -> str:
    """Rejection text with team and player names replaced, so no output can name either."""
    for team in league.teams.values():
        message = message.replace(team.name, "TEAM")
    for player in league.players.values():
        if player.name in message:
            message = message.replace(player.name, "PLAYER")
    return message


def _offer_stale(league: Any, offer: dict[str, Any]) -> bool:
    partner = league.teams[offer["partner_id"]]
    return any(pid not in partner.roster for pid in offer["you_receive"]) or any(
        pid not in league.user_team.roster for pid in offer["they_receive"]
    )


def _free_agent_whereabouts(league: Any, player_id: Any) -> str:
    try:
        player = league.players.get(int(player_id))
    except (TypeError, ValueError):
        return "bad id"
    if player is None:
        return "unknown id"
    if int(player_id) in league.waiver_wire:
        return "on the waiver wire"
    if player.team_id is not None:
        return "on a team" if player.team_id != league.user_team_id else "already yours"
    return "free agent"


def _lineup_snapshot(league: Any, team: Any, drafted: set[int] | None) -> dict[str, Any]:
    """Strength with the stored lineup and with the engine's default (no stored lineup), and who is benched."""
    dressed = league._effective_lineup(team, available_only=True)
    dressed_ids = {player.id for player in dressed}
    stored = league._team_strength(team, False)
    saved, team.lineup = team.lineup, []
    try:
        default = league._team_strength(team, False)
    finally:
        team.lineup = saved
    healthy = [league.players[pid] for pid in team.roster if league.players[pid].injured_games == 0]
    worst = {pos: min((p.overall for p in dressed if p.position == pos), default=None) for pos in LINEUP_MIN_POSITIONS}
    snapshot = {
        "gap_to_default": stored - default,
        "goalies_dressed": sum(1 for p in dressed if p.position == "G"),
        "goalies_healthy": sum(1 for p in healthy if p.position == "G"),
    }
    if drafted is not None:
        draftees = [league.players[pid] for pid in drafted if pid in team.roster]
        snapshot["draftees"] = len(draftees)
        snapshot["draftees_benched_outranking"] = sum(
            1
            for p in draftees
            if p.injured_games == 0
            and p.id not in dressed_ids
            and worst[p.position] is not None
            and p.overall > worst[p.position]
        )
    return snapshot


def replay(ledger: Path) -> _Probe:
    if ledger_benchmark_version(ledger) != BENCHMARK_VERSION:
        raise SystemExit(f"{ledger}: not a 2.1 ledger")
    records = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
    records, marked = replayable_ledger(records)
    if not marked:
        return _Probe.from_ledger(ledger, reopen=False)
    with tempfile.TemporaryDirectory(prefix="gmb-behavior-") as directory:
        copy = Path(directory) / "ledger.jsonl"
        copy.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in records), encoding="utf-8")
        return _Probe.from_ledger(copy, reopen=False)


def _committed_rows() -> dict[str, dict[str, Any]]:
    return {json.loads(p.read_text(encoding="utf-8"))["agent"]: {"path": p} for p in sorted(ROWS.glob("*.json"))}


def _run_agent(run_dir: Path) -> str | None:
    run_json = run_dir / "run.json"
    if run_json.exists():
        return json.loads(run_json.read_text(encoding="utf-8"))["agent"]
    first = next(iter(sorted(run_dir.glob("episode-*/result.json"))), None)
    return json.loads(first.read_text(encoding="utf-8"))["agent"] if first else None


def _normalize(message: str) -> str:
    return re.sub(r"\d+(\.\d+)?", "N", message)


def measure_episode(episode_dir: Path, row_episode: dict[str, Any]) -> dict[str, Any]:
    ledger = episode_dir / "ledger.jsonl"
    probe = replay(ledger)
    result = probe.result()
    if abs(result["final_score"] - row_episode["final_score"]) > 1e-6:
        raise SystemExit(f"{episode_dir}: replayed final score does not match the committed row")
    phases = probe.phases
    if len(phases) != 20:
        raise SystemExit(f"{episode_dir}: expected 20 phases, replayed {len(phases)}")
    for phase in phases:
        phase["empty"] = {c["tool"] for c in phase["calls"]} <= EMPTY_PHASE_TOOLS
        phase["read_status"] = any(c["tool"] == "get_status" for c in phase["calls"])
    n_empty = sum(p["empty"] for p in phases)
    if n_empty != empty_phases(ledger) or n_empty != row_episode["empty_phases"]:
        raise SystemExit(f"{episode_dir}: empty-phase count disagrees with validate or the committed row")
    components = result["score_components"]
    terms = {group: sum(components[f"{name}_contribution"] for name in names) for group, names in TERM_GROUPS.items()}
    terms["penalty"] = -components["protocol_penalty"]
    if abs(sum(terms.values()) - result["final_score"]) > 1e-3:
        raise SystemExit(f"{episode_dir}: score terms do not sum to the final score")
    summaries = result["season_summaries"]
    return {
        "seed": result["seed"],
        "final_score": result["final_score"],
        "after_season_4": summaries[FINAL_SEASON - 2]["score_after_season"],
        "terms": terms,
        "phases": phases,
        "calls": probe.calls,
        "roster_end": len(probe.league.user_team.roster),
        "roster_before_final_rollover": probe.roster_before_final_rollover,
    }


def _mean(values: list[float], digits: int = 3) -> float:
    return round(statistics.mean(values), digits) if values else 0.0


def model_summary(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(episodes)
    phases = [p for e in episodes for p in e["phases"]]
    drafts = [p for p in phases if p["phase"] == "draft"]
    empty = [p for p in phases if p["empty"]]
    empty_no_pick = [p for p in empty if p["phase"] == "draft" and p["picks_at_open"] == 0]
    calls = [c for e in episodes for c in e["calls"]]
    ok_ext = [c for c in calls if c["tool"] == "extend_contract" and c["ok"]]
    s5_signings = [c for c in calls if c["tool"] == "sign_free_agent" and c["ok"] and c["season"] == FINAL_SEASON]
    draft_lineups = [p["lineup"] for p in drafts]
    closes = [p["lineup"] for p in phases if p["lineup"]["goalies_healthy"] >= 2]
    s5_pre = [p for p in phases if p["phase"] == "preseason" and p["season"] == FINAL_SEASON]
    penalized = [c for c in calls if c["penalized"]]
    after_rejection = 0
    for phase in phases:
        tools = phase["calls"]
        if len(tools) >= 2 and tools[-1]["tool"] == "end_phase" and tools[-2]["penalized"]:
            after_rejection += 1
    by_type = Counter(p["phase"] for p in empty)
    return {
        "episodes": n,
        "mean_final_score": _mean([e["final_score"] for e in episodes]),
        "empty_phases": {
            "count": len(empty),
            "phases": len(phases),
            "rate": round(len(empty) / len(phases), 4),
            "by_phase": {name: by_type.get(name, 0) for name in ("preseason", "midseason", "trade_deadline", "draft")},
            "drafts_with_no_pick": len(empty_no_pick),
            "share_drafts_with_no_pick": round(len(empty_no_pick) / len(empty), 4) if empty else None,
            "without_status_read": sum(1 for p in empty if not p["read_status"]),
        },
        "drafts": {
            "count": len(drafts),
            "no_pick_at_open": sum(1 for p in drafts if p["picks_at_open"] == 0),
            "closed_holding_unused_pick": sum(1 for p in drafts if p["picks_at_close"] > 0),
            "set_lineup_in_draft": sum(1 for p in drafts if any(c["tool"] == "set_lineup" for c in p["calls"])),
            "with_live_deadline_offers": sum(1 for p in drafts if p["live_offers"]),
            "with_a_stale_listed_offer": sum(1 for p in drafts if p["stale_offers"]),
            "trade_attempts_in_draft": sum(1 for c in calls if c["tool"] == "trade" and c["phase"] == "draft"),
            "trade_attempts_at_deadline": sum(
                1 for c in calls if c["tool"] == "trade" and c["phase"] == "trade_deadline"
            ),
            "signings_in_draft": sum(
                1 for c in calls if c["tool"] == "sign_free_agent" and c["ok"] and c["phase"] == "draft"
            ),
        },
        "status_habit": {
            "phases_ended_without_status_read": sum(1 for p in phases if not p["read_status"]),
            "rate_ended_without_status_read": round(sum(1 for p in phases if not p["read_status"]) / len(phases), 4),
            "get_status_per_episode": round(sum(1 for c in calls if c["tool"] == "get_status") / n, 2),
            "set_lineup_per_episode": round(sum(1 for c in calls if c["tool"] == "set_lineup") / n, 2),
        },
        "end_of_run": {
            "roster_before_final_rollover": _mean([e["roster_before_final_rollover"] for e in episodes], 2),
            "roster_at_end": _mean([e["roster_end"] for e in episodes], 2),
            "episodes_ending_with_5_or_fewer": sum(1 for e in episodes if e["roster_end"] <= 5),
            "season_5_extensions_per_episode": round(sum(1 for c in ok_ext if c["season"] == FINAL_SEASON) / n, 2),
            "extensions_per_episode": round(len(ok_ext) / n, 2),
            "extensions_ending_at_final_rollover": sum(
                1 for c in ok_ext if c["season"] + int(c["years"]) - 1 == FINAL_SEASON
            ),
            "final_year_players_left_at_season_5_preseason_close": sum(p["final_year_players"] for p in s5_pre),
            "season_5_signings": len(s5_signings),
            "season_5_signings_one_year": sum(1 for c in s5_signings if int(c["years"] or 1) == 1),
            "mean_final_minus_after_season_4": _mean([e["final_score"] - e["after_season_4"] for e in episodes], 2),
            "episodes_final_below_after_season_4": sum(1 for e in episodes if e["final_score"] < e["after_season_4"]),
        },
        "lineups": {
            "mean_gap_to_default_at_draft_close": _mean([s["gap_to_default"] for s in draft_lineups]),
            "draft_closes_more_than_0_5_below_default": sum(1 for s in draft_lineups if s["gap_to_default"] < -0.5),
            "draftees": sum(s["draftees"] for s in draft_lineups),
            "draftees_benched_outranking_a_dressed_player": sum(
                s["draftees_benched_outranking"] for s in draft_lineups
            ),
            "phase_closes_with_2_healthy_goalies": len(closes),
            "of_which_2_goalies_dressed": sum(1 for s in closes if s["goalies_dressed"] >= 2),
        },
        "rejections": {
            "penalized": len(penalized),
            "penalized_per_episode": round(len(penalized) / n, 2),
            "phases_closed_straight_after_a_penalized_rejection": after_rejection,
            "by_message": dict(Counter(_normalize(c["message"]) for c in penalized).most_common()),
            "not_an_available_free_agent": dict(
                Counter(
                    c["whereabouts"]
                    for c in calls
                    if c["tool"] == "sign_free_agent" and "not an available free agent" in c["message"]
                )
            ),
            "pick_window_offering_current_season": sum(
                1 for c in penalized if c["message"].startswith("pick seasons must be") and c["gives_current_pick"]
            ),
            "partner_broke_off_talks": sum(1 for c in calls if "broken off trade talks" in c["message"]),
        },
    }


def _seed_correlation(a: list[float], b: list[float]) -> float | None:
    try:
        return round(statistics.correlation(a, b), 3)
    except statistics.StatisticsError:
        return None


def family_gap(by_model: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    openai, claude = [m for m in OPENAI if m in by_model], [m for m in CLAUDE if m in by_model]
    if not openai or not claude:
        return {"note": "needs at least one OpenAI and one Claude row"}
    n = len(by_model[openai[0]])

    def family_mean(models: list[str], index: int, key: str) -> float:
        values = []
        for model in models:
            episode = by_model[model][index]
            values.append(episode["final_score"] if key == "final_score" else episode["terms"][key])
        return statistics.mean(values)

    keys = ["final_score", *TERM_GROUPS, "penalty"]
    gaps = {key: [family_mean(openai, i, key) - family_mean(claude, i, key) for i in range(n)] for key in keys}
    total = statistics.mean(gaps["final_score"])
    empties = {m: [sum(p["empty"] for p in e["phases"]) for e in by_model[m]] for m in openai + claude}
    return {
        "openai": openai,
        "claude": claude,
        "seeds": n,
        "terms": {key: paired(values) for key, values in gaps.items()},
        "share_of_gap": {
            key: round(statistics.mean(gaps[key]) / total, 3) if total else None for key in keys if key != "final_score"
        },
        "seed_correlation_extra_empty_vs_score_gap": {
            f"{o} vs {c}": _seed_correlation(
                [empties[c][i] - empties[o][i] for i in range(n)],
                [by_model[o][i]["final_score"] - by_model[c][i]["final_score"] for i in range(n)],
            )
            for o in openai
            for c in claude
        },
    }


def penalized_clusters(summaries: dict[str, dict[str, Any]]) -> dict[str, Any]:
    total: Counter[str] = Counter()
    for summary in summaries.values():
        total.update(summary["rejections"]["by_message"])
    count = sum(total.values())
    return {
        "penalized": count,
        "clusters": [
            {
                "message": message,
                "count": n,
                "share": round(n / count, 3),
                "by_model": {m: s["rejections"]["by_message"].get(message, 0) for m, s in summaries.items()},
            }
            for message, n in total.most_common()
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("runs", nargs="+", type=Path, help="2.1 raw run directories")
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    rows = _committed_rows()
    by_model: dict[str, list[dict[str, Any]]] = {}
    sources: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    for run_dir in (run.expanduser() for run in args.runs):
        agent = _run_agent(run_dir)
        if agent not in rows:
            skipped.append({"run": run_dir.name, "reason": "no committed row in results/agentic_v21/"})
            print(f"skip {run_dir.name}: no committed 2.1 row", file=sys.stderr)
            continue
        row = json.loads(rows[agent]["path"].read_text(encoding="utf-8"))
        dirs = sorted(run_dir.glob("episode-*"))
        if len(dirs) != len(row["episodes"]):
            raise SystemExit(f"{run_dir}: {len(dirs)} episodes, the committed row has {len(row['episodes'])}")
        model = agent.split(":", 1)[1].rsplit("/", 1)[-1]
        by_model[model] = [measure_episode(d, e) for d, e in zip(dirs, row["episodes"], strict=True)]
        sources.append({"model": model, "run": run_dir.name, "row": rows[agent]["path"].relative_to(ROOT).as_posix()})
        print(
            f"{model:24s} {len(dirs)} episodes replayed; every final score matches the committed row", file=sys.stderr
        )
    if not by_model:
        raise SystemExit("no run with a committed 2.1 row")
    seeds = [[e["seed"] for e in episodes] for episodes in by_model.values()]
    if any(s != seeds[0] for s in seeds):
        raise SystemExit("runs do not share the same seeds in the same order; they cannot be paired")
    summaries = {model: model_summary(episodes) for model, episodes in by_model.items()}
    report = {
        "contract": BENCHMARK_VERSION,
        "sources": sources,
        "skipped_runs": skipped,
        "scope_note": (
            "The committed 2.1 rows only. claude-haiku-5-5 and mimo-v2.6-flash had no committed 2.1 row when "
            "this was written (their panels were still running), so they are not measured."
        ),
        "definitions": {
            "empty_phase": EMPTY_PHASE_DEFINITION,
            "drafts_with_no_pick": "an empty draft phase in which the team held no current-season pick at open",
            "closed_holding_unused_pick": "a draft phase closed with a current-season pick still unused",
            "phases_ended_without_status_read": "a phase in which get_status was never called",
            "roster_at_end": "players under contract after the final rollover, when the end-state terms are scored",
            "extensions_ending_at_final_rollover": "successful extensions whose last season (the current season "
            "plus years minus 1) is season 5, so the player leaves before the end-state terms are scored",
            "gap_to_default_at_draft_close": "team strength with the stored lineup minus with no stored lineup "
            "(the engine's default), no injury noise, as the draft phase closes and the rest of the season is "
            "played",
            "draftees_benched_outranking_a_dressed_player": "players drafted in that phase, healthy and not "
            "dressed at its close, rated above the lowest-rated dressed player at their position",
            "family_gap": "per seed, mean of the OpenAI rows minus mean of the Claude rows; terms are score-v2 "
            "contributions grouped as in TERM_GROUPS, penalty is minus the protocol penalty, and the terms sum "
            "to final_score",
        },
        "models": summaries,
        "family_gap": family_gap(by_model),
        "penalized_rejections": penalized_clusters(summaries),
        "not_reproduced": [
            "lineup counterfactual (engine default lineup at every phase close)",
            "filling empty phases with cheap actions",
            "drafting the best prospect in a forfeited draft",
            "fixed-effects regressions of score on empty phases",
        ],
    }
    gap = report["family_gap"]
    for model, s in summaries.items():
        e, r = s["empty_phases"], s["end_of_run"]
        print(
            f"{model:24s} empty {e['count']:3d}/640 (no-pick drafts {e['drafts_with_no_pick']:3d})  "
            f"no status {s['status_habit']['rate_ended_without_status_read']:.2f}  "
            f"end roster {r['roster_at_end']:5.2f}  s5 ext/ep {r['season_5_extensions_per_episode']:5.2f}  "
            f"final<s4 {r['episodes_final_below_after_season_4']:2d}/{s['episodes']}"
        )
    if "terms" in gap:
        print("family gap: " + "  ".join(f"{k} {v['mean']:+.1f}" for k, v in gap["terms"].items()))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
