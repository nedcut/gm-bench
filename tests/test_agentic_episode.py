"""GM-Bench 2.0 episode engine: calendar, moves, ledger replay, and failure closes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gm_bench.agentic.episode import (
    ENDED_BY_AGENT,
    ENDED_BY_GUARD,
    ENDED_BY_HARNESS_EXIT,
    AgenticEpisode,
    EpisodeComplete,
)
from gm_bench.agentic.tools import TOOLS, mcp_tool_listing, validate_arguments
from gm_bench.agents import AGENTS
from gm_bench.protocol import PHASES
from gm_bench.recorder import canonical_state_digest
from gm_bench.runner import run_episode


def _play(episode: AgenticEpisode, *, scout: bool = True) -> list[dict]:
    """A small scripted agent: read state, scout once, sign nobody, end each phase."""
    replies = []
    while not episode.done:
        status = episode.call_tool("get_status", {})
        assert status["ok"], status
        if scout and status["data"]["scouting_points_remaining"] > 0 and episode.phase == "draft":
            prospects = episode.call_tool("list_draft_class", {})["data"]["prospects"]
            replies.append(episode.call_tool("scout", {"player_id": prospects[0]["id"]}))
            replies.append(episode.call_tool("draft", {"prospect_id": prospects[0]["id"]}))
        replies.append(episode.call_tool("end_phase", {}))
    return replies


def test_tool_listing_is_valid_mcp_shape() -> None:
    listing = mcp_tool_listing()
    assert [tool["name"] for tool in listing] == [tool["name"] for tool in TOOLS]
    for tool in listing:
        assert set(tool) == {"name", "description", "inputSchema"}
        assert tool["inputSchema"]["type"] == "object"
    assert validate_arguments("scout", {"player_id": 3}) is None
    assert "missing required" in validate_arguments("scout", {})
    assert "unexpected" in validate_arguments("get_status", {"x": 1})
    assert "integer" in validate_arguments("set_lineup", {"player_ids": [1, "2"]})
    assert "unknown tool" in validate_arguments("hack", {})


def test_full_episode_walks_all_phases_and_scores(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    episode = AgenticEpisode(11, seasons=2, ledger_path=ledger)
    replies = _play(episode)
    assert episode.done
    assert replies[-1]["episode_complete"] is True
    with pytest.raises(EpisodeComplete):
        episode.call_tool("get_status", {})
    result = episode.result("test")
    assert result["decisions"] == 2 * len(PHASES)
    assert result["failed_decisions"] == 0
    assert result["agentic"]["phases_ended_by"] == {ENDED_BY_AGENT: 8}
    assert result["agentic"]["tool_calls_by_tool"]["end_phase"] == 8
    assert result["agentic"]["scout_points_used"] == 2
    assert len(result["season_summaries"]) == 2
    # The ledger recorded every call, with the header first.
    records = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert records[0]["event"] == "episode" and records[0]["seed"] == 11
    assert sum(1 for r in records if r["event"] == "tool_call") == result["agentic"]["tool_calls"]
    assert sum(1 for r in records if r["event"] == "phase_end") == 8


def test_noop_agentic_episode_matches_one_shot_noop_league() -> None:
    """Ending every phase without moves must see the same league as a 1.0 noop agent."""

    class _Noop(AGENTS["random"]):
        name = "noop"

        def act(self, observation):  # noqa: ANN001
            return [{"type": "noop"}]

    one_shot = run_episode(_Noop(), seed=23, seasons=2)
    episode = AgenticEpisode(23, seasons=2)
    while not episode.done:
        episode.call_tool("end_phase", {})
    assert episode.result()["final_score"] == one_shot.final_score
    assert canonical_state_digest(episode.league) is not None


def test_ledger_replay_rebuilds_identical_state(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    live = AgenticEpisode(17, seasons=2, ledger_path=ledger)
    # Play one and a half seasons with a real move in it, then stop mid-phase.
    for _ in range(5):
        status = live.call_tool("get_status", {})
        assert status["ok"]
        live.call_tool("end_phase", {})
    team = live.call_tool("get_team", {})["data"]
    lineup = [player["id"] for player in team["roster"]][:18]
    live.call_tool("set_lineup", {"player_ids": lineup})
    live.call_tool("write_memo", {"text": "replay me"})
    live.close()

    before = ledger.read_text()
    rebuilt = AgenticEpisode.from_ledger(ledger)
    assert ledger.read_text() == before, "replay must not write to the ledger"
    assert (rebuilt.season, rebuilt.phase) == (live.season, live.phase)
    assert rebuilt.seq == live.seq
    assert rebuilt.tool_counts == live.tool_counts
    assert rebuilt.league.agent_memo == "replay me"
    assert canonical_state_digest(rebuilt.league) == canonical_state_digest(live.league)
    # The rebuilt engine keeps appending to the same ledger and can finish.
    rebuilt.call_tool("end_phase", {})
    rebuilt.abandon()
    result = rebuilt.result()
    assert result["failed_decisions"] == 2
    assert result["agentic"]["phases_ended_by"] == {ENDED_BY_AGENT: 6, ENDED_BY_HARNESS_EXIT: 2}
    # A second replay of the now-complete ledger lands on the same score, and
    # counts the refused post-completion call the harness also saw.
    with pytest.raises(EpisodeComplete):
        rebuilt.call_tool("get_status", {})
    rebuilt.close()
    again = AgenticEpisode.from_ledger(ledger, reopen=False)
    assert again.done
    assert again.result()["final_score"] == result["final_score"]
    assert again.tool_counts == rebuilt.tool_counts
    assert again.tool_counts["get_status"] == rebuilt.tool_counts["get_status"]


def test_phase_guard_closes_phase_and_refuses_the_call(monkeypatch: pytest.MonkeyPatch) -> None:
    episode = AgenticEpisode(5, seasons=1, phase_guard_seconds=10.0)
    clock = {"now": 1000.0}
    monkeypatch.setattr("gm_bench.agentic.episode.time.monotonic", lambda: clock["now"])
    episode._phase_started_monotonic = clock["now"]
    assert episode.call_tool("get_status", {})["ok"]
    clock["now"] += 11.0
    reply = episode.call_tool("get_status", {})
    assert reply["ok"] is False and "NOT executed" in reply["message"]
    assert (episode.season, episode.phase) == (1, PHASES[1])
    assert episode.phase_log[-1]["ended_by"] == ENDED_BY_GUARD


def test_wrong_phase_and_bad_ids_are_rejected_not_crashed() -> None:
    episode = AgenticEpisode(3, seasons=1)
    assert episode.phase == "preseason"
    assert episode.call_tool("list_draft_class", {})["ok"] is False
    assert episode.call_tool("list_waiver_wire", {})["ok"] is False
    drafted = episode.call_tool("draft", {"prospect_id": 1})
    assert drafted["ok"] is False and drafted.get("penalized") is True
    assert episode.league.illegal_actions == 1
    unknown = episode.call_tool("inspect_team", {"team_id": 99})
    assert unknown["ok"] is False and "penalized" not in unknown
    bad = episode.call_tool("trade", {"partner_team_id": "x"})
    assert bad["ok"] is False and "invalid arguments" in bad["message"]
    assert episode.league.illegal_actions == 1


def test_ledger_audit_flags_moves_on_ids_the_agent_never_saw(tmp_path: Path) -> None:
    from gm_bench.agentic.audit import audit_ledger

    ledger = tmp_path / "ledger.jsonl"
    episode = AgenticEpisode(11, seasons=1, ledger_path=ledger)
    # A move on an id fetched through get_team is fine.
    roster = episode.call_tool("get_team", {})["data"]["roster"]
    lineup = [player["id"] for player in roster][:18]
    assert episode.call_tool("set_lineup", {"player_ids": lineup})["ok"]
    # A free agent the agent never listed: legal to the simulator, but the id came from nowhere.
    hidden_free_agent = next(iter(episode.league.free_agents))
    quote = episode.league._signing_quotes(episode.league.players[hidden_free_agent])
    years, salary = next(iter(quote.items()))
    signed = episode.call_tool(
        "sign_free_agent", {"player_id": hidden_free_agent, "years": int(years), "salary": salary}
    )
    assert signed["ok"], signed
    # A guessed id that the simulator rejects is only suspicious.
    assert episode.call_tool("release_player", {"player_id": 999999})["ok"] is False
    episode.close()

    report = audit_ledger(ledger)
    assert report["clean"] is False
    assert [finding["tool"] for finding in report["violations"]] == ["sign_free_agent"]
    assert report["violations"][0]["unseen_ids"] == [hidden_free_agent]
    assert [finding["tool"] for finding in report["suspicious"]] == ["release_player"]
    assert report["moves"] == 3


def test_ledger_audit_accepts_a_guessed_id_once_a_read_confirms_it(tmp_path: Path) -> None:
    """Ids are sequential; a scouted-then-drafted guess is reported, not a violation."""
    from gm_bench.agentic.audit import audit_ledger

    ledger = tmp_path / "ledger.jsonl"
    episode = AgenticEpisode(11, seasons=1, ledger_path=ledger)
    while episode.phase != "draft":
        episode.call_tool("end_phase", {})
    prospects = sorted(episode.league.prospects)
    guessed, blind = prospects[0], prospects[1]
    # Never listed the class; scouted a guessed id, then drafted it.
    assert episode.call_tool("scout", {"player_id": guessed})["ok"]
    assert episode.call_tool("draft", {"prospect_id": guessed})["ok"]
    episode.close()
    report = audit_ledger(ledger)
    assert report["clean"] is True
    assert [finding["tool"] for finding in report["guessed_reads"]] == ["scout"]
    assert report["guessed_reads"][0]["unseen_ids"] == [guessed]

    # Drafting a guessed id with no read at all is still a violation.
    ledger2 = tmp_path / "ledger2.jsonl"
    episode = AgenticEpisode(11, seasons=1, ledger_path=ledger2)
    while episode.phase != "draft":
        episode.call_tool("end_phase", {})
    assert episode.call_tool("draft", {"prospect_id": blind})["ok"]
    episode.close()
    assert audit_ledger(ledger2)["clean"] is False


def test_ledger_audit_declines_ledgers_without_exposure_records() -> None:
    from gm_bench.agentic.audit import audit_ledger

    legacy = [
        {"event": "episode", "seed": 1},
        {"event": "tool_call", "seq": 1, "tool": "release_player", "arguments": {"player_id": 4}, "ok": True},
    ]
    report = audit_ledger(legacy)
    assert report["auditable"] is False and report["violations"] == [] and report["clean"] is False
