"""GM-Bench 2.1: league rules, score-v2, the episode engine and the contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gm_bench.agentic.contract import agentic_fingerprint
from gm_bench.agentic.episode import AgenticEpisode
from gm_bench.agents import AGENTS
from gm_bench.contract import contract_fingerprint
from gm_bench.simulator import League
from gm_bench.v21 import contract as v21_contract
from gm_bench.v21 import scoring
from gm_bench.v21.episode import AgenticEpisode21, ledger_benchmark_version
from gm_bench.v21.rules import League21, bracket_odds
from gm_bench.v21.runner import play_league, run_episode

GAMES_PER_SEASON = 33


class _Noop(AGENTS["random"]):
    name = "noop"

    def act(self, observation):  # noqa: ANN001
        return [{"type": "noop"}]


def test_earlier_contracts_are_untouched() -> None:
    assert contract_fingerprint() == "a600b7da0c302231"
    assert agentic_fingerprint() == "07de948a4f4afbae"


def test_contract_block_is_pinned() -> None:
    block = v21_contract.contract()
    assert block["benchmark_version"] == "gm-bench-2.1"
    assert block["agentic_fingerprint"] == v21_contract.fingerprint() == "282dbf382c4ee56c"
    assert block["parent_agentic_fingerprint"] == "07de948a4f4afbae"
    assert block["base_contract_fingerprint"] == "a600b7da0c302231"
    assert block["scoring_version"] == "score-v2"
    assert block["scoring_scale_fingerprint"] == scoring.PUBLISHED_SCALE_FINGERPRINT == scoring.scale_fingerprint()


def test_records_reset_each_season() -> None:
    league = play_league(AGENTS["pick-trader"](), 11)
    assert len(league.summaries) == 5
    assert all(s.wins + s.losses == GAMES_PER_SEASON for s in league.summaries)


def test_bracket_odds_form_a_distribution() -> None:
    league = play_league(AGENTS["pick-trader"](), 11, seasons=1)
    odds = league.expected_playoffs[1]
    assert len(odds) == 8
    assert sum(title for _rounds, title in odds.values()) == pytest.approx(1.0)
    assert sum(rounds for rounds, _title in odds.values()) == pytest.approx(7.0)
    teams = sorted(league.teams.values(), key=lambda team: team.id)[:2]
    two = bracket_odds(teams, {teams[0].id: 60.0, teams[1].id: 60.0})
    assert two[teams[0].id] == pytest.approx((0.5, 0.5))


def test_score_v2_terms_add_up_and_are_pinned() -> None:
    result = run_episode(AGENTS["pick-trader"](), 11)
    components = result["score_components"]
    assert components["season_wins"] == sum(s.wins for s in play_league(AGENTS["pick-trader"](), 11).summaries)
    total = sum(value for name, value in components.items() if name.endswith("_contribution"))
    assert total - components["protocol_penalty"] == pytest.approx(result["final_score"], abs=1e-3)
    # Golden 2.1 score. The deep dive's records-reset prototype under candidate E gave
    # 229.047 here; the draft fix (pick-trader leaves a pick unused on this seed) moves it.
    assert result["final_score"] == 219.093


def test_score_v2_is_for_the_user_team_only() -> None:
    league = play_league(AGENTS["value"](), 12, seasons=1)
    with pytest.raises(ValueError):
        scoring.score_components(league, league.user_team_id + 1)


def test_noop_agentic_episode_matches_the_2_1_runner() -> None:
    episode = AgenticEpisode21(23, seasons=2)
    assert isinstance(episode.league, League21)
    while not episode.done:
        episode.call_tool("end_phase", {})
    result = episode.result()
    assert result["final_score"] == run_episode(_Noop(), 23, seasons=2)["final_score"]
    assert result["scoring_version"] == "score-v2"
    assert result["benchmark_version"] == "gm-bench-2.1"
    assert set(result["score_components"]) == set(scoring.SCORE_COMPONENT_KEYS)
    # Same seed under 2.0 plays a different league (records accumulate there).
    legacy = AgenticEpisode(23, seasons=2)
    assert type(legacy.league) is League


def test_ledger_names_its_contract_and_replays(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    live = AgenticEpisode21(17, seasons=1, ledger_path=ledger)
    while not live.done:
        live.call_tool("get_status", {})
        if live.phase == "draft":
            prospects = live.call_tool("list_draft_class", {})["data"]["prospects"]
            live.call_tool("draft", {"prospect_id": prospects[0]["id"]})
        live.call_tool("end_phase", {})
    result = live.result()
    live.close()
    header = json.loads(ledger.read_text().splitlines()[0])
    assert header["benchmark_version"] == "gm-bench-2.1"
    assert ledger_benchmark_version(ledger) == "gm-bench-2.1"
    again = AgenticEpisode21.from_ledger(ledger, reopen=False)
    assert again.done and isinstance(again.league, League21)
    assert again.result()["final_score"] == result["final_score"]


def test_legacy_ledgers_read_as_2_0(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    episode = AgenticEpisode(17, seasons=1, ledger_path=ledger)
    episode.close()
    assert ledger_benchmark_version(ledger) == "gm-bench-2.0"


def _validated_run(tmp_path: Path, episode_cls, contract: dict) -> tuple[dict, dict]:
    from gm_bench.agentic.validate import validate_run

    run_dir = tmp_path / "run"
    ledger = run_dir / "seed-11" / "ledger.jsonl"
    episode = episode_cls(11, seasons=1, ledger_path=ledger)
    while not episode.done:
        episode.call_tool("get_status", {})
        episode.call_tool("end_phase", {})
    result = episode.result("opencode:test")
    episode.close()
    calls = result["agentic"]["tool_calls"]
    lines = []
    for tool, count in result["agentic"]["tool_calls_by_tool"].items():
        part = {"type": "tool", "tool": f"gm-bench_{tool}"}
        lines.extend(json.dumps({"type": "tool", "sessionID": "ses_x", "part": part}) for _ in range(count))
    ledger.with_name("opencode-events.jsonl").write_text("\n".join(lines) + "\n")
    result["harness_run"] = {
        "ledger_path": "seed-11/ledger.jsonl",
        "events_path": "seed-11/opencode-events.jsonl",
        "tool_call_agreement": {"ledger": calls, "harness": calls, "agree": True},
        "exit_code": 0,
        "timed_out": False,
    }
    result["usage"]["harness"] = {"telemetry_reported": True}
    run = {
        "agent": "opencode:test",
        "harness": {"name": "opencode"},
        "contract": contract,
        "seeds": [11],
        "episodes": [result],
    }
    (run_dir / "run.json").write_text(json.dumps(run))
    return validate_run(run_dir), result


def test_validator_replays_a_2_1_run_under_its_own_contract(tmp_path: Path) -> None:
    from gm_bench.agentic.versions import contract_block

    report, result = _validated_run(tmp_path, AgenticEpisode21, contract_block("2.1"))
    assert report["ok"], report["problems"]
    assert report["per_episode"][0]["replayed_score"] == result["final_score"]


def test_validator_rejects_a_2_1_run_claiming_the_2_0_contract(tmp_path: Path) -> None:
    from gm_bench.agentic.versions import contract_block

    report, _result = _validated_run(tmp_path, AgenticEpisode21, contract_block("2.0"))
    assert not report["ok"]
    assert any("played under gm-bench-2.1" in problem for problem in report["problems"]), report["problems"]


def test_registry_resolves_versions() -> None:
    from gm_bench.agentic.versions import contract_block, episode_class, resolve

    assert resolve(None) == resolve("2.0") == "gm-bench-2.0"
    assert resolve("2.1") == "gm-bench-2.1"
    assert episode_class("2.1") is AgenticEpisode21
    assert contract_block("2.0")["agentic_fingerprint"] == "07de948a4f4afbae"
    with pytest.raises(ValueError):
        resolve("3.0")


def test_canary_checks_run_under_2_1() -> None:
    from gm_bench.v21.runner import run_many as run_v21
    from gm_bench.validity import run_validity_canaries

    # Shape and wiring only; CI runs the full 24-seed panel (`validate-contract --contract 2.1`).
    result = run_validity_canaries(seeds=[11, 12], seasons=2, run=run_v21)
    assert {row["agent"] for row in result["baselines"]} == {"pick-trader", "strategic", "shrewd", "value"}
    assert result["checks"]


def _draft_accounting(league_cls) -> list[tuple[int, int]]:
    """Per draft: (opponent-owned slots when the user's window opens, opponent picks made)."""
    seen: list[list[int]] = []
    pick = league_cls._opponent_draft_pick
    draft = league_cls.run_opponent_draft

    def counting_pick(self, team, origin_id):  # noqa: ANN001
        seen[-1][1] += 1
        return pick(self, team, origin_id)

    def counting_draft(self, before_user):  # noqa: ANN001
        if before_user:
            self.run_draft_lottery()
            owners = [owner for _, owner in self._draft_slots()]
            seen.append([sum(1 for owner in owners if owner is not None and owner != self.user_team_id), 0])
        return draft(self, before_user)

    league_cls._opponent_draft_pick, league_cls.run_opponent_draft = counting_pick, counting_draft
    try:
        if league_cls is League21:
            play_league(AGENTS["pick-trader"](), 11)
        else:
            from gm_bench.runner import run_episode as run_v1

            run_v1(AGENTS["pick-trader"](), 11)
    finally:
        league_cls._opponent_draft_pick, league_cls.run_opponent_draft = pick, draft
    return [tuple(row) for row in seen]


def test_opponents_use_every_draft_slot_they_own() -> None:
    fixed = _draft_accounting(League21)
    assert fixed and all(owned == made for owned, made in fixed), fixed
    # 1.0 skips the opponent slots between pick-trader's used and unused picks.
    legacy = _draft_accounting(League)
    assert any(made < owned for owned, made in legacy), legacy
