"""The GM-Bench 2.1 contract block and fingerprint.

Not itself a contract source (like ``gm_bench/agentic/contract.py`` for 2.0):
it names the version and hashes the files that are. The 2.1 fingerprint
covers the 2.0 agentic fingerprint (and through it the 1.0 contract) plus
every 2.1 source below, byte for byte. A change to any of them is a new
benchmark version.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path
from typing import Any

BENCHMARK_VERSION = "gm-bench-2.1"
SIMULATOR_VERSION = "sim-v4-league21"
_SOURCES = ("rules.py", "scoring.py", "runner.py", "episode.py")
_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=1)
def fingerprint() -> str:
    from gm_bench.agentic.contract import agentic_fingerprint

    digest = hashlib.sha256()
    digest.update(agentic_fingerprint().encode())
    digest.update(b"\0")
    for name in _SOURCES:
        digest.update(name.encode())
        digest.update(b"\0")
        digest.update((_DIR / name).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def contract() -> dict[str, Any]:
    from gm_bench.agentic.brief import BRIEF_VERSION
    from gm_bench.agentic.contract import agentic_fingerprint
    from gm_bench.agentic.tools import TOOL_SURFACE_VERSION
    from gm_bench.contract import benchmark_contract
    from gm_bench.v21.scoring import SCORING_VERSION, scale_fingerprint

    base = benchmark_contract()
    return {
        "benchmark_version": BENCHMARK_VERSION,
        "base_benchmark_version": base["benchmark_version"],
        "base_contract_fingerprint": base["contract_fingerprint"],
        "parent_agentic_fingerprint": agentic_fingerprint(),
        "scoring_version": SCORING_VERSION,
        "scoring_scale_fingerprint": scale_fingerprint(),
        "simulator_version": SIMULATOR_VERSION,
        "tool_surface": TOOL_SURFACE_VERSION,
        "brief": BRIEF_VERSION,
        # Same key as 2.0 so every row names its own lane's fingerprint there.
        "agentic_fingerprint": fingerprint(),
    }
