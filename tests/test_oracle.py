from __future__ import annotations

from gm_bench.agents import AGENTS, PickTraderAgent
from gm_bench.contract import contract_fingerprint
from gm_bench.oracle import OracleAgent
from gm_bench.runner import run_many


def test_oracle_preserves_frozen_contract_fingerprint() -> None:
    # sota-v3 begins with the post-release numeric-validation and negotiation
    # window corrections, adds per-episode score components to the episode row,
    # and registers the scaffold-view baseline (whose compaction source is part
    # of the fingerprint); sota-v2 remains pinned in SOTA_V2_CONTRACT.
    #
    # The fingerprint hashes raw source bytes, so docstrings and comments in a
    # _CONTRACT_SOURCES file move it too. This pin last moved for a wording
    # correction in ScaffoldViewAgent's docstring (the reference measures view
    # truncation, not "the scaffold"). That is deliberately cheap now and
    # impossible later: once a panel is bought, no contract source may change.
    assert contract_fingerprint() == "8a4eb422d548317a"
    assert "oracle" not in AGENTS


def test_oracle_beats_pick_trader_without_illegal_actions() -> None:
    seeds = [11, 12, 13]
    oracle = run_many(OracleAgent(), seeds=seeds, seasons=5, workers=1)
    pick_trader = run_many(PickTraderAgent(), seeds=seeds, seasons=5, workers=1)
    assert oracle["summary"]["illegal_actions"] == 0
    assert oracle["summary"]["mean_score"] > pick_trader["summary"]["mean_score"]
