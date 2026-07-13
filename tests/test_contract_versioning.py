"""Tests for the v2 contract version strings and policy aliasing."""

from __future__ import annotations

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


def test_sota_v2_policy_registered_and_v1_label_aliases_to_it() -> None:
    assert SOTA_V2_POLICY.name == "sota-v2"
    assert POLICIES["sota-v2"] is SOTA_V2_POLICY
    # The old label resolves to the current strict policy so `--policy sota-v1`
    # fails on a contract mismatch, not an unknown-policy error.
    assert POLICIES["sota-v1"] is SOTA_V2_POLICY
    # The retained module symbol is an alias for the same object.
    assert SOTA_V1_POLICY is SOTA_V2_POLICY
