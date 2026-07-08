"""Tests for opponent-initiated trade offers."""

from __future__ import annotations

from typing import Any

from gm_bench.agents import Agent, ValueAgent
from gm_bench.runner import run_many
from gm_bench.simulator import TRADE_LIMIT_PER_PARTNER, League


def observed_offers(league: League) -> list[dict[str, Any]]:
    """Publish offers the way the runner does: generate once, then observe."""
    league.prepare_trade_deadline()
    return league.observation("trade_deadline")["incoming_offers"]


def test_offers_are_published_and_deterministic():
    offers_a = observed_offers(League.new(seed=7))
    offers_b = observed_offers(League.new(seed=7))
    assert offers_a == offers_b
    assert offers_a, "expected at least one incoming offer on seed 7"
    for offer in offers_a:
        assert offer["you_receive_players"], "partner must give something"
        assert offer["they_receive_players"], "partner must ask for something"


def test_observation_does_not_regenerate_offers_across_rounds():
    """Multi-round observation must not resurrect an accepted/declined offer."""
    league = League.new(seed=7)
    league.prepare_trade_deadline()
    offer_id = league.observation("trade_deadline")["incoming_offers"][0]["offer_id"]
    league.apply_actions([{"type": "decline_offer", "offer_id": offer_id}], "trade_deadline")
    assert offer_id not in league.current_offers
    republished = {offer["offer_id"] for offer in league.observation("trade_deadline")["incoming_offers"]}
    assert offer_id not in republished


def test_accept_offer_transfers_players_and_counts_partner_limit():
    league = League.new(seed=7)
    offer = observed_offers(league)[0]
    partner = league.teams[offer["team_id"]]
    incoming = offer["you_receive_players"][0]["id"]
    outgoing = offer["they_receive_players"][0]["id"]
    league.apply_actions([{"type": "accept_offer", "offer_id": offer["offer_id"]}], "trade_deadline")
    assert league.transactions[-1].accepted
    assert incoming in league.user_team.roster
    assert outgoing in partner.roster
    assert league.partner_trades[partner.id] == 1
    assert league.illegal_actions == 0


def test_accept_unknown_or_expired_offer_is_illegal():
    league = League.new(seed=7)
    observed_offers(league)
    league.apply_actions([{"type": "accept_offer", "offer_id": "offer-nope"}], "trade_deadline")
    assert not league.transactions[-1].accepted
    assert league.illegal_actions == 1
    # Offers expire when the next trade-deadline window re-rolls the pool.
    league_2 = League.new(seed=7)
    stale = observed_offers(league_2)[0]["offer_id"]
    league_2.simulate_season()
    league_2.prepare_trade_deadline()
    league_2.apply_actions([{"type": "accept_offer", "offer_id": stale}], "trade_deadline")
    if stale not in league_2.current_offers:
        assert not league_2.transactions[-1].accepted


def test_decline_offer_is_free_and_removes_offer():
    league = League.new(seed=7)
    offer_id = observed_offers(league)[0]["offer_id"]
    league.apply_actions([{"type": "decline_offer", "offer_id": offer_id}], "trade_deadline")
    assert league.transactions[-1].accepted
    assert league.illegal_actions == 0
    assert offer_id not in league.current_offers
    league.apply_actions([{"type": "accept_offer", "offer_id": offer_id}], "trade_deadline")
    assert not league.transactions[-1].accepted


def test_partner_at_trade_limit_sends_no_offers():
    league = League.new(seed=7)
    for team_id in league.teams:
        if team_id != league.user_team_id:
            league.partner_trades[team_id] = TRADE_LIMIT_PER_PARTNER
    assert observed_offers(league) == []


class AcceptEverythingAgent(Agent):
    """Naive agent that accepts every incoming offer and otherwise stands pat."""

    name = "accept-everything"

    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = [
            {"type": "accept_offer", "offer_id": offer["offer_id"]} for offer in observation.get("incoming_offers", [])
        ]
        if observation["phase"] == "draft" and observation["draft_class"]:
            best = max(
                observation["draft_class"],
                key=lambda prospect: prospect["potential"] * 0.6 + prospect["overall"] * 0.4,
            )
            actions.append({"type": "draft", "prospect_id": best["id"]})
        return actions or [{"type": "noop"}]


def test_accepting_everything_underperforms_value_agent():
    """Offers must contain traps: blind acceptance cannot beat selective play."""
    seeds = [1, 2, 3]
    naive = run_many(AcceptEverythingAgent(), seeds=seeds, seasons=3, workers=1)
    value = run_many(ValueAgent(), seeds=seeds, seasons=3, workers=1)
    assert naive["summary"]["mean_score"] < value["summary"]["mean_score"]


def test_ignoring_offers_leaves_scripted_scores_unchanged():
    """Offer publication must not perturb the RNG stream or penalize inaction."""
    result = run_many(ValueAgent(), seeds=[1], seasons=2, workers=1)
    assert result["summary"]["illegal_actions"] == 0
