import json
import sys
from pathlib import Path

from gm_bench.v22.episode import AgenticEpisode22

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import diagnose_package_trades as diagnose  # noqa: E402

SEED = 201


def test_the_replicas_asset_estimate_is_the_engines() -> None:
    league = diagnose.Unfixed.new(seed=SEED)
    for player_id in league.free_agents[:40]:
        player = league.players[player_id]
        quote = league._signing_quote(player, diagnose.FILLER_YEARS)
        estimate = diagnose._asset_if_signed(player, quote)
        player.salary, player.contract_years = quote, diagnose.FILLER_YEARS
        assert abs(player.asset_value - estimate) < 1e-9


def test_the_replica_pays_before_the_fix_and_makes_no_trade_after_it() -> None:
    base = diagnose.play(SEED, "pick-trader", "unfixed")[0]
    before, stats = diagnose.play(SEED, "pick-trader", "unfixed", "replica")
    assert before > base + 50 and stats["accepted_trades"] > 10
    fixed_base = diagnose.play(SEED, "pick-trader", "fixed")[0]
    after, stats = diagnose.play(SEED, "pick-trader", "fixed", "replica")
    assert after == fixed_base and stats["accepted_trades"] == 0


def test_the_ledger_profile_counts_same_season_signings_sent(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    episode = AgenticEpisode22(SEED, ledger_path=ledger)
    league = episode.league
    free_agent = max(league.free_agents, key=lambda i: league.players[i].overall)
    quote = league._signing_quote(league.players[free_agent], 2)
    assert episode.call_tool("sign_free_agent", {"player_id": free_agent, "years": 2, "salary": quote})["ok"]
    partner = league.teams[1]
    worthless = min(partner.roster, key=lambda i: league.players[i].asset_value)
    trade = {"partner_team_id": 1, "give_player_ids": [free_agent], "receive_player_ids": [worthless]}
    # A rival gives a player it values at nothing for nothing, so this trade is accepted.
    assert league.players[worthless].asset_value == 0.0
    assert episode.call_tool("trade", trade)["ok"]
    episode.close()
    profile = diagnose.trade_profile(ledger)
    assert profile["free_agent_signings"] == 1
    assert profile["accepted_trades"] == profile["same_season_signings_sent"] == 1
    assert json.loads(ledger.read_text().splitlines()[0])["seed"] == SEED
