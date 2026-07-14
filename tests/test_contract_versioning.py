"""Tests for current and historical contract policy registration."""

from __future__ import annotations

import json
from pathlib import Path

from gm_bench.contract import (
    ACTION_PROTOCOL_VERSION,
    BENCHMARK_VERSION,
    SIMULATOR_VERSION,
    benchmark_contract,
)
from gm_bench.official import (
    POLICIES,
    SOTA_V1_POLICY,
    SOTA_V2_POLICY,
    validate_leaderboard_payload,
)


def test_contract_reports_v2_version_strings() -> None:
    assert BENCHMARK_VERSION == "sota-v2"
    assert ACTION_PROTOCOL_VERSION == "actions-v2"
    assert SIMULATOR_VERSION == "sim-v2"
    contract = benchmark_contract()
    assert contract["benchmark_version"] == "sota-v2"
    assert contract["action_protocol_version"] == "actions-v2"
    assert contract["simulator_version"] == "sim-v2"
    # Scoring scale is deliberately unchanged in v2.
    assert contract["scoring_version"] == "score-v1"


def test_current_and_historical_sota_policies_are_distinct() -> None:
    assert SOTA_V2_POLICY.name == "sota-v2"
    assert POLICIES["sota-v2"] is SOTA_V2_POLICY
    assert SOTA_V1_POLICY.name == "sota-v1"
    assert POLICIES["sota-v1"] is SOTA_V1_POLICY
    assert SOTA_V1_POLICY is not SOTA_V2_POLICY
    assert SOTA_V1_POLICY.expected_contract["contract_fingerprint"] == "cf2607e59dba0c7f"


def test_archived_v1_result_remains_auditable_but_not_v2_eligible() -> None:
    path = Path("results/leaderboard/archive-v1/openrouter-gpt-5.6-luna.json")
    payload = json.loads(path.read_text())

    historical = validate_leaderboard_payload(payload, policy=SOTA_V1_POLICY)
    current = validate_leaderboard_payload(payload, policy=SOTA_V2_POLICY)

    assert historical.ok
    assert not current.ok
    assert any("benchmark_version" in error for error in current.errors)
