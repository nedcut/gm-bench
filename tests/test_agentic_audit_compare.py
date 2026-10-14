from __future__ import annotations

import json
from pathlib import Path

import pytest

from gm_bench.agentic.audit import PRE_SIGNING_POLICY, audit_ledger
from gm_bench.agentic.audit_compare import compare_archive


def call(tool: str, arguments: dict, **kwargs: object) -> dict:
    return {"event": "tool_call", "tool": tool, "arguments": arguments, "ok": True, "ids_exposed": [], **kwargs}


@pytest.mark.parametrize("player", [302, 21, 1050020])
def test_blind_signing_is_general_and_retained(player: int) -> None:
    # High salary, later season, no release: opening FA membership is irrelevant.
    records = [call("sign_free_agent", {"player_id": player, "salary": 12, "years": 5}, season=5)]
    assert audit_ledger(records)["clean"]
    assert len(audit_ledger(records)["guessed_signings"]) == 1
    assert len(audit_ledger(records, policy=PRE_SIGNING_POLICY)["violations"]) == 1
    # Acceptance alone does not expose the player; a later unseen extension still fails.
    assert not audit_ledger(records + [call("extend_contract", {"player_id": player})])["clean"]


def test_signing_boundaries() -> None:
    rejected = audit_ledger([call("sign_free_agent", {"player_id": 302}, ok=False)])
    assert len(rejected["suspicious"]) == 1 and not rejected["guessed_signings"]
    multi = audit_ledger([call("sign_free_agent", {"player_id": 302, "team_id": 99})])
    assert len(multi["violations"]) == 1 and not multi["guessed_signings"]
    skipped = audit_ledger([call("sign_free_agent", {"player_id": 302}, executed=False)])
    assert not skipped["guessed_signings"]
    exposed = [call("list_free_agents", {}, ids_exposed=[302]), call("sign_free_agent", {"player_id": 302})]
    assert not audit_ledger(exposed)["guessed_signings"]
    with pytest.raises(ValueError, match="unknown audit policy"):
        audit_ledger([], policy="typo")


def test_comparison_includes_orphans_missing_and_legacy_without_private_data(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(json.dumps(call("sign_free_agent", {"player_id": 302}, season=5)) + "\n")
    (tmp_path / "run.json").write_text(
        json.dumps(
            {
                "seeds": ["PRIVATE"],
                "episodes": [
                    {"harness_run": {"ledger_path": "ledger.jsonl"}},
                    {"harness_run": {"ledger_path": "missing"}},
                ],
            }
        )
    )
    other = tmp_path / "excluded"
    other.mkdir()
    (other / "ledger.jsonl").write_text(json.dumps({"event": "tool_call", "tool": "draft"}) + "\n")
    report = compare_archive(tmp_path)
    first, missing = report["runs"][0]["episodes"]
    assert first["old"]["status"] == "fail" and first["new"]["status"] == "pass"
    assert first["old"]["violations"] == 1 and first["new"]["guessed_signings"] == 1
    assert missing["new"]["status"] == "unavailable"
    assert report["orphan_ledgers"][0]["old"]["status"] == "unauditable"
    assert "PRIVATE" not in json.dumps(report)
    assert "unseen_ids" not in json.dumps(report)


def test_full_comparison_preserves_original_failure_for_a_retained_signing(tmp_path: Path) -> None:
    from gm_bench.agentic.contract import agentic_contract
    from gm_bench.agentic.episode import AgenticEpisode

    ledger = tmp_path / "ledger.jsonl"
    episode = AgenticEpisode(11, seasons=1, ledger_path=ledger)
    player = next(iter(episode.league.free_agents))
    years, salary = max(
        episode.league._signing_quotes(episode.league.players[player]).items(), key=lambda item: int(item[0])
    )
    assert episode.call_tool("sign_free_agent", {"player_id": player, "years": int(years), "salary": salary})["ok"]
    while not episode.done:
        episode.call_tool("end_phase", {})
    result = episode.result()
    result["harness_run"] = {"ledger_path": "ledger.jsonl"}
    episode.close()
    assert player in episode.league.user_team.roster
    (tmp_path / "run.json").write_text(
        json.dumps({"contract": agentic_contract(), "seeds": [11], "episodes": [result]})
    )
    report = compare_archive(tmp_path, validate=True)["runs"][0]
    assert report["episodes"][0]["old"]["status"] == "fail"
    assert report["episodes"][0]["new"]["status"] == "pass"
    # Other validation problems (no harness event stream) remain problems;
    # the signing alone moves from a fatal audit finding to an explicit warning.
    old, new = report["validation"]["old"], report["validation"]["new"]
    assert old["problems"] == new["problems"] + 1
    assert new["warnings"] == old["warnings"] + 1
