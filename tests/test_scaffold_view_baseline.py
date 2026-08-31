from __future__ import annotations

import json
import math
from typing import Any

import pytest

from examples import gm_agent_common
from gm_bench.agents import AGENTS, PickTraderAgent, ScaffoldViewAgent
from gm_bench.benchmark_config import PRESETS
from gm_bench.runner import run_episode, run_many
from gm_bench.scaffold_view import compact_observation, scaffold_view_observation
from gm_bench.simulator import League


@pytest.fixture(autouse=True)
def _compact_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    # Importing an example adapter sets GM_AGENT_PROFILE process-wide, so the
    # profile under test is pinned rather than inherited.
    monkeypatch.setenv("GM_AGENT_PROFILE", "compact")


def _capture_view(
    monkeypatch: pytest.MonkeyPatch,
    observation: dict[str, Any],
    profile: str | None = None,
) -> dict[str, Any]:
    """Run the agent and return the observation its policy was actually handed."""
    seen: list[dict[str, Any]] = []
    original = PickTraderAgent.act

    def spy(self: PickTraderAgent, obs: dict[str, Any]) -> list[dict[str, Any]]:
        seen.append(obs)
        return original(self, obs)

    monkeypatch.setattr(PickTraderAgent, "act", spy)
    ScaffoldViewAgent(profile).act(observation)
    assert len(seen) == 1
    return seen[0]


def test_scaffold_view_is_registered_as_a_baseline() -> None:
    assert AGENTS["scaffold-view"] is ScaffoldViewAgent
    assert issubclass(ScaffoldViewAgent, PickTraderAgent)
    assert ScaffoldViewAgent().name == "scaffold-view"
    # Non-default profiles must not share the registered cache identity.
    assert ScaffoldViewAgent("tiny").name == "scaffold-view:tiny"


def test_adapter_and_reference_share_one_compaction() -> None:
    # Not equality of two implementations -- there is only one, re-exported.
    assert gm_agent_common.compact_observation is compact_observation

    league = League.new(seed=11)
    observation = league.observation("offseason")
    compact = compact_observation(observation)
    view = scaffold_view_observation(observation)

    assert view["team"]["roster"] == compact["team"]["top_roster"]
    for key in ("free_agents", "draft_class", "trade_market", "incoming_offers", "rules", "scout_reports"):
        assert view[key] == compact[key]


def test_model_prompt_and_scaffold_view_do_not_expose_seed() -> None:
    league = League.new(seed=9_876_543_210)
    observation = league.observation("preseason")

    compact = compact_observation(observation)
    view = scaffold_view_observation(observation)
    prompt = gm_agent_common.build_prompt(observation)
    prompt_payload = json.loads(prompt.rsplit("Observation JSON:\n", maxsplit=1)[1])

    assert observation["seed"] == 9_876_543_210
    assert "seed" not in compact
    assert "seed" not in view
    assert "seed" not in prompt_payload


def test_scaffold_view_policy_receives_the_truncated_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    league = League.new(seed=11)
    observation = league.observation("offseason")
    assert len(observation["free_agents"]) > 16
    assert len(observation["trade_market"]) > 12

    view = _capture_view(monkeypatch, observation)

    assert len(view["free_agents"]) == 16
    assert len(view["draft_class"]) <= 16
    assert len(view["trade_market"]) == 12
    assert len(view["incoming_offers"]) <= 3
    assert view["free_agents"] == compact_observation(observation)["free_agents"]
    # Fields the scaffold drops entirely stay dropped.
    assert "standings" not in view
    assert "waiver_wire" not in view


def test_pick_trader_still_sees_the_untruncated_observation(monkeypatch: pytest.MonkeyPatch) -> None:
    league = League.new(seed=11)
    observation = league.observation("offseason")
    seen: list[dict[str, Any]] = []
    original = PickTraderAgent.act

    def spy(self: PickTraderAgent, obs: dict[str, Any]) -> list[dict[str, Any]]:
        seen.append(obs)
        return original(self, obs)

    monkeypatch.setattr(PickTraderAgent, "act", spy)
    PickTraderAgent().act(observation)
    assert seen[0]["free_agents"] == observation["free_agents"]
    assert seen[0]["trade_market"] == observation["trade_market"]


def test_scaffold_view_draft_class_truncation(monkeypatch: pytest.MonkeyPatch) -> None:
    league = League.new(seed=11)
    observation = league.observation("draft")
    assert len(observation["draft_class"]) > 16

    view = _capture_view(monkeypatch, observation)

    assert len(view["draft_class"]) == 16


def test_scaffold_view_actions_are_legal_across_phases() -> None:
    league = League.new(seed=11)
    agent = ScaffoldViewAgent()
    for phase in ("preseason", "offseason", "midseason", "draft"):
        actions = agent.act(league.observation(phase))
        results = league.apply_actions(actions, phase)
        assert league.illegal_actions == 0, [item.to_dict() for item in results if not item.accepted]


def test_scaffold_view_episode_runs_clean() -> None:
    result = run_episode(ScaffoldViewAgent(), seed=11, seasons=2)
    assert result.illegal_actions == 0
    assert result.protocol_penalty == 0.0


def test_scaffold_view_and_pick_trader_leaderboard_seed_smoke() -> None:
    """Official panel seed 11 at leaderboard season count must run without error."""
    seed = PRESETS["leaderboard"]["seeds"][0]
    seasons = PRESETS["leaderboard"]["seasons"]
    scaffold = run_many(ScaffoldViewAgent(), seeds=[seed], seasons=seasons, workers=1)
    pick_trader = run_many(PickTraderAgent(), seeds=[seed], seasons=seasons, workers=1)
    scaffold_score = scaffold["summary"]["mean_score"]
    pick_trader_score = pick_trader["summary"]["mean_score"]
    assert math.isfinite(scaffold_score)
    assert math.isfinite(pick_trader_score)
    # Seed 11 ties on the official panel; re-pinned for the v6 draft lottery,
    # again for v6 free-agent willingness, and again for v6 lineup
    # construction (an extra generator RNG draw per forward).
    # Pin the score so contract drift cannot silently invalidate the run log.
    assert scaffold_score == pytest.approx(pick_trader_score)
    assert scaffold_score == pytest.approx(236.328, abs=0.001)


def test_tiny_profile_still_yields_a_legal_lineup() -> None:
    # The tiny profile truncates the roster to 18, so the host-computed lineup
    # the prompt gives every model is the only thing keeping the view playable.
    league = League.new(seed=13)
    observation = league.observation("preseason")
    view = scaffold_view_observation(observation, "tiny")
    # The policy alone cannot dress a legal lineup from this truncated roster.
    assert not [action for action in PickTraderAgent().act(view) if action["type"] == "set_lineup"]

    actions = ScaffoldViewAgent("tiny").act(observation)
    lineups = [action for action in actions if action["type"] == "set_lineup"]
    assert len(lineups) == 1
    assert lineups[0]["player_ids"] == view["scaffold_fallback_lineup"]
    results = league.apply_actions(actions, "preseason")
    lineup_result = next(item for item in results if item.action["type"] == "set_lineup")
    assert lineup_result.accepted, lineup_result.message
    assert league.illegal_actions == 0


def test_tiny_profile_episode_takes_no_protocol_penalty() -> None:
    # The injected lineup is computed before the batch runs, so a deadline that
    # also releases or trades a player must not dress a departed one.
    result = run_episode(ScaffoldViewAgent("tiny"), seed=11, seasons=2)
    assert result.illegal_actions == 0
    assert result.protocol_penalty == 0.0


def test_tiny_profile_zeroes_the_trade_market(monkeypatch: pytest.MonkeyPatch) -> None:
    league = League.new(seed=11)
    view = _capture_view(monkeypatch, league.observation("offseason"), "tiny")
    assert view["trade_market"] == []
    assert len(view["team"]["roster"]) <= 18


def test_ambient_profile_cannot_decide_the_reference_view(monkeypatch: pytest.MonkeyPatch) -> None:
    """The registered baseline is pinned, not inherited.

    This agent runs in the harness process, where GM_AGENT_PROFILE reflects the
    operator's shell rather than the lane the model ran under. If it inherited,
    an ambient "tiny" would quietly hand the reference a different view than the
    row it is being differenced against, and the cached episode would carry no
    trace of which view produced it.
    """
    monkeypatch.setenv("GM_AGENT_PROFILE", "tiny")
    league = League.new(seed=11)
    view = _capture_view(monkeypatch, league.observation("offseason"))
    assert len(view["trade_market"]) == 12
    assert ScaffoldViewAgent().profile == "compact"


def test_tiny_profile_does_not_share_the_compact_cache_key() -> None:
    from gm_bench.baseline_cache import cache_key

    compact = ScaffoldViewAgent()
    tiny = ScaffoldViewAgent("tiny")
    assert cache_key(compact.name, 11, 5) != cache_key(tiny.name, 11, 5)
