"""Tests for puzzle extraction.

Cards are illustrative, but they still make a claim on screen -- "this option
was better" -- so the grading, the gates, and the plain-language rendering all
need to be right.
"""

from __future__ import annotations

import importlib.util
import sys
from collections import Counter
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "build_puzzles", Path(__file__).resolve().parents[1] / "scripts" / "build_puzzles.py"
)
assert _SPEC and _SPEC.loader
build_puzzles = importlib.util.module_from_spec(_SPEC)
sys.modules["build_puzzles"] = build_puzzles
_SPEC.loader.exec_module(build_puzzles)


def _delta(**metrics: float) -> dict[str, float]:
    from gm_bench.recorder import IMMEDIATE_METRICS

    delta = {name: 0.0 for name in IMMEDIATE_METRICS}
    delta.update({f"{name}_contribution": 0.0 for name in IMMEDIATE_METRICS})
    delta.update(metrics)
    return delta


# -- grading ---------------------------------------------------------------


def test_option_score_sums_weighted_contributions() -> None:
    delta = _delta(total_assets_contribution=1.5, cap_room_contribution=-0.5)
    assert build_puzzles.option_score(delta) == 1.0


def test_worthiness_is_what_the_subject_left_on_the_table() -> None:
    subject = _delta(total_assets_contribution=2.0)
    better = _delta(total_assets_contribution=9.0)
    assert build_puzzles.puzzle_worthiness(subject, [better], "preseason") == 7.0


def test_worthiness_is_zero_when_the_subject_played_it_best() -> None:
    subject = _delta(total_assets_contribution=9.0)
    worse = _delta(total_assets_contribution=2.0)
    assert build_puzzles.puzzle_worthiness(subject, [worse], "preseason") == 0.0


def test_worthiness_needs_something_to_compare_against() -> None:
    assert build_puzzles.puzzle_worthiness(_delta(), [], "draft") == 0.0


# -- option identity -------------------------------------------------------


def test_routine_actions_do_not_make_two_choices_different() -> None:
    """Every policy sets a lineup and writes a memo; that is not a decision."""
    left = [{"type": "set_lineup", "player_ids": [1, 2]}, {"type": "memo", "text": "a"}]
    right = [{"type": "memo", "text": "totally different prose"}]
    assert build_puzzles.option_key(left) == build_puzzles.option_key(right)


def test_a_real_move_makes_two_choices_different() -> None:
    stand_pat = [{"type": "noop"}]
    signing = [{"type": "sign_free_agent", "player_id": 4, "salary": 1.0, "years": 2}]
    assert build_puzzles.option_key(stand_pat) != build_puzzles.option_key(signing)


def test_option_key_ignores_action_order() -> None:
    one = {"type": "release", "player_id": 1}
    two = {"type": "release", "player_id": 2}
    assert build_puzzles.option_key([one, two]) == build_puzzles.option_key([two, one])


# -- gates -----------------------------------------------------------------


def _options(count: int) -> list[dict]:
    return [{"actions": [{"type": "release", "player_id": index}]} for index in range(count)]


def test_a_collapsed_roster_is_not_a_decision() -> None:
    observation = {"team": {"roster": [{"id": index} for index in range(7)]}}
    reason = build_puzzles.gate({"agent": "value"}, observation, _options(2))
    assert reason == "roster has collapsed"


def test_random_is_not_a_policy() -> None:
    observation = {"team": {"roster": [{"id": index} for index in range(24)]}}
    assert build_puzzles.gate({"agent": "random"}, observation, _options(2)) == "excluded subject"


def test_an_unreadably_long_option_is_dropped() -> None:
    observation = {"team": {"roster": [{"id": index} for index in range(24)]}}
    long_option = {"actions": [{"type": "release", "player_id": i} for i in range(9)]}
    reason = build_puzzles.gate({"agent": "value"}, observation, [*_options(1), long_option])
    assert reason == "an option is too long to read"


def test_a_healthy_window_passes_the_gates() -> None:
    observation = {"team": {"roster": [{"id": index} for index in range(24)]}}
    assert build_puzzles.gate({"agent": "value"}, observation, _options(2)) is None


def test_dedupe_keeps_the_sharpest_card_per_state() -> None:
    cards = [
        {"state_key": "s1-y1-draft", "worthiness": 9.0, "id": "keep"},
        {"state_key": "s1-y1-draft", "worthiness": 2.0, "id": "drop"},
        {"state_key": "s1-y2-draft", "worthiness": 1.0, "id": "other"},
    ]
    kept = build_puzzles._dedupe_by_state(cards, Counter())
    assert [card["id"] for card in kept] == ["keep", "other"]


# -- rendering -------------------------------------------------------------


PLAYERS = {
    7: {"id": 7, "name": "Finn Frost", "position": "F", "overall": 78.2},
    9: {"id": 9, "name": "Owen Jensen", "position": "G", "overall": 58.4},
}
TEAMS = {1: "Austin Jackals"}


def test_signing_reads_as_a_sentence() -> None:
    action = {"type": "sign_free_agent", "player_id": 7, "salary": 9.487, "years": 4}
    assert build_puzzles.describe_action(action, PLAYERS, TEAMS) == "Sign Finn Frost (F 78) for $9.49M x 4y"


def test_a_trade_names_the_partner_and_both_sides() -> None:
    action = {
        "type": "trade",
        "partner_team_id": 1,
        "give_player_ids": [7],
        "receive_pick_seasons": [4],
    }
    rendered = build_puzzles.describe_action(action, PLAYERS, TEAMS)
    assert rendered == "Trade Finn Frost (F 78) to Austin Jackals for their season-4 first-round pick"


def test_an_unknown_team_does_not_break_a_trade_line() -> None:
    action = {"type": "trade", "partner_team_id": 99, "give_player_ids": [9], "receive_player_ids": [7]}
    assert "another team" in build_puzzles.describe_action(action, PLAYERS, TEAMS)


def test_doing_nothing_is_described_as_a_choice() -> None:
    assert build_puzzles.describe_option([{"type": "noop"}], PLAYERS, TEAMS) == [
        "Stand pat - make no roster move this window"
    ]


def test_summary_names_both_sides_of_a_trade_off() -> None:
    """A pick-for-player swap is not 'gave up asset value'; it is an exchange."""
    delta = _delta(
        total_assets=-9.9,
        total_assets_contribution=-1.6,
        cap_room=4.5,
        cap_room_contribution=1.6,
    )
    summary = build_puzzles.headline_metric(delta)
    assert "gained 4.5 of cap room" in summary
    assert "gave up 9.9 of asset value" in summary


def test_summary_says_so_when_nothing_moved() -> None:
    assert build_puzzles.headline_metric(_delta()) == "barely moved the roster"


def test_summary_reports_a_one_sided_option_once() -> None:
    delta = _delta(young_assets=54.7, young_assets_contribution=9.8)
    assert build_puzzles.headline_metric(delta) == "gained 54.7 of young asset value"


def test_player_index_finds_players_across_every_bucket() -> None:
    observation = {
        "team": {"roster": [{"id": 1, "name": "A"}]},
        "free_agents": [{"id": 2, "name": "B"}],
        "waiver_wire": [{"id": 3, "name": "C"}],
        "draft_class": [{"id": 4, "name": "D"}],
        "trade_market": [{"player": {"id": 5, "name": "E"}}],
    }
    assert sorted(build_puzzles.player_index(observation)) == [1, 2, 3, 4, 5]


def test_team_index_reads_the_standings_naming_key() -> None:
    observation = {"standings": [{"team_id": 3, "team_name": "Anchorage Auroras"}]}
    assert build_puzzles.team_index(observation)[3] == "Anchorage Auroras"
