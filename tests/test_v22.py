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
from gm_bench.contract import contract_fingerprint
from gm_bench.v21 import contract as v21_contract
from gm_bench.v21.episode import AgenticEpisode21, ledger_benchmark_version
from gm_bench.v22 import brief as brief_v22
from gm_bench.v22 import contract as v22_contract
from gm_bench.v22 import tools as tools_v22
from gm_bench.v22.episode import AgenticEpisode22
from gm_bench.v22.mcp_server import McpServer22, SocketMcpServer22


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


# -- phase 0 only -------------------------------------------------------------
# The fork starts as a no-op. These two pin that; each is deleted by the change
# that first forks the text or the rules on purpose (docs/bench_v2_2_spec.md).


def test_phase_0_the_agent_is_told_exactly_what_2_0_tells_it() -> None:
    assert tools_v22.mcp_tool_listing() == tools_v1.mcp_tool_listing()
    assert tools_v22.ACTION_TYPE_FOR_TOOL == tools_v1.ACTION_TYPE_FOR_TOOL
    assert brief_v22.task_brief(5, "Harbor Owls", 0) == brief_v1.task_brief(5, "Harbor Owls", 0)
    assert brief_v22.nudge_message(2, "draft", 5, 1, 3) == brief_v1.nudge_message(2, "draft", 5, 1, 3)
    assert brief_v22.server_instructions() == brief_v1.server_instructions()


def test_phase_0_a_2_1_game_replays_identically_under_2_2(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    live = AgenticEpisode21(23, seasons=2, ledger_path=ledger)
    _play(live)
    expected = live.result()
    live.close()
    replayed = AgenticEpisode22.from_ledger(ledger, reopen=False).result()
    for key in ("final_score", "score_components", "wins", "illegal_actions", "season_summaries", "transactions"):
        assert replayed[key] == expected[key], key
    assert replayed["agentic"]["tool_calls_by_tool"] == expected["agentic"]["tool_calls_by_tool"]
