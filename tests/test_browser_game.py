"""The human game must play and restore the actual benchmark episode."""

import json

import pytest

from gm_bench.agentic.episode import AgenticEpisode
from gm_bench.browser_game import BrowserGame, dispatch


def test_full_challenge_matches_agentic_engine_and_restores_every_window():
    game = BrowserGame(7)
    authority = AgenticEpisode(7, phase_guard_seconds=0)
    for window in range(20):
        snapshot = game.snapshot()
        assert snapshot["done"] is False
        assert snapshot["season"] == window // 4 + 1
        if window == 0:
            player = snapshot["free_agents"][0]
            actions = [
                ("scout", {"player_id": player["id"]}),
                ("sign_free_agent", {"player_id": player["id"], "years": 1, "salary": player["contract_quotes"]["1"]}),
                ("write_memo", {"text": "Develop young players"}),
                # Declines/illegal moves must replay too: they affect penalties.
                ("release_player", {"player_id": -1}),
            ]
            for tool, args in actions:
                assert game.act(tool, args) == authority.call_tool(tool, args)
        if snapshot["phase"] == "draft":
            prospect = snapshot["draft_class"][0]
            args = {"prospect_id": prospect["id"]}
            assert game.act("draft", args) == authority.call_tool("draft", args)
        else:
            assert snapshot["draft_class"] == []
        assert game.act("end_phase", {}) == authority.call_tool("end_phase", {})
        restored = BrowserGame.restore(json.loads(json.dumps(game.save())))
        assert restored.snapshot() == game.snapshot()
        assert restored.episode.phase_guard_seconds == 0
    result = authority.result()
    assert game.snapshot()["done"] is True
    assert game.snapshot()["score"]["final_score"] == pytest.approx(result["final_score"], abs=0.001)
    assert len(game.snapshot()["history"]) == 5
    with pytest.raises(ValueError, match="complete"):
        game.act("end_phase", {})


def test_public_snapshot_and_reads_do_not_change_game():
    game = BrowserGame(1)
    first = game.snapshot()
    assert first == game.snapshot()
    assert game.save()["calls"] == []
    assert len(first["teams"]) == 12
    assert first["team"]["cap_room"] == pytest.approx(first["rules"]["salary_cap"] - first["team"]["payroll"])
    for team in first["teams"]:
        for player in team["roster"]:
            assert "true_potential" not in player
            assert "hidden_value" not in player
    assert "true_potential" not in json.dumps(first)


@pytest.mark.parametrize("seed", [-1, 2**31, True, "1", None, 1.5])
def test_invalid_seed(seed):
    with pytest.raises(ValueError, match="seed"):
        BrowserGame(seed)


def test_rejected_import_preserves_active_game():
    version = "test-engine"
    active = json.loads(dispatch(json.dumps({"command": "new", "seed": 42}), version))
    bad_save = {**active["save"], "calls": [{"tool": "end_phase", "arguments": {}, "ok": False}]}
    with pytest.raises(ValueError, match="consistently"):
        dispatch(json.dumps({"command": "restore", "save": bad_save}), version)
    current = json.loads(
        dispatch(json.dumps({"command": "act", "tool": "write_memo", "arguments": {"text": "Still here"}}), version)
    )
    assert current["snapshot"]["seed"] == 42
    assert current["snapshot"]["phase"] == "preseason"
    assert len(current["save"]["calls"]) == 1


def test_invalid_or_incompatible_saves():
    game = BrowserGame()
    with pytest.raises(ValueError, match="version"):
        BrowserGame.restore(game.save(), engine_version="other")
    with pytest.raises(ValueError, match="not a GM-Bench"):
        BrowserGame.restore({"schema": "pickle"})
    with pytest.raises(ValueError, match="not available"):
        game.act("get_status", {})
    with pytest.raises(ValueError):
        BrowserGame.restore(
            {**game.save(), "calls": [{"tool": "trade", "arguments": {"partner_team_id": "bad"}, "ok": True}]}
        )
