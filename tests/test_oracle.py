from __future__ import annotations

from gm_bench.agents import AGENTS, PickTraderAgent
from gm_bench.contract import contract_fingerprint
from gm_bench.oracle import OracleAgent
from gm_bench.runner import run_many


def test_oracle_preserves_frozen_contract_fingerprint() -> None:
    # The current sota-v3 fingerprint moved for contract economics: dead cap,
    # term-priced free agency, incumbent extensions, and market/cap inflation.
    # Frozen sota-v2 remains pinned separately in SOTA_V2_CONTRACT.
    #
    # The fingerprint hashes raw source bytes, so docstrings and comments in a
    # _CONTRACT_SOURCES file move it too. That is deliberately cheap before a
    # panel is bought and impossible afterward.
    # Moved again for the reachable-release fix in gm_bench/agents.py (#91).
    assert contract_fingerprint() == "0a5f0434dca31ac5"
    assert "oracle" not in AGENTS


def test_oracle_is_a_distinct_protocol_legal_diagnostic() -> None:
    seeds = [11, 12, 13]
    oracle = run_many(OracleAgent(), seeds=seeds, seasons=5, workers=1)
    pick_trader = run_many(PickTraderAgent(), seeds=seeds, seasons=5, workers=1)
    assert oracle["summary"]["illegal_actions"] == 0
    # This partial oracle isolates hidden draft information; contract decisions
    # can make its alternate draft choices lose, so it is not an optimization
    # ceiling and is only required to remain behaviorally distinct.
    assert oracle["summary"]["mean_score"] != pick_trader["summary"]["mean_score"]
