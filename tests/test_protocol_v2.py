from __future__ import annotations

from gm_bench.agents import ValueAgent
from gm_bench.protocol import EpisodeConfig
from gm_bench.runner import run_decision_point, run_episode
from gm_bench.simulator import League


class QueryThenActAgent:
    name = "query-then-act"

    def __init__(self) -> None:
        self.round = 0

    def act(self, observation: dict) -> list[dict]:
        if self.round == 0:
            self.round += 1
            return [{"type": "list_free_agents", "limit": 5}, {"type": "end_turn"}]
        return ValueAgent().act(observation)


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
    results = run_decision_point(league, QueryThenActAgent(), "preseason", config)
    assert any(item.get("accepted") for item in results)


def test_midseason_adds_partial_standings_and_waiver_wire() -> None:
    league = League.new(seed=8)
    league.prepare_midseason()
    observation = league.observation("midseason")
    assert observation["phase"] == "midseason"
    assert league.user_team.wins + league.user_team.losses > 0


def test_episode_config_can_disable_midseason() -> None:
    result = run_episode(ValueAgent(), seed=1, seasons=1, config=EpisodeConfig(include_midseason=False))
    assert result.final_score > 0
