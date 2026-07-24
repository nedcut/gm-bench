from __future__ import annotations

from gm_bench.agents import AGENTS, PickTraderAgent
from gm_bench.contract import contract_fingerprint
from gm_bench.oracle import OracleAgent
from gm_bench.runner import run_many


def test_oracle_preserves_frozen_contract_fingerprint() -> None:
    # sota-v3 begins with the post-release numeric-validation and negotiation
    # window corrections; sota-v2 remains pinned in SOTA_V2_CONTRACT.
    assert contract_fingerprint() == "89c89e53c26740c7"
    assert "oracle" not in AGENTS


def test_oracle_beats_pick_trader_without_illegal_actions() -> None:
    seeds = [11, 12, 13]
    oracle = run_many(OracleAgent(), seeds=seeds, seasons=5, workers=1)
    pick_trader = run_many(PickTraderAgent(), seeds=seeds, seasons=5, workers=1)
    assert oracle["summary"]["illegal_actions"] == 0
    assert oracle["summary"]["mean_score"] > pick_trader["summary"]["mean_score"]
