from __future__ import annotations

from gm_bench.agents import AGENTS, PickTraderAgent
from gm_bench.benchmark_config import PRESETS
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


def test_oracle_beats_pick_trader_without_illegal_actions() -> None:
    """Hidden draft information must still be worth something.

    This assertion was temporarily weakened to `!=` during the miscalibrated
    intermediate commit (f65a2b0, constants 1%/0.75%/10%) and the weakening
    outlived the revert in c9771ef. `!=` between two independently computed
    floats fails only on an exact tie, so it asserted essentially nothing --
    the same unfalsifiable-assertion defect this branch exists to remove.

    Restored on the public leaderboard panel, because it holds on the final
    constants: oracle 274.789 vs pick-trader 267.875. If a future mechanic
    genuinely erodes the value of perfect draft information, this should fail
    and be discussed, not be relaxed into a tautology.
    """
    seeds = list(PRESETS["leaderboard"]["seeds"])
    oracle = run_many(OracleAgent(), seeds=seeds, seasons=5, workers=1)
    pick_trader = run_many(PickTraderAgent(), seeds=seeds, seasons=5, workers=1)
    assert oracle["summary"]["illegal_actions"] == 0
    assert oracle["summary"]["mean_score"] > pick_trader["summary"]["mean_score"]
