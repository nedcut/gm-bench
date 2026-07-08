from __future__ import annotations

from gm_bench.agents import AGENTS, PickTraderAgent, StrategicAgent
from gm_bench.simulator import League


def test_strategic_references_are_registered() -> None:
    assert AGENTS["strategic"] is StrategicAgent
    assert AGENTS["pick-trader"] is PickTraderAgent


def test_strategic_scouts_before_using_reports_to_draft() -> None:
    league = League.new(seed=11)
    agent = StrategicAgent()

    for interaction_round in range(3):
        observation = league.observation("draft", interaction_round=interaction_round)
        actions = agent.act(observation)
        assert [action["type"] for action in actions] == ["scout"]
        league.apply_actions(actions, "draft")

    observation = league.observation("draft", interaction_round=3)
    actions = agent.act(observation)
    assert "draft" in {action["type"] for action in actions}
    drafted_id = next(action["prospect_id"] for action in actions if action["type"] == "draft")
    reports = observation["scout_reports"]
    expected = max(
        observation["draft_class"],
        key=lambda player: agent._scouted_value(player, reports),
    )
    assert drafted_id == expected["id"]
