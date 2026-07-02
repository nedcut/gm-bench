"""Tests for the benchmark-validity fixes: trade realism, real lineups,
competitive drafts, the memo scratchpad, FA aging, and the score split."""

from __future__ import annotations

from gm_bench.agents import ExploitAgent, ValueAgent
from gm_bench.models import LINEUP_MIN_POSITIONS, LINEUP_SIZE, ROSTER_MIN
from gm_bench.runner import run_episode
from gm_bench.scoring import score_breakdown
from gm_bench.simulator import MEMO_MAX_CHARS, TRADE_LIMIT_PER_PARTNER, League


def _lopsided_trade(league: League, partner_id: int) -> dict[str, object]:
    """A trade the partner clearly wants: user's best asset for partner's worst."""
    give_id = max(league.user_team.roster, key=lambda pid: league.players[pid].asset_value)
    receive_id = min(league.teams[partner_id].roster, key=lambda pid: league.players[pid].asset_value)
    return {
        "type": "trade",
        "partner_team_id": partner_id,
        "give_player_ids": [give_id],
        "receive_player_ids": [receive_id],
    }


# --- Trade pump closed ---------------------------------------------------


def test_partner_trade_limit_per_season() -> None:
    league = League.new(seed=8)
    partner_id = 1
    for _ in range(TRADE_LIMIT_PER_PARTNER):
        league.apply_actions([_lopsided_trade(league, partner_id)], "preseason")
        assert league.transactions[-1].accepted is True
    league.apply_actions([_lopsided_trade(league, partner_id)], "preseason")
    assert league.transactions[-1].accepted is False
    assert "appetite" in league.transactions[-1].message


def test_partner_trade_limit_resets_each_season() -> None:
    league = League.new(seed=8)
    partner_id = 1
    for _ in range(TRADE_LIMIT_PER_PARTNER):
        league.apply_actions([_lopsided_trade(league, partner_id)], "preseason")
        assert league.transactions[-1].accepted is True
    league.simulate_season()
    league.apply_actions([_lopsided_trade(league, partner_id)], "preseason")
    assert league.transactions[-1].accepted is True


def test_trade_cannot_drop_either_roster_below_minimum() -> None:
    league = League.new(seed=8)
    partner = league.teams[2]
    # Strip the partner below the floor: request many players for one good one.
    receive = partner.roster[: len(partner.roster) - ROSTER_MIN + 2]
    give = [max(league.user_team.roster, key=lambda pid: league.players[pid].asset_value)]
    league.apply_actions(
        [{"type": "trade", "partner_team_id": 2, "give_player_ids": give, "receive_player_ids": receive}],
        "preseason",
    )
    assert league.transactions[-1].accepted is False
    assert "minimum" in league.transactions[-1].message


def test_release_cannot_drop_roster_below_minimum() -> None:
    league = League.new(seed=8)
    while len(league.user_team.roster) > ROSTER_MIN:
        league.apply_actions([{"type": "release", "player_id": league.user_team.roster[-1]}], "preseason")
        assert league.transactions[-1].accepted is True
    league.apply_actions([{"type": "release", "player_id": league.user_team.roster[-1]}], "preseason")
    assert league.transactions[-1].accepted is False
    assert "minimum" in league.transactions[-1].message


def test_partner_valuation_bias_is_hidden_deterministic_and_bounded() -> None:
    league_a = League.new(seed=13)
    league_b = League.new(seed=13)
    for partner_id in (1, 2, 3):
        for player_id in list(league_a.players)[:20]:
            bias_a = league_a._partner_valuation_bias(partner_id, player_id)
            bias_b = league_b._partner_valuation_bias(partner_id, player_id)
            assert bias_a == bias_b
            assert 0.9 <= bias_a <= 1.1


def test_exploit_agent_no_longer_beats_honest_baselines() -> None:
    """Red-team canary: the trade-pump/FA-hoard strategy must not dominate.

    Pre-fix, value pumping gained up to +28% asset value per trade and this
    agent's strategy would have out-scored `value`. Both runs are fully
    deterministic, so this assertion is stable until the rules change again.
    """
    exploit = run_episode(ExploitAgent(), seed=1, seasons=5)
    value = run_episode(ValueAgent(), seed=1, seasons=5)
    assert exploit.final_score < value.final_score
    assert exploit.strategy_score < value.strategy_score


# --- Lineups are real ----------------------------------------------------


def test_set_lineup_changes_team_strength() -> None:
    league = League.new(seed=4)
    auto_strength = league._team_strength(league.user_team, apply_injury_noise=False)
    roster = sorted(league.user_team.roster, key=lambda pid: league.players[pid].overall)
    # Build a legal lineup biased toward the weakest players.
    weak_first = [league.players[pid].public_dict() for pid in roster]
    from gm_bench.agent_utils import position_aware_lineup

    weak_lineup = position_aware_lineup(weak_first, lambda player: -player["overall"])
    league.apply_actions([{"type": "set_lineup", "player_ids": weak_lineup}], "preseason")
    assert league.transactions[-1].accepted is True
    weak_strength = league._team_strength(league.user_team, apply_injury_noise=False)
    assert weak_strength < auto_strength


def test_effective_lineup_repairs_stale_entries_and_position_minimums() -> None:
    league = League.new(seed=4)
    team = league.user_team
    # A stale lineup full of ids not on the roster must repair into a legal lineup.
    team.lineup = [-1, -2, -3]
    lineup = league._effective_lineup(team)
    assert len(lineup) == LINEUP_SIZE
    for position, minimum in LINEUP_MIN_POSITIONS.items():
        assert sum(1 for player in lineup if player.position == position) >= minimum


def test_lineup_players_develop_faster_than_bench() -> None:
    """Aging is applied with an identical RNG in both scenarios, so the only
    difference is the playing-time multiplier — dressed development must win."""
    import random

    def run(dress_young: bool) -> float:
        league = League.new(seed=6)
        roster = league.user_team.roster
        # A young player with real growth room, so the usage multiplier matters.
        young_id = max(
            (pid for pid in roster if league.players[pid].age <= 22),
            key=lambda pid: league.players[pid].true_potential - league.players[pid].overall,
        )
        players = [league.players[pid].public_dict() for pid in roster]
        from gm_bench.agent_utils import position_aware_lineup

        # Dress the young player when requested, bury them otherwise.
        def rank(player: dict[str, object]) -> float:
            if player["id"] == young_id:
                return 1000.0 if dress_young else -1000.0
            return float(player["overall"])

        lineup = position_aware_lineup(players, rank)
        league.apply_actions([{"type": "set_lineup", "player_ids": lineup}], "preseason")
        assert league.transactions[-1].accepted is True
        assert (young_id in lineup) == dress_young
        league._age_and_contracts(random.Random("fixed-development-test"))
        return league.players[young_id].overall

    assert run(dress_young=True) > run(dress_young=False)


# --- Competitive draft ---------------------------------------------------


def test_opponents_draft_prospects_every_season() -> None:
    result = run_episode(ValueAgent(), seed=3, seasons=2)
    opponent_picks = [
        transaction
        for transaction in result.transactions
        if transaction["phase"] == "draft" and transaction["team_id"] != 0 and transaction["accepted"]
    ]
    # 11 opponents pick each season.
    assert len(opponent_picks) == 22


def test_draft_order_is_inverse_standings() -> None:
    league = League.new(seed=5)
    league.teams[3].wins = 0
    league.teams[7].wins = 40
    order = league._draft_order()
    assert order.index(3) < order.index(7)


def test_user_pick_slot_respects_standings() -> None:
    league = League.new(seed=5)
    for team in league.teams.values():
        team.wins = 30 if team.id != league.user_team_id else 0
    class_size_before = len(league.prospects)
    league.run_opponent_draft(before_user=True)
    # Worst record → user picks first, nobody drafts ahead.
    assert len(league.prospects) == class_size_before
    league.run_opponent_draft(before_user=False)
    assert len(league.prospects) == class_size_before - (league.num_teams - 1)


def test_draft_picks_replenish_beyond_generated_years() -> None:
    result = run_episode(ValueAgent(), seed=2, seasons=9)
    season_nine_drafts = [
        transaction
        for transaction in result.transactions
        if transaction["phase"] == "draft"
        and transaction["season"] == 9
        and transaction["team_id"] == 0
        and transaction["accepted"]
    ]
    assert season_nine_drafts, "the user's draft pick should still exist in season 9"


# --- Competitive free agency and opponent trades ---------------------------


def test_opponents_compete_for_standout_free_agents_at_the_deadline() -> None:
    league = League.new(seed=14)
    star_id = league.free_agents[0]
    league.players[star_id].overall = 90.0
    for team in league.teams.values():
        if team.id == league.user_team_id:
            continue
        for player_id in team.roster:
            league.players[player_id].salary = 1.0
    league.run_autopilot_opponents("trade_deadline")
    assert league.players[star_id].team_id is not None
    assert star_id not in league.free_agents


def test_opponent_trades_are_one_for_one_between_opponents() -> None:
    result = run_episode(ValueAgent(), seed=1, seasons=5)
    ai_trades = [
        transaction
        for transaction in result.transactions
        if transaction["team_id"] != 0 and transaction["action"].get("type") == "trade"
    ]
    assert ai_trades, "opponents should trade among themselves over five seasons"
    for transaction in ai_trades:
        action = transaction["action"]
        assert transaction["accepted"] is True
        assert len(action["give_player_ids"]) == 1
        assert len(action["receive_player_ids"]) == 1
        assert action["partner_team_id"] != 0


def test_opponent_activity_does_not_touch_user_roster_or_penalties() -> None:
    league = League.new(seed=14)
    roster_before = list(league.user_team.roster)
    for phase in ("preseason", "trade_deadline", "draft"):
        league.run_autopilot_opponents(phase)
    assert league.user_team.roster == roster_before
    assert league.illegal_actions == 0


# --- Memo scratchpad ------------------------------------------------------


def test_memo_round_trips_through_observation() -> None:
    league = League.new(seed=10)
    league.apply_actions([{"type": "memo", "text": "rebuild until season 3, then buy"}], "preseason")
    assert league.transactions[-1].accepted is True
    assert league.observation("trade_deadline")["memo"] == "rebuild until season 3, then buy"
    assert league.illegal_actions == 0


def test_memo_is_truncated_and_type_checked() -> None:
    league = League.new(seed=10)
    league.apply_actions([{"type": "memo", "text": "x" * (MEMO_MAX_CHARS + 500)}], "preseason")
    assert len(league.observation("preseason")["memo"]) == MEMO_MAX_CHARS
    league.apply_actions([{"type": "memo", "text": 42}], "preseason")
    assert league.transactions[-1].accepted is False


# --- Aging and score split -------------------------------------------------


def test_free_agents_age_between_seasons() -> None:
    league = League.new(seed=12)
    fa_id = league.free_agents[0]
    age_before = league.players[fa_id].age
    league.simulate_season()
    assert league.players[fa_id].age == age_before + 1


def test_score_breakdown_splits_strategy_and_protocol() -> None:
    league = League.new(seed=5)
    league.illegal_actions = 4
    breakdown = score_breakdown(league, league.user_team_id)
    assert breakdown["protocol_penalty"] == 10.0
    assert breakdown["final_score"] == breakdown["strategy_score"] - breakdown["protocol_penalty"]


def test_episode_reports_score_split_consistently() -> None:
    result = run_episode(ExploitAgent(), seed=1, seasons=2)
    assert result.protocol_penalty == result.illegal_actions * 2.5
    assert result.final_score == round(result.strategy_score - result.protocol_penalty, 3)
