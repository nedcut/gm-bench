"""The GM-Bench 2.2 contract block and fingerprint (draft, not frozen).

Not itself a contract source: it names the version and hashes the files that
are. The fingerprint covers the 2.1 fingerprint (and through it 2.0 and 1.0)
plus every 2.2 source below, byte for byte. While the version carries
``-draft`` the fingerprint moves with every edit and is pinned nowhere.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

BENCHMARK_VERSION = "gm-bench-2.2-draft"
SIMULATOR_VERSION = "sim-v4-league22"
_SOURCES = ("tools.py", "brief.py", "rules.py", "scoring.py", "runner.py", "episode.py", "mcp_server.py")
_DIR = Path(__file__).resolve().parent


def fingerprint() -> str:
    from gm_bench.v21 import contract as v21_contract

    digest = hashlib.sha256()
    digest.update(v21_contract.fingerprint().encode())
    digest.update(b"\0")
    for name in _SOURCES:
        digest.update(name.encode())
        digest.update(b"\0")
        digest.update((_DIR / name).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def contract() -> dict[str, Any]:
    from gm_bench.v21 import contract as v21_contract
    from gm_bench.v22.brief import BRIEF_VERSION
    from gm_bench.v22.episode import AgenticEpisode22
    from gm_bench.v22.tools import TOOL_SURFACE_VERSION

    parent = v21_contract.contract()
    scoring = AgenticEpisode22.scoring
    return {
        "benchmark_version": BENCHMARK_VERSION,
        "base_benchmark_version": parent["base_benchmark_version"],
        "base_contract_fingerprint": parent["base_contract_fingerprint"],
        "parent_agentic_fingerprint": parent["agentic_fingerprint"],
        "scoring_version": scoring.SCORING_VERSION,
        "scoring_scale_fingerprint": scoring.scale_fingerprint(),
        "simulator_version": SIMULATOR_VERSION,
        "tool_surface": TOOL_SURFACE_VERSION,
        "brief": BRIEF_VERSION,
        # Same key as 2.0 and 2.1 so every row names its own lane's fingerprint there.
        "agentic_fingerprint": fingerprint(),
    }
