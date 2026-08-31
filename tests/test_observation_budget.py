"""The v6 observation budget and the mechanics the compact render must keep.

Two things are pinned here. The prompt a model actually receives has to fit the
v6 execution rule -- target ~6,500 tokens, hard ceiling 8,000 -- across seeds
and into the fat late seasons, even against an agent that deliberately inflates
every part of the view it controls. And the render has to stay legible: a
mechanic that no longer appears in the rows cannot be played, so each v6
mechanic is asserted to have a visible signal.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from examples import gm_agent_common
from gm_bench.agent_utils import position_aware_lineup, public_asset_value
from gm_bench.protocol import EpisodeConfig
from gm_bench.runner import run_episode
from gm_bench.scaffold_view import compact_observation
from gm_bench.simulator import MEMO_MAX_CHARS, League

# The execution rule is written in tokens, and the repo has no tokenizer
# dependency, so the bound is enforced in characters at a conservative ratio.
# Measured against tiktoken's o200k_base on this render, the prompt runs
# 2.65-2.76 characters per token; 2.6 is below that floor, so a prompt inside
# the character bound is inside the token ceiling with margin. When tiktoken
# happens to be installed the token count itself is checked as well.
CHARS_PER_TOKEN = 2.6
TOKEN_CEILING = 8_000
TOKEN_TARGET = 6_500
BUDGET_SEEDS = (11, 23, 42, 101)


class _BudgetStressAgent:
    """Maximizes every part of the observation the agent itself controls.

    A full 2,000-character notebook every turn, a flood of information actions
    whose answers are echoed back in ``action_results``, and free-agent hoarding
    to grow the roster past the render's row limit. This is the shape of the
    worst case, not a policy anyone would run.

    Under the v6 execution rules this agent gets one round per phase, so only
    its first branch runs: the notebook and the query flood are paid for, but
    the echoed answers never come back and the roster never grows. The second
    branch, and the ``action_results`` rows that make the prompt largest, are
    reachable only through the pre-v6 multi-round lane, which
    ``test_multi_round_lane_worst_case_still_fits`` measures separately.
    """

    name = "budget-stress"

    def __init__(self, sink: list[tuple[int, str, str]]) -> None:
        self.sink = sink
        self.memo = ("Contend by season three; watch expiring deals and lottery odds. " * 40)[:MEMO_MAX_CHARS]

    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        self.sink.append((observation["season"], observation["phase"], gm_agent_common.build_prompt(observation)))
        team = observation["team"]
        roster = team["roster"]
        if int(observation.get("interaction_round", 0)) == 0:
            queries: list[dict[str, Any]] = [{"type": "memo", "text": self.memo}]
            queries += [{"type": "list_free_agents", "limit": 24} for _ in range(3)]
            queries += [{"type": "inspect_team", "team_id": team_id} for team_id in (1, 2, 3)]
            queries += [{"type": "inspect_player", "player_id": player["id"]} for player in roster[:4]]
            for prospect in sorted(observation.get("draft_class", []), key=public_asset_value, reverse=True)[:3]:
                queries.append({"type": "scout", "prospect_id": prospect["id"]})
            return queries
        actions: list[dict[str, Any]] = [{"type": "memo", "text": self.memo}]
        cap_room = team["cap_room"]
        for player in sorted(observation.get("free_agents", []), key=lambda item: item["asking_salary"]):
            if cap_room <= 2 or len(actions) > 10:
                break
            cap_room -= player["asking_salary"]
            actions.append(
                {"type": "sign_free_agent", "player_id": player["id"], "years": 5, "salary": player["asking_salary"]}
            )
        if observation["phase"] == "draft" and observation.get("draft_class"):
            actions.append(
                {"type": "draft", "prospect_id": max(observation["draft_class"], key=public_asset_value)["id"]}
            )
        lineup = position_aware_lineup(roster)
        if lineup:
            actions.append({"type": "set_lineup", "player_ids": lineup})
        return actions

    def act_with_usage(self, observation: dict[str, Any]) -> tuple[list[dict[str, Any]], None]:
        return self.act(observation), None


@pytest.fixture(scope="module")
def stress_prompts() -> list[tuple[int, str, str]]:
    prompts: list[tuple[int, str, str]] = []
    for seed in BUDGET_SEEDS:
        run_episode(_BudgetStressAgent(prompts), seed=seed, seasons=5)
    return prompts


def _token_estimate(prompt: str) -> float:
    return len(prompt) / CHARS_PER_TOKEN


def test_worst_case_prompt_stays_under_the_v6_token_ceiling(stress_prompts: list[tuple[int, str, str]]) -> None:
    worst_season, worst_phase, worst_prompt = max(stress_prompts, key=lambda row: len(row[2]))
    assert _token_estimate(worst_prompt) <= TOKEN_CEILING, (
        f"season {worst_season} {worst_phase} renders ~{_token_estimate(worst_prompt):.0f} tokens"
    )


def test_typical_prompt_stays_near_the_v6_target(stress_prompts: list[tuple[int, str, str]]) -> None:
    estimates = sorted(_token_estimate(prompt) for _, _, prompt in stress_prompts)
    median = estimates[len(estimates) // 2]
    # Near the target from both sides: an over-aggressive cut is also a failure,
    # because the budget the spec sets is meant to be spent on information.
    assert TOKEN_TARGET * 0.6 <= median <= TOKEN_TARGET * 1.1, f"median ~{median:.0f} tokens"


def test_late_seasons_do_not_grow_past_the_ceiling(stress_prompts: list[tuple[int, str, str]]) -> None:
    """Season 5 is the fat case: a full ledger, a grown roster, five history rows."""
    late = [prompt for season, _phase, prompt in stress_prompts if season == 5]
    assert late
    assert max(_token_estimate(prompt) for prompt in late) <= TOKEN_CEILING


def test_token_ceiling_holds_on_a_real_tokenizer(stress_prompts: list[tuple[int, str, str]]) -> None:
    tiktoken = pytest.importorskip("tiktoken", reason="exact token count is checked when a tokenizer is installed")
    encoding = tiktoken.get_encoding("o200k_base")
    worst = max(len(encoding.encode(prompt)) for _, _, prompt in stress_prompts)
    assert worst <= TOKEN_CEILING


def test_multi_round_lane_worst_case_still_fits() -> None:
    """The largest prompt the render can produce, on the lane that can produce it.

    Echoed ``action_results`` are the biggest single block the view carries and
    only appear from interaction round 1 onward, which the v6 one-call lane
    never reaches. Measured here on the exact tokenizer rather than the
    character proxy: this lane's headroom under the ceiling is thinner than the
    proxy's own conservatism, so the proxy cannot certify it.
    """
    tiktoken = pytest.importorskip("tiktoken", reason="this lane is too close to the ceiling for the char proxy")
    encoding = tiktoken.get_encoding("o200k_base")
    prompts: list[tuple[int, str, str]] = []
    config = EpisodeConfig(single_paid_call_per_phase=False)
    for seed in BUDGET_SEEDS:
        run_episode(_BudgetStressAgent(prompts), seed=seed, seasons=5, config=config)
    echoed = [prompt for _, _, prompt in prompts if '"interaction_round": 1' in prompt]
    assert echoed, "no prompt reached a second round, so nothing echoed query results"
    assert all('"action_results": ["ok|' in prompt for prompt in echoed)
    assert max(len(encoding.encode(prompt)) for _, _, prompt in prompts) <= TOKEN_CEILING


def _rendered(league: League, phase: str) -> dict[str, Any]:
    return compact_observation(league.observation(phase), "compact")


def test_every_v6_mechanic_has_a_visible_signal() -> None:
    league = League.new(seed=11)
    rendered = _rendered(league, "preseason")
    blob = json.dumps(rendered)

    # Draft lottery: odds, the slot order, and each pick's origin team.
    assert "weights_worst_first" in rendered["draft_lottery"]
    assert "ORIGINAL team's slot" in rendered["draft_lottery"]
    assert "owner T" in rendered["draft_lottery"]
    assert "pick_holdings" in rendered["standings_columns"]

    # Free-agent willingness: the per-player appeal and the term price table.
    assert "signing_appeal" in rendered["free_agents_columns"]
    assert "contract_quotes" in rendered["free_agents_columns"]
    assert "quote_multiplier" in rendered["rules"]["free_agency"]
    appeal_columns = [row.split("|")[-2] for row in rendered["free_agents"]]
    assert all(field.count(",") == 2 and "x" in field for field in appeal_columns)

    # Lineup construction: the center bonus and a C/W sub_position per forward.
    assert "bonus_per_center" in rendered["rules"]["lineup"]
    assert any("F/C" in row for row in rendered["team"]["roster"])
    assert any("F/W" in row for row in rendered["team"]["roster"])

    # Cap and dead-cap state, including the exact cost of releasing each player.
    assert "release_dead_cap" in rendered["team"]["roster_columns"]
    assert rendered["team"]["cap_room"] is not None and rendered["team"]["payroll"] is not None
    assert "dead_cap" in rendered["team"]
    assert "salary_cap" in rendered["rules"]["cap"]

    # Standings, the ledger, and the season-by-season record.
    assert len(rendered["standings"]) == league.num_teams
    assert "recent_transactions" in rendered and "history" in rendered
    assert "score_after_season" in rendered["history_columns"]

    # The rules block survives compaction section by section.
    assert set(rendered["rules"]) == {"cap", "lineup", "free_agency", "contracts", "trades", "scouting"}
    assert "seed" not in blob


def test_pick_holdings_report_only_picks_that_can_still_be_spent() -> None:
    """An exercised pick must not read as a pick the team traded away.

    A drafted-in season leaves an empty origin list behind, which renders the
    same way as a genuine departure. Publishing past seasons therefore labelled
    every team that had ever drafted as having sold its first-rounders, and
    buried the one real trade among eleven rows of noise.
    """
    league = League.new(seed=42)
    for _ in range(2):
        league.run_opponent_draft(before_user=True)
        league.run_opponent_draft(before_user=False)
        league.simulate_season()
    assert league.season == 3
    assert league.teams[4].draft_picks[1] == [], "opponents must have spent their season-1 picks"

    league._transfer_pick(league.user_team, league.teams[4], 5)
    rendered = _rendered(league, "preseason")
    holdings = {row.split("|")[0]: row.split("|")[-1] for row in rendered["standings"]}

    # The only departure on the board is the pick the user actually traded, and
    # its arrival is the only acquisition.
    assert holdings["T0"] == "-S5"
    assert holdings["T4"] == "+S5(T0)"
    assert all(holdings[f"T{team_id}"] == "own" for team_id in range(1, 12) if team_id != 4)
    assert not any("S1" in value or "S2" in value for value in holdings.values())

    # The user's own per-season counts start at the current season for the same
    # reason, and agree with the pick rows beside them.
    counts = rendered["team"]["draft_picks"]
    assert min(counts) == league.season
    assert counts[5] == 0
    assert sum(counts.values()) == len(rendered["team"]["picks"])


def test_expiring_contracts_publish_quotes_and_the_expiry_risk() -> None:
    league = League.new(seed=11)
    league.season = 2
    for player_id in league.user_team.roster:
        league.players[player_id].contract_years = 1
    rendered = _rendered(league, "preseason")
    extension_quotes = [row.rsplit("|", maxsplit=1)[-1] for row in rendered["team"]["roster"]]
    assert any("/" in quotes for quotes in extension_quotes), "no incumbent published extension_quotes"
    assert "expires to free agency" in rendered["rules"]["contracts"]
    assert "extension_quotes" in rendered["team"]["roster_columns"]


def test_a_released_player_is_rendered_as_blocked_from_re_signing() -> None:
    league = League.new(seed=11)
    released = max(league.user_team.roster, key=lambda player_id: league.players[player_id].overall)
    league.apply_actions([{"type": "release", "player_id": released}], "preseason")
    rendered = _rendered(league, "preseason")
    row = next(row for row in rendered["free_agents"] if row.startswith(f"{released}|"))
    assert row.endswith("resign_blocked")
    assert "will not re-sign with you" in rendered["rules"]["contracts"]


def test_echoed_query_results_cannot_inflate_the_view() -> None:
    """A batch of information actions is bounded, and says so when it is cut."""
    league = League.new(seed=11)
    queries = [{"type": "list_free_agents", "limit": 24} for _ in range(4)]
    results = [item.to_dict() for item in league.apply_actions(queries, "preseason")]
    rendered = compact_observation(
        league.observation("preseason", action_results=results, interaction_round=1), "compact"
    )
    assert len(rendered["action_results"]) <= 15
    assert "omitted" in rendered["action_results"][-1]
    # The first answer is served whole up to the budget, so asking one question
    # at a time keeps working.
    assert sum(1 for row in rendered["action_results"] if row.startswith("  ")) >= 12
