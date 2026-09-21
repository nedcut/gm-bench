"""The GM-Bench 2.0 contract identity.

2.0 plays the 1.0 simulator, so its identity is the 1.0 contract fingerprint
(``gm_bench.contract.contract_fingerprint``, unchanged and untouched) plus a
fingerprint of everything the agent is measured through: the tool surface,
the task brief, the episode engine, and the server's wire behaviour. A byte
change to any of those is a new 2.0 contract, exactly as the 1.0 rule says.
The 1.0 source list is deliberately not extended: adding these files there
would re-fingerprint every published 1.0 row.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any

from gm_bench.agentic.brief import BRIEF_VERSION
from gm_bench.agentic.tools import TOOL_SURFACE_VERSION
from gm_bench.contract import benchmark_contract, contract_fingerprint

AGENTIC_BENCHMARK_VERSION = "gm-bench-2.0-dev"

_PACKAGE_ROOT = Path(__file__).resolve().parent
_AGENTIC_CONTRACT_SOURCES = (
    "tools.py",
    "brief.py",
    "episode.py",
    "mcp_server.py",
)


@lru_cache(maxsize=1)
def agentic_fingerprint() -> str:
    digest = hashlib.sha256()
    digest.update(contract_fingerprint().encode())
    digest.update(b"\0")
    for name in _AGENTIC_CONTRACT_SOURCES:
        digest.update(name.encode())
        digest.update(b"\0")
        digest.update((_PACKAGE_ROOT / name).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def agentic_contract() -> dict[str, Any]:
    base = benchmark_contract()
    return {
        "benchmark_version": AGENTIC_BENCHMARK_VERSION,
        "base_benchmark_version": base["benchmark_version"],
        "base_contract_fingerprint": base["contract_fingerprint"],
        "scoring_version": base["scoring_version"],
        "scoring_scale_fingerprint": base["scoring_scale_fingerprint"],
        "simulator_version": base["simulator_version"],
        "tool_surface": TOOL_SURFACE_VERSION,
        "brief": BRIEF_VERSION,
        "agentic_fingerprint": agentic_fingerprint(),
    }
