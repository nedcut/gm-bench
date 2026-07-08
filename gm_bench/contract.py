"""Versioned benchmark contract metadata.

These values define the public interpretation contract for a result. The
fingerprint is intentionally source-derived: it changes when the simulator,
scoring, protocol schemas, or official preset logic changes, even before a
package version is cut.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any

BENCHMARK_VERSION = "sota-v1"
ACTION_PROTOCOL_VERSION = "actions-v1"
SCORING_VERSION = "score-v1"
SIMULATOR_VERSION = "sim-v1"
OBSERVATION_VERSION = "observation-v1"

_ROOT = Path(__file__).resolve().parents[1]
_CONTRACT_SOURCES = (
    "gm_bench/agent_utils.py",
    "gm_bench/agents.py",
    "gm_bench/benchmark_config.py",
    "gm_bench/generator.py",
    "gm_bench/models.py",
    "gm_bench/runner.py",
    "gm_bench/scoring.py",
    "gm_bench/simulator.py",
    "schemas/gm_action_list.schema.json",
    "schemas/gm_actions.schema.json",
    "schemas/gm_observation.schema.json",
)


@lru_cache(maxsize=1)
def contract_fingerprint() -> str:
    digest = hashlib.sha256()
    for relative_path in _CONTRACT_SOURCES:
        digest.update(relative_path.encode())
        digest.update(b"\0")
        digest.update((_ROOT / relative_path).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def benchmark_contract() -> dict[str, Any]:
    return {
        "benchmark_version": BENCHMARK_VERSION,
        "action_protocol_version": ACTION_PROTOCOL_VERSION,
        "scoring_version": SCORING_VERSION,
        "simulator_version": SIMULATOR_VERSION,
        "observation_version": OBSERVATION_VERSION,
        "contract_fingerprint": contract_fingerprint(),
    }


def expected_contract() -> dict[str, Any]:
    """Return the exact contract block required for current official results."""

    return benchmark_contract()
