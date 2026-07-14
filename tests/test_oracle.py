from __future__ import annotations

from gm_bench.agents import AGENTS, PickTraderAgent
from gm_bench.contract import contract_fingerprint
from gm_bench.oracle import OracleAgent
from gm_bench.runner import run_many


def test_oracle_preserves_frozen_contract_fingerprint() -> None:
    assert contract_fingerprint() == "75818ce1be557ef3"
    assert "oracle" not in AGENTS


def test_oracle_is_a_distinct_protocol_legal_diagnostic() -> None:
    seeds = [11, 12, 13]
    oracle = run_many(OracleAgent(), seeds=seeds, seasons=5, workers=1)
    pick_trader = run_many(PickTraderAgent(), seeds=seeds, seasons=5, workers=1)
    assert oracle["summary"]["illegal_actions"] == 0
    # The partial hidden-information policy is not an optimization ceiling;
    # its value is isolating whether hidden draft information changes behavior.
    assert oracle["summary"]["mean_score"] != pick_trader["summary"]["mean_score"]
