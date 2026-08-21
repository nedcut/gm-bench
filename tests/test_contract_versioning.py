"""Tests for current and historical contract policy registration."""

from __future__ import annotations

import json
from pathlib import Path

from gm_bench.contract import (
    _CONTRACT_SOURCES,
    ACTION_PROTOCOL_VERSION,
    BENCHMARK_VERSION,
    SIMULATOR_VERSION,
    SOTA_V2_CONTRACT,
    SOTA_V2_ORACLE_MEAN,
    SOTA_V3_CONTRACT,
    SOTA_V4_CONTRACT,
    SOTA_V5_CONTRACT,
    benchmark_contract,
)
from gm_bench.official import (
    POLICIES,
    SOTA_V1_POLICY,
    SOTA_V2_POLICY,
    SOTA_V3_POLICY,
    SOTA_V4_POLICY,
    SOTA_V5_POLICY,
    validate_leaderboard_payload,
)


def test_contract_reports_v5_version_strings() -> None:
    assert BENCHMARK_VERSION == "sota-v5"
    assert ACTION_PROTOCOL_VERSION == "actions-v3"
    assert SIMULATOR_VERSION == "sim-v3"
    contract = benchmark_contract()
    assert contract["benchmark_version"] == "sota-v5"
    assert contract["action_protocol_version"] == "actions-v3"
    assert contract["simulator_version"] == "sim-v3"
    # The P0 fixes change action/simulator semantics, not the scoring scale.
    assert contract["scoring_version"] == "score-v1"


def test_contract_fingerprint_covers_protocol_constants() -> None:
    assert "gm_bench/protocol.py" in _CONTRACT_SOURCES


def test_current_and_historical_sota_policies_are_distinct() -> None:
    assert SOTA_V2_POLICY.name == "sota-v2"
    assert POLICIES["sota-v2"] is SOTA_V2_POLICY
    assert SOTA_V3_POLICY.name == "sota-v3"
    assert POLICIES["sota-v3"] is SOTA_V3_POLICY
    assert SOTA_V4_POLICY.name == "sota-v4"
    assert POLICIES["sota-v4"] is SOTA_V4_POLICY
    assert SOTA_V5_POLICY.name == "sota-v5"
    assert POLICIES["sota-v5"] is SOTA_V5_POLICY
    assert SOTA_V1_POLICY.name == "sota-v1"
    assert POLICIES["sota-v1"] is SOTA_V1_POLICY
    assert SOTA_V1_POLICY is not SOTA_V2_POLICY
    assert SOTA_V1_POLICY.expected_contract["contract_fingerprint"] == "cf2607e59dba0c7f"
    assert SOTA_V2_POLICY.expected_contract == SOTA_V2_CONTRACT
    assert SOTA_V2_POLICY.expected_contract["contract_fingerprint"] == "558e8f35ea1d66b9"
    assert SOTA_V2_ORACLE_MEAN == 431.153
    assert SOTA_V3_POLICY.expected_contract == SOTA_V3_CONTRACT
    assert SOTA_V4_POLICY.expected_contract == SOTA_V4_CONTRACT
    assert SOTA_V5_POLICY.expected_contract == SOTA_V5_CONTRACT
    assert SOTA_V5_POLICY.expected_contract == benchmark_contract()
    assert SOTA_V4_CONTRACT["contract_fingerprint"] != SOTA_V5_CONTRACT["contract_fingerprint"]
    assert SOTA_V4_CONTRACT["benchmark_version"] != SOTA_V5_CONTRACT["benchmark_version"]
    assert SOTA_V3_POLICY.expected_scaffold_fingerprints["openrouter"] == "2462b25854c1298b"
    assert SOTA_V3_POLICY.expected_scaffold_fingerprints["openai"] == "8275269195e00191"
    assert SOTA_V4_POLICY.expected_scaffold_fingerprints["openrouter"] == "f04724717cc09caf"
    assert SOTA_V5_POLICY.expected_scaffold_fingerprints["openrouter"] == "ec8ede1bcf7774ce"


def test_archived_v1_result_remains_auditable_but_not_v2_eligible() -> None:
    path = Path("results/leaderboard/archive-v1/openrouter-gpt-5.6-luna.json")
    payload = json.loads(path.read_text())

    historical = validate_leaderboard_payload(payload, policy=SOTA_V1_POLICY)
    current = validate_leaderboard_payload(payload, policy=SOTA_V3_POLICY)

    assert historical.ok
    assert not current.ok
    assert any("benchmark_version" in error for error in current.errors)
