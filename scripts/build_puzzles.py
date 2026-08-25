#!/usr/bin/env python3
"""Turn recorded decisions into puzzle cards for the site.

A card is one decision window with several options attached. Every option is a
real policy's actual choice from the *same* observation, so nothing is invented:
the distractors are moves some policy genuinely wanted to make.

Options are graded by immediate state delta -- the change in cap room, asset
value, roster depth and current strength the moment the actions apply. That
grade is deterministic. Grading by the rest of the season would not be: within-
seed score noise runs to an SD of 53 points and survives pairing, which is
larger than the spread between most published models.

This is illustrative content. It is not a benchmark artifact, carries no
contract fingerprint, and must never be cited as evidence about any policy.

    python scripts/build_puzzles.py --limit 24
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gm_bench.recorder import IMMEDIATE_METRICS  # noqa: E402

DEFAULT_INPUT = Path("data/decision-records")
DEFAULT_OUTPUT = Path("web/src/data/puzzles.json")
PUZZLE_SCHEMA = "gm-bench-puzzles-v1"

# Actions every policy emits every turn. They are real actions, but a card whose
# options differ only in lineup order or memo prose is not a decision anybody
# would find interesting.
ROUTINE_ACTIONS = frozenset(
    {"memo", "noop", "set_lineup", "end_turn", "inspect_team", "inspect_player", "list_free_agents", "scout"}
)

# A decision is only interesting if the club is in a recognisable state. A
# policy that has let its roster collapse well under the 18-player minimum makes
# every option trivially "sign anyone", which ranks enormously well on immediate
# delta and teaches nothing.
MIN_ROSTER_FOR_A_CARD = 15
# An option holding a dozen signings is a policy summary, not a choice a person
# can weigh. Cards stay readable when each option is a handful of moves.
MAX_ACTIONS_PER_OPTION = 4
# `random` is not a policy. Its choices are noise, so a card contrasting it with
# anything is a card about randomness rather than about judgement.
EXCLUDED_SUBJECTS = ("random",)

PHASE_LABELS = {
    "preseason": "Preseason",
    "midseason": "Midseason",
    "trade_deadline": "Trade deadline",
    "draft": "Draft",
}


# --------------------------------------------------------------------------
# grading
# --------------------------------------------------------------------------


def option_score(delta: dict[str, float]) -> float:
    """Immediate score effect of an option, in score-v1 points."""
    return sum(value for name, value in delta.items() if name.endswith("_contribution"))


def puzzle_worthiness(subject_delta: dict[str, float], option_deltas: list[dict[str, float]], phase: str) -> float:
    """Rank a decision. Higher is a better card; 0.0 drops it.

    THIS IS THE TUNING KNOB. It decides which decisions become puzzles, and it
    is a judgment call rather than a fact about the simulator.

    The current rule is "how much did the subject leave on the table": the gap
    in immediate score between the best available option and the one the subject
    took. That surfaces the decisions which actually explain a policy's deficit,
    which is what the cards are meant to illustrate.

    Two deliberate choices worth revisiting:

    * Signed, not absolute. A decision where the subject beat every ghost scores
      0.0 and is dropped. Those exist and can be interesting, but they make a
      confusing card -- the "right" answer is then the one nobody recommends.
    * Ungated by mechanic. Cap-room arithmetic can dominate, because ``cap_room``
      is clamped to a +/-12 band while ``total_assets`` is not. If cards start
      looking repetitive, weight by mechanic here rather than filtering later.
    """
    if not option_deltas:
        return 0.0
    best = max(option_score(delta) for delta in option_deltas)
    return max(0.0, best - option_score(subject_delta))


# --------------------------------------------------------------------------
# option identity
# --------------------------------------------------------------------------


def substantive(actions: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [action for action in actions if action.get("type") not in ROUTINE_ACTIONS]


def option_key(actions: Iterable[dict[str, Any]]) -> str:
    """Canonical identity of a choice, ignoring routine actions and key order."""
    return json.dumps(
        sorted((json.dumps(action, sort_keys=True) for action in substantive(actions))),
        sort_keys=True,
    )


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------


def player_index(observation: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """Every player the observation names, by id."""
    index: dict[int, dict[str, Any]] = {}
    for player in observation.get("team", {}).get("roster", []):
        index[player["id"]] = player
    for bucket in ("free_agents", "waiver_wire", "draft_class"):
        for player in observation.get(bucket, []) or []:
            index.setdefault(player["id"], player)
    for listing in observation.get("trade_market", []) or []:
        player = listing.get("player")
        if player:
            index.setdefault(player["id"], player)
    for offer in observation.get("incoming_offers", []) or []:
        for bucket in ("give_players", "receive_players", "players"):
            for player in offer.get(bucket, []) or []:
                if isinstance(player, dict) and "id" in player:
                    index.setdefault(player["id"], player)
    return index


def team_index(observation: dict[str, Any]) -> dict[int, str]:
    names = {row["team_id"]: row.get("team_name", f"Team {row['team_id']}") for row in observation.get("standings", [])}
    for listing in observation.get("trade_market", []) or []:
        if "team_id" in listing:
            names.setdefault(listing["team_id"], listing.get("team_name", f"Team {listing['team_id']}"))
    return names


def _name(index: dict[int, dict[str, Any]], player_id: Any) -> str:
    player = index.get(int(player_id)) if str(player_id).lstrip("-").isdigit() else None
    if not player:
        return f"player {player_id}"
    return f"{player['name']} ({player.get('position', '?')} {player.get('overall', 0):.0f})"


def _pick_label(season: Any) -> str:
    return f"their season-{season} first-round pick"


def describe_action(action: dict[str, Any], players: dict[int, dict[str, Any]], teams: dict[int, str]) -> str:
    kind = action.get("type")
    if kind == "sign_free_agent":
        return (
            f"Sign {_name(players, action.get('player_id'))} "
            f"for ${action.get('salary', 0):.2f}M x {action.get('years', 0)}y"
        )
    if kind == "extend_contract":
        return (
            f"Extend {_name(players, action.get('player_id'))} "
            f"for ${action.get('salary', 0):.2f}M x {action.get('years', 0)}y"
        )
    if kind == "release":
        return f"Release {_name(players, action.get('player_id'))}"
    if kind == "claim_waiver":
        return f"Claim {_name(players, action.get('player_id'))} off waivers"
    if kind == "draft":
        return f"Draft {_name(players, action.get('prospect_id'))}"
    if kind == "trade":
        partner = teams.get(int(action.get("partner_team_id", -1)), "another team")
        out = [_name(players, pid) for pid in action.get("give_player_ids") or []]
        out += [_pick_label(season) for season in action.get("give_pick_seasons") or []]
        back = [_name(players, pid) for pid in action.get("receive_player_ids") or []]
        back += [_pick_label(season) for season in action.get("receive_pick_seasons") or []]
        return f"Trade {', '.join(out) or 'nothing'} to {partner} for {', '.join(back) or 'nothing'}"
    if kind == "accept_trade_offer":
        return "Accept the incoming trade offer"
    if kind == "reject_trade_offer":
        return "Reject the incoming trade offer"
    if kind == "counter_trade_offer":
        return "Counter the incoming trade offer"
    return kind or "unknown action"


def describe_option(actions: list[dict[str, Any]], players: dict, teams: dict) -> list[str]:
    lines = [describe_action(action, players, teams) for action in substantive(actions)]
    return lines or ["Stand pat - make no roster move this window"]


def situation(observation: dict[str, Any]) -> dict[str, Any]:
    team = observation.get("team", {})
    return {
        "team": team.get("name", "your club"),
        "season": observation.get("season"),
        "phase": PHASE_LABELS.get(observation.get("phase", ""), observation.get("phase", "")),
        "record": f"{team.get('wins', 0)}-{team.get('losses', 0)}",
        "cap_room": round(team.get("cap_room", 0.0), 2),
        "payroll": round(team.get("payroll", 0.0), 2),
        "roster_size": len(team.get("roster", [])),
        "championships": team.get("championships", 0),
        "free_agents_available": len(observation.get("free_agents", []) or []),
        "offers_on_the_table": len(observation.get("incoming_offers", []) or []),
    }


METRIC_LABELS = {
    "total_assets": "asset value",
    "young_assets": "young asset value",
    "future_pick_assets": "future pick value",
    "cap_room": "cap room",
    "current_strength": "current strength",
    "roster_depth": "roster depth",
}
# Below this many score points a movement is not worth a clause in the summary.
MATERIAL_CONTRIBUTION = 0.3


def headline_metric(delta: dict[str, float]) -> str:
    """Summarise an option as the trade it makes, in plain words.

    Reporting only the largest mover is actively misleading when two metrics
    offset: a trade that ships a player for picks reads as "gave up asset value"
    even when it is the best option on the board. Naming both sides is the whole
    point -- the trade-off *is* the decision.
    """
    def contribution(name: str) -> float:
        return delta.get(f"{name}_contribution", 0.0)

    gains = [name for name in IMMEDIATE_METRICS if contribution(name) >= MATERIAL_CONTRIBUTION]
    losses = [name for name in IMMEDIATE_METRICS if contribution(name) <= -MATERIAL_CONTRIBUTION]
    if not gains and not losses:
        return "barely moved the roster"

    clauses = []
    if gains:
        clauses.append(f"gained {_amount(max(gains, key=contribution), delta)}")
    if losses:
        clauses.append(f"gave up {_amount(min(losses, key=contribution), delta)}")
    return ", ".join(clauses)


def _amount(metric: str, delta: dict[str, float]) -> str:
    """Render one metric movement in units a reader can picture.

    ``roster_depth`` is stored as a fraction of a 24-man roster, so a signing
    shows up as 0.042 and rounds to a meaningless "0.0". Convert it to bodies.
    """
    raw = abs(delta.get(metric, 0.0))
    if metric == "roster_depth":
        players = round(raw * 24)
        return f"{players} roster {'spot' if players == 1 else 'spots'}"
    return f"{raw:.1f} of {METRIC_LABELS[metric]}"


# --------------------------------------------------------------------------
# card assembly
# --------------------------------------------------------------------------


def gate(record: dict[str, Any], observation: dict[str, Any], options: list[dict[str, Any]]) -> str | None:
    """Why this decision cannot become a card, or None if it can.

    Gates run before ranking. Without them, worthiness ranks by how broken the
    subject is rather than how interesting the decision is: the worst-scoring
    cards in the first build were all "your roster has seven players, sign ten
    free agents or sign none".
    """
    if record["agent"] in EXCLUDED_SUBJECTS:
        return "excluded subject"
    if len(observation.get("team", {}).get("roster", [])) < MIN_ROSTER_FOR_A_CARD:
        return "roster has collapsed"
    if any(len(substantive(option["actions"])) > MAX_ACTIONS_PER_OPTION for option in options):
        return "an option is too long to read"
    return None


def build_card(record: dict[str, Any], *, rejections: Counter[str] | None = None) -> dict[str, Any] | None:
    observation = record.get("observation")
    if not observation:
        return None

    candidates = [{"source": record["agent"], "actions": record["actions"], "delta": record["delta"], "subject": True}]
    for ghost in record.get("ghosts", []):
        if "error" in ghost:
            continue
        candidates.append({"source": ghost["agent"], "actions": ghost["actions"], "delta": ghost["delta"], "subject": False})

    # Collapse policies that made the same substantive choice; keep the first,
    # and remember who else agreed so a card can say "two policies did this".
    merged: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        key = option_key(candidate["actions"])
        if key in merged:
            merged[key]["sources"].append(candidate["source"])
            merged[key]["subject"] = merged[key]["subject"] or candidate["subject"]
            continue
        merged[key] = {**candidate, "sources": [candidate["source"]]}

    options = list(merged.values())
    if len(options) < 2:
        return None

    subject = next((option for option in options if option["subject"]), None)
    if subject is None:
        return None

    reason = gate(record, observation, options)
    if reason:
        if rejections is not None:
            rejections[reason] += 1
        return None

    others = [option["delta"] for option in options if not option["subject"]]
    worth = puzzle_worthiness(subject["delta"], others, record["phase"])
    if worth <= 0.0:
        return None

    players = player_index(observation)
    teams = team_index(observation)
    best = max(options, key=lambda option: option_score(option["delta"]))

    rendered = []
    for index, option in enumerate(options):
        rendered.append(
            {
                "id": chr(ord("a") + index),
                "lines": describe_option(option["actions"], players, teams),
                "chosen_by": sorted(set(option["sources"])),
                "immediate_score": round(option_score(option["delta"]), 2),
                "summary": headline_metric(option["delta"]),
                "delta": {name: round(option["delta"].get(name, 0.0), 2) for name in IMMEDIATE_METRICS},
            }
        )
    answer = rendered[options.index(best)]["id"]

    return {
        "id": f"{record['agent']}-s{record['seed']}-y{record['season']}-{record['phase']}",
        # Options come from the league state, not from the subject, so the same
        # window recorded under five subjects yields five near-identical cards.
        "state_key": f"s{record['seed']}-y{record['season']}-{record['phase']}",
        "seed": record["seed"],
        "season": record["season"],
        "phase": record["phase"],
        "subject": record["agent"],
        "worthiness": round(worth, 2),
        "situation": situation(observation),
        "options": sorted(rendered, key=lambda option: option["id"]),
        "answer": answer,
        "points_left_on_the_table": round(worth, 1),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=24, help="how many cards to keep")
    parser.add_argument("--per-phase", type=int, default=0, help="cap cards per phase (0 = no cap)")
    parser.add_argument("--stats", action="store_true", help="print grading diagnostics and write nothing")
    args = parser.parse_args(argv)

    paths = sorted(args.input.glob("*.jsonl"))
    if not paths:
        parser.error(f"no recordings in {args.input}; run scripts/record_decisions.py first")

    records = [json.loads(line) for path in paths for line in path.read_text(encoding="utf-8").splitlines()]
    rejections: Counter[str] = Counter()
    cards = [card for card in (build_card(record, rejections=rejections) for record in records) if card]
    cards.sort(key=lambda card: card["worthiness"], reverse=True)
    cards = _dedupe_by_state(cards, rejections)

    if args.stats:
        return _print_stats(records, cards, rejections)

    if args.per_phase:
        kept: list[dict[str, Any]] = []
        seen: Counter[str] = Counter()
        for card in cards:
            if seen[card["phase"]] >= args.per_phase:
                continue
            seen[card["phase"]] += 1
            kept.append(card)
        cards = kept
    cards = cards[: args.limit]

    payload = {
        "schema": PUZZLE_SCHEMA,
        "note": (
            "Illustrative content generated at HEAD. Options are real choices made by scripted "
            "policies from the same observation, graded by immediate state change. Not a benchmark "
            "artifact and not evidence about any policy."
        ),
        "source_records": len(records),
        "puzzles": cards,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{len(records)} records -> {len(cards)} cards -> {args.output}")
    return 0


def _dedupe_by_state(cards: list[dict[str, Any]], rejections: Counter[str]) -> list[dict[str, Any]]:
    """Keep the sharpest card per league state.

    Expects ``cards`` pre-sorted by worthiness, so the survivor is the subject
    that left the most on the table in that window.
    """
    seen: set[str] = set()
    kept = []
    for card in cards:
        if card["state_key"] in seen:
            rejections["duplicate league state"] += 1
            continue
        seen.add(card["state_key"])
        kept.append(card)
    return kept


def _print_stats(records: list[dict[str, Any]], cards: list[dict[str, Any]], rejections: Counter[str]) -> int:
    """Does the immediate-delta grade agree with the policy that actually wins?"""
    wins: Counter[str] = Counter()
    appearances: Counter[str] = Counter()
    for record in records:
        entries = [(record["agent"], record["delta"])]
        entries += [(g["agent"], g["delta"]) for g in record.get("ghosts", []) if "error" not in g]
        if len(entries) < 2:
            continue
        for name, _ in entries:
            appearances[name] += 1
        wins[max(entries, key=lambda entry: option_score(entry[1]))[0]] += 1

    print(f"records: {len(records)}   cards: {len(cards)}")
    print("\ntop immediate-delta option, by policy:")
    for name, count in wins.most_common():
        print(f"  {name:14} {count:5}  ({count / max(1, appearances[name]):.0%} of its appearances)")
    print("\nrejected decisions:", dict(rejections.most_common()))
    print("cards by phase:", dict(Counter(card["phase"] for card in cards)))
    print("cards by subject:", dict(Counter(card["subject"] for card in cards)))
    if cards:
        worth = [card["worthiness"] for card in cards]
        print(f"worthiness: max {max(worth):.1f}  median {sorted(worth)[len(worth) // 2]:.1f}  min {min(worth):.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
