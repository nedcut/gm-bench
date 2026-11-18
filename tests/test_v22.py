"""GM-Bench 2.2 (draft): the forked tool surface, brief, engine and server."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from gm_bench.agentic import brief as brief_v1
from gm_bench.agentic import tools as tools_v1
from gm_bench.agentic.contract import agentic_fingerprint
from gm_bench.agentic.mcp_server import McpServer, SocketMcpServer
from gm_bench.agentic.versions import (
    brief_module,
    contract_block,
    episode_class,
    replay_ledger,
    resolve,
    socket_server_class,
)
from gm_bench.agents import AGENTS
from gm_bench.contract import contract_fingerprint
from gm_bench.models import pick_value
from gm_bench.v21 import contract as v21_contract
from gm_bench.v21 import scoring as score_v2
from gm_bench.v21.episode import ledger_benchmark_version
from gm_bench.v22 import brief as brief_v22
from gm_bench.v22 import contract as v22_contract
from gm_bench.v22 import rules as rules_v22
from gm_bench.v22 import scoring as score_v3
from gm_bench.v22 import tools as tools_v22
from gm_bench.v22.episode import AgenticEpisode22
from gm_bench.v22.mcp_server import McpServer22, SocketMcpServer22, _LockedMcpServer22
from gm_bench.v22.rules import League22
from gm_bench.v22.runner import play_league, run_episode
from gm_bench.v22.validity import ExtendEverythingAgent, RunDownAgent, run_validity_canaries


class _Noop(AGENTS["random"]):
    name = "noop"

    def act(self, observation):  # noqa: ANN001
        return [{"type": "noop"}]


def _play(episode) -> None:
    """A short scripted game that reads, moves, draws a rejection and drafts."""
    while not episode.done:
        episode.call_tool("get_status", {})
        team = episode.call_tool("get_team", {})["data"]
        episode.call_tool("set_lineup", {"player_ids": [p["id"] for p in team["roster"]][:18]})
        episode.call_tool("trade", {"partner_id": 1})
        if episode.phase == "draft":
            prospects = episode.call_tool("list_draft_class", {})["data"]["prospects"]
            if prospects:
                episode.call_tool("draft", {"prospect_id": prospects[0]["id"]})
        episode.call_tool("end_phase", {})


def _rpc(server_class, episode, method: str, params: dict | None = None) -> dict:
    out = io.StringIO()
    server = server_class(episode, stdin=io.StringIO(), stdout=out, stderr=io.StringIO())
    server._handle({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})
    return json.loads(out.getvalue())["result"]


def test_earlier_contracts_are_untouched() -> None:
    assert contract_fingerprint() == "a600b7da0c302231"
    assert agentic_fingerprint() == "07de948a4f4afbae"
    assert v21_contract.fingerprint() == "282dbf382c4ee56c"


def test_the_draft_is_registered_and_cannot_be_published() -> None:
    from gm_bench.agentic.publication import LANE_CONFIGS

    assert resolve("2.2-draft") == v22_contract.BENCHMARK_VERSION == "gm-bench-2.2-draft"
    assert episode_class("2.2-draft") is AgenticEpisode22
    assert socket_server_class("2.2-draft") is SocketMcpServer22
    assert brief_module("2.2-draft") is brief_v22
    # The frozen contracts keep the 2.0 surface.
    assert socket_server_class("2.1") is socket_server_class("2.0") is SocketMcpServer
    assert brief_module("2.1") is brief_module(None) is brief_v1
    block = contract_block("2.2-draft")
    assert block["parent_agentic_fingerprint"] == "282dbf382c4ee56c"
    assert block["agentic_fingerprint"] == v22_contract.fingerprint()
    # ``agentic-redact`` refuses a contract with no lane, so no draft row can be published.
    assert v22_contract.BENCHMARK_VERSION not in LANE_CONFIGS


def test_the_2_2_server_serves_the_2_2_surface(monkeypatch: pytest.MonkeyPatch) -> None:
    episode = AgenticEpisode22(17, seasons=1)
    marked = [{**tools_v22.TOOLS[0], "description": "2.2 text"}, *tools_v22.TOOLS[1:]]
    monkeypatch.setattr(tools_v22, "TOOLS", marked)
    monkeypatch.setattr("gm_bench.v22.mcp_server.server_instructions", lambda: "2.2 instructions")
    listing = _rpc(McpServer22, episode, "tools/list")["tools"]
    assert listing[0]["description"] == "2.2 text"
    assert _rpc(McpServer22, episode, "initialize")["instructions"] == "2.2 instructions"
    # The frozen server still serves the frozen text.
    assert _rpc(McpServer, episode, "tools/list")["tools"] == tools_v1.mcp_tool_listing()


def test_ledger_names_its_contract_and_replays(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    live = AgenticEpisode22(17, seasons=1, ledger_path=ledger)
    _play(live)
    result = live.result()
    live.close()
    assert ledger_benchmark_version(ledger) == "gm-bench-2.2-draft"
    assert result["benchmark_version"] == "gm-bench-2.2-draft"
    again = replay_ledger(ledger, reopen=False)
    assert type(again) is AgenticEpisode22 and again.done
    assert again.result()["final_score"] == result["final_score"]


# -- rules --------------------------------------------------------------------


def test_the_published_strength_formula_is_the_engines() -> None:
    league = play_league(AGENTS["pick-trader"](), 17, seasons=1)
    published = league.observation("preseason")["rules"]["team_strength"]
    weights = [w["weight"] for w in published["lineup_slot_weights"] for _ in range(6)]
    centers = league.observation("preseason")["rules"]["lineup_center_bonus"]
    for team in league.teams.values():
        dressed = sorted(league._effective_lineup(team, available_only=True), key=lambda p: -p.overall)
        strength = sum(p.overall * w for p, w in zip(dressed, weights)) / sum(weights[: len(dressed)])
        goalies = sum(1 for p in dressed if p.position == "G")
        strength += min(goalies, published["goalie_bonus_max_goalies"]) * published["goalie_bonus_per_dressed_goalie"]
        dressed_centers = sum(1 for p in dressed if p.sub_position == "C")
        strength += min(dressed_centers, centers["target"]) * centers["bonus_per_center"]
        strength -= max(0.0, league._payroll(team) - league.cap) * published["over_cap_penalty_per_unit"]
        assert strength == pytest.approx(league._team_strength(team, apply_injury_noise=False))
    assert published["season_injury_overall_loss"] == list(rules_v22.SEASON_INJURY_OVERALL_LOSS)


def test_picks_say_whether_they_can_be_traded_now() -> None:
    observation = League22.new(seed=17).observation("preseason")
    assert observation["rules"]["pick_trading"]["tradable_seasons"] == [2, 3, 4]
    assert {pick["season"]: pick["tradable_now"] for pick in observation["team"]["picks"]}[1] is False
    assert all(card["injured_games"] == 0 for card in observation["team"]["roster"])
    advice = ("often misses", "not a free option", "always succeeds")
    assert not any(phrase in json.dumps(observation["rules"]) for phrase in advice)
    assert all(pick["tradable_now"] for pick in observation["team"]["picks"] if pick["season"] in (2, 3, 4))


def test_inspect_player_finds_a_prospect() -> None:
    league = League22.new(seed=17)
    prospect_id = next(iter(league.prospects))
    result = league.apply_actions([{"type": "inspect_player", "player_id": prospect_id}], "preseason")[-1]
    assert result.accepted and result.data["player"]["draft_prospect"] is True
    assert league.failed_queries == 0


def test_a_refused_signing_names_where_the_player_is_and_is_still_penalized() -> None:
    league = League22.new(seed=17)
    signed = league.teams[3].roster[0]
    result = league.apply_actions(
        [{"type": "sign_free_agent", "player_id": signed, "years": 1, "salary": 1.0}], "preseason"
    )[-1]
    assert not result.accepted and "team id 3" in result.message
    assert league.illegal_actions == 1
    league.waiver_wire.append(10**9)
    result = league.apply_actions(
        [{"type": "sign_free_agent", "player_id": 10**9, "years": 1, "salary": 1.0}], "midseason"
    )[-1]
    assert "claim_waiver" in result.message and league.illegal_actions == 2


def test_deadline_offers_are_withdrawn_when_the_deadline_closes() -> None:
    episode = AgenticEpisode22(17, seasons=1)
    while episode.phase != "trade_deadline":
        episode.call_tool("end_phase", {})
    assert episode.league.current_offers  # seed 17 draws offers at the first deadline
    episode.call_tool("end_phase", {})
    assert episode.phase == "draft" and episode.league.current_offers == {}
    legal = episode.call_tool("get_status", {})["data"]["legal_tools"]
    assert "accept_trade_offer" not in legal


# -- score ----------------------------------------------------------------------


def test_score_v3_is_score_v2_plus_the_next_drafts_picks() -> None:
    league = play_league(AGENTS["pick-trader"](), 17, seasons=2)
    v2 = score_v2.score_components(league, 0)
    v3 = score_v3.score_components(league, 0)
    held = len(league.user_team.draft_picks[league.season])
    extra = held * pick_value(league.season, league.season)
    assert held >= 1
    assert v3["future_pick_assets"] == pytest.approx(v2["future_pick_assets"] + extra)
    assert score_v3.score_team(league, 0) == pytest.approx(
        score_v2.score_team(league, 0) + extra * score_v3.SCALE.future_pick_asset
    )
    # While a season is open its draft has been held: nothing is added.
    assert score_v3.score_components(league, 0, open_season_wins=20) == score_v2.score_components(
        league, 0, open_season_wins=20
    )


def test_noop_agentic_episode_matches_the_2_2_runner() -> None:
    episode = AgenticEpisode22(23, seasons=2)
    assert type(episode.league) is League22
    while not episode.done:
        episode.call_tool("end_phase", {})
    result = episode.result()
    assert result["final_score"] == run_episode(_Noop(), 23, seasons=2)["final_score"]
    assert result["scoring_version"] == "score-v3"
    assert set(result["score_components"]) == set(score_v3.SCORE_COMPONENT_KEYS)


# -- engine -----------------------------------------------------------------------


def test_the_draft_class_is_listed_in_every_phase() -> None:
    episode = AgenticEpisode22(17, seasons=1)
    assert episode.phase == "preseason"
    prospects = episode.call_tool("list_draft_class", {})["data"]["prospects"]
    assert prospects and "list_draft_class" in episode.call_tool("get_status", {})["data"]["legal_tools"]
    assert episode.call_tool("scout", {"player_id": prospects[0]["id"]})["ok"]


def closed_calls(episode) -> list[tuple[str, bool]]:  # noqa: ANN001
    closed = episode.call_tool("end_phase", {})["closed"]
    assert closed["penalized_calls"] == sum(1 for call in closed["rejected_calls"] if call["penalized"])
    return [(call["tool"], call["penalized"]) for call in closed["rejected_calls"]]


def test_end_phase_reports_the_phases_rejected_calls_and_the_calendar() -> None:
    episode = AgenticEpisode22(17, seasons=1)
    episode.call_tool("trade", {"partner_team_id": 1})  # no assets: an illegal move
    # A schema failure and a read refused in this phase are listed too, unpenalized.
    episode.call_tool("extend_contract", {"player_id": 1, "years": 1, "salary": 1.0})
    episode.call_tool("list_waiver_wire", {})
    episode.call_tool("end_phase", {"now": True})  # a close refused by the schema is listed too
    assert closed_calls(episode) == [
        ("trade", True),
        ("extend_contract", False),
        ("list_waiver_wire", False),
        ("end_phase", False),
    ]
    assert episode.call_tool("end_phase", {})["closed"]["rejected_calls"] == []
    opened = episode.call_tool("end_phase", {})
    assert opened["now"]["phase"] == "draft" and "playoffs are played when you end this phase" in opened["message"]


def test_a_non_object_call_is_logged_as_not_executed_so_replay_matches(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    live = AgenticEpisode22(17, seasons=1, ledger_path=ledger)
    assert not live.call_tool("end_phase", ["not", "an", "object"])["ok"]
    assert live.phase == "preseason"
    live.call_tool("trade", {"partner_team_id": 1})
    live.call_tool("no_such_tool", [])
    # A reopened ledger reports the same refusals, the skipped calls included.
    reopened = replay_ledger(ledger, reopen=False)
    assert reopened._phase_rejections == live._phase_rejections and len(live._phase_rejections) == 3
    while not live.done:
        live.call_tool("end_phase", {})
    result = live.result()
    live.close()
    calls = [json.loads(line) for line in ledger.read_text().splitlines() if '"tool_call"' in line]
    assert calls[0]["executed"] is False
    again = replay_ledger(ledger, reopen=False)
    assert again.done and again.result()["final_score"] == result["final_score"]


def test_a_guard_notice_is_not_a_refusal_after_a_reopen(tmp_path: Path) -> None:
    import time

    ledger = tmp_path / "ledger.jsonl"
    live = AgenticEpisode22(17, seasons=1, ledger_path=ledger, phase_guard_seconds=0.01)
    time.sleep(0.05)
    assert "phase guard" in live.call_tool("get_status", {})["message"]  # the guard closes preseason
    live.phase_guard_seconds = 0.0
    live.call_tool("phase guard", [])  # refused by the tool layer, whatever it is called
    reopened = replay_ledger(ledger, reopen=False)
    assert reopened._phase_rejections == live._phase_rejections
    assert [call["tool"] for call in live._phase_rejections] == ["phase guard"]
    live.close()


def test_schema_ranges_are_the_simulators() -> None:
    assert tools_v22.validate_arguments("extend_contract", {"player_id": 1, "years": 1, "salary": 1.0})
    assert tools_v22.validate_arguments("sign_free_agent", {"player_id": 1, "years": 6, "salary": 1.0})
    assert tools_v22.validate_arguments("sign_free_agent", {"player_id": 1, "years": 1, "salary": 1.0}) is None


def test_a_call_queued_when_stop_began_is_refused() -> None:
    import threading

    episode = AgenticEpisode22(17, seasons=1)
    stopping = threading.Event()
    out = io.StringIO()
    server = _LockedMcpServer22(
        episode, threading.Lock(), stopping, stdin=io.StringIO(), stdout=out, stderr=io.StringIO()
    )
    stopping.set()
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "end_phase", "arguments": {}}}
    server._handle(request)
    assert "not executed" in json.loads(out.getvalue())["error"]["message"]
    assert episode.phase == "preseason" and episode.seq == 0


# -- text -------------------------------------------------------------------------


def test_the_brief_states_what_2_1_models_misread() -> None:
    brief = brief_v22.task_brief(5, "Harbor Owls", 0)
    assert "capped credit" not in brief and "roster depth stops counting at 24 players" in brief
    assert "counted after\n     the final season's contracts have expired" in brief
    assert "when the draft phase closes" in brief
    assert "they do not change the score" in brief
    assert "after 2 declines" in brief
    assert tools_v22.TOOL_SURFACE_VERSION != tools_v1.TOOL_SURFACE_VERSION
    assert brief_v22.BRIEF_VERSION != brief_v1.BRIEF_VERSION
    # Tool names and the action mapping are unchanged; only text and ranges moved.
    assert [t["name"] for t in tools_v22.TOOLS] == [t["name"] for t in tools_v1.TOOLS]
    assert tools_v22.ACTION_TYPE_FOR_TOOL == tools_v1.ACTION_TYPE_FOR_TOOL


# -- contract checks -----------------------------------------------------------------


def test_end_of_run_canaries_do_what_they_say() -> None:
    def final_season_extensions(agent) -> int:  # noqa: ANN001
        league = play_league(agent, 11, seasons=2)
        return sum(
            1
            for t in league.transactions
            if t.team_id == 0 and t.accepted and t.season == 2 and t.action.get("type") == "extend_contract"
        )

    base = final_season_extensions(AGENTS["pick-trader"]())
    assert final_season_extensions(RunDownAgent(2)) == 0
    assert final_season_extensions(ExtendEverythingAgent(2)) > base


def test_canary_checks_run_under_2_2() -> None:
    # Shape and wiring only; the full 24-seed panel is `validate-contract --contract 2.2-draft`.
    result = run_validity_canaries(seeds=[11, 12], seasons=2)
    assert {row["agent"] for row in result["canaries"]} >= {"extend-everything", "run-down"}
    assert [check["loser"] for check in result["checks"] if check["name"] == "end_of_run_gain"] == [
        "extend-everything",
        "run-down",
    ]
