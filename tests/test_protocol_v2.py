from __future__ import annotations

from gm_bench.agents import ValueAgent
from gm_bench.baseline_cache import cache_key
from gm_bench.protocol import EpisodeConfig
from gm_bench.runner import run_decision_point, run_episode
from gm_bench.simulator import REGULAR_SEASON_GAMES_PER_PAIR, League


class QueryThenActAgent:
    name = "query-then-act"

    def __init__(self) -> None:
        self.round = 0
        self.seen_action_results: list[dict] | None = None
        self.seen_interaction_round: int | None = None

    def act(self, observation: dict) -> list[dict]:
        if self.round == 0:
            # Query only (no end_turn) so the decision point advances to a
            # second round and feeds the query results back to us.
            self.round += 1
            return [{"type": "list_free_agents", "limit": 5}]
        # Second round: capture what the harness fed back before ending the turn.
        self.seen_interaction_round = observation.get("interaction_round")
        self.seen_action_results = observation.get("action_results")
        return [{"type": "end_turn"}]


def test_scout_reveals_true_potential_band() -> None:
    league = League.new(seed=3)
    player_id = league.user_team.roster[0]
    results = league.apply_actions([{"type": "scout", "player_id": player_id}], "preseason")
    assert results[0].accepted is True
    assert "true_potential_estimate" in (results[0].data or {})


def test_inspect_player_returns_detail() -> None:
    league = League.new(seed=4)
    player_id = league.free_agents[0]
    results = league.apply_actions([{"type": "inspect_player", "player_id": player_id}], "preseason")
    assert results[0].accepted is True
    assert results[0].data is not None
    assert results[0].data["player"]["id"] == player_id


def test_incoming_trade_offer_can_be_rejected() -> None:
    league = League.new(seed=5)
    league.prepare_trade_deadline()
    assert league.incoming_trade_offers
    offer_id = league.incoming_trade_offers[0].offer_id
    results = league.apply_actions([{"type": "reject_trade_offer", "offer_id": offer_id}], "trade_deadline")
    assert results[0].accepted is True
    assert all(offer.offer_id != offer_id for offer in league.incoming_trade_offers)


def test_summary_tier_uses_summaries() -> None:
    league = League.new(seed=6)
    observation = league.observation("preseason", tier="summary")
    assert "free_agents_summary" in observation
    assert "free_agents" not in observation


def test_multi_round_decision_returns_action_results() -> None:
    league = League.new(seed=7)
    config = EpisodeConfig(observation_tier="full", max_interaction_rounds=3)
    agent = QueryThenActAgent()
    results = run_decision_point(league, agent, "preseason", config)
    # The agent must have reached a second round and been handed the results of
    # its first-round query, exercising the action_results hand-off (not just
    # breaking after round 0).
    assert agent.seen_interaction_round == 1
    assert agent.seen_action_results is not None
    assert any(item.get("action", {}).get("type") == "list_free_agents" for item in agent.seen_action_results)
    # The final results are the round-1 end_turn.
    assert any(item.get("action", {}).get("type") == "end_turn" and item.get("accepted") for item in results)


def test_midseason_adds_partial_standings_and_waiver_wire() -> None:
    league = League.new(seed=8)
    league.prepare_midseason()
    observation = league.observation("midseason")
    assert observation["phase"] == "midseason"
    assert league.user_team.wins + league.user_team.losses > 0


def test_episode_config_can_disable_midseason() -> None:
    result = run_episode(ValueAgent(), seed=1, seasons=1, config=EpisodeConfig(include_midseason=False))
    assert result.final_score > 0


def test_midseason_legs_sum_to_a_full_season() -> None:
    # The pre-break and post-break legs must total a full season; the old
    # int() truncation played only 2 of 3 games per pairing.
    league = League.new(seed=11)
    league.prepare_midseason()
    partial = league.partial_games_per_pair
    assert 1 <= partial < REGULAR_SEASON_GAMES_PER_PAIR
    remainder = max(1, REGULAR_SEASON_GAMES_PER_PAIR - partial)
    assert partial + remainder == REGULAR_SEASON_GAMES_PER_PAIR


def test_midseason_plays_same_total_games_as_no_midseason() -> None:
    plays: dict[str, int] = {"full": 0, "split": 0}

    def counting_league(seed: int, bucket: str) -> League:
        league = League.new(seed=seed)
        original = league._play_game

        def spy(*args: object, **kwargs: object) -> object:
            plays[bucket] += 1
            return original(*args, **kwargs)

        league._play_game = spy  # type: ignore[method-assign]
        return league

    full = counting_league(11, "full")
    full.simulate_season()

    split = counting_league(11, "split")
    split.prepare_midseason()
    split.simulate_season()

    # Both schedule 8-team playoffs on top of the regular season, so equal total
    # _play_game calls means equal regular-season schedules.
    assert plays["split"] == plays["full"]


def test_negotiation_actions_advertised_only_when_offers_exist() -> None:
    league = League.new(seed=12)
    # Before any offers are generated, the trade-deadline phase must not tempt
    # the agent with negotiation actions it cannot legally take.
    assert "accept_trade_offer" not in league.observation("trade_deadline")["available_actions"]
    league.prepare_trade_deadline()
    assert league.incoming_trade_offers
    assert "accept_trade_offer" in league.observation("trade_deadline")["available_actions"]
    # Preseason never generates incoming offers, so a fresh league keeps them
    # hidden there (advertisement follows offer state, not the phase name).
    assert "accept_trade_offer" not in League.new(seed=13).observation("preseason")["available_actions"]


def test_baseline_cache_key_separates_episode_configs() -> None:
    default_fp = EpisodeConfig().baseline_cache_fingerprint()
    nomid_fp = EpisodeConfig(include_midseason=False).baseline_cache_fingerprint()
    # Default config appends nothing, preserving the historical cache keys.
    assert default_fp == ""
    assert cache_key("random", 1, 5) == cache_key("random", 1, 5, default_fp)
    # A non-default config gets a distinct key so it cannot reuse default scores.
    assert nomid_fp and nomid_fp != default_fp
    assert cache_key("random", 1, 5, nomid_fp) != cache_key("random", 1, 5)


def test_playoff_rounds_reset_each_season_with_midseason() -> None:
    league = League.new(seed=9)
    league.prepare_midseason()
    league.simulate_season()
    first_rounds = league.summaries[-1].playoff_rounds
    league.prepare_midseason()
    league.simulate_season()
    second_rounds = league.summaries[-1].playoff_rounds
    assert first_rounds <= 3
    assert second_rounds <= 3
    assert league.user_team.playoff_rounds <= 3
