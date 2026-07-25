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

from gm_bench.scoring import SCORING_VERSION, scoring_scale_fingerprint

BENCHMARK_VERSION = "sota-v3"
ACTION_PROTOCOL_VERSION = "actions-v3"
SIMULATOR_VERSION = "sim-v3"
OBSERVATION_VERSION = "observation-v2"

SOTA_V2_CONTRACT = {
    "benchmark_version": "sota-v2",
    "action_protocol_version": "actions-v2",
    "scoring_version": "score-v1",
    "scoring_scale_fingerprint": "05a60ff4f691e734",
    "simulator_version": "sim-v2",
    "observation_version": "observation-v1",
    "contract_fingerprint": "558e8f35ea1d66b9",
}

_ROOT = Path(__file__).resolve().parents[1]
# Fingerprint covers score-affecting simulator/protocol sources only.
# Pricing/telemetry (gm_bench/pricing.json, gm_bench/telemetry.py) and
# presentation helpers are intentionally excluded: cost/latency changes do not
# change whether a score is comparable under the same contract.
_CONTRACT_SOURCES = (
    "gm_bench/agent_utils.py",
    "gm_bench/agents.py",
    "gm_bench/benchmark_config.py",
    "gm_bench/generator.py",
    "gm_bench/models.py",
    "gm_bench/runner.py",
    # The compaction rules are score-affecting for the scaffold-view baseline,
    # whose whole result is a function of them; without this the baseline cache
    # would serve a pre-edit score after the model view changed.
    "gm_bench/scaffold_view.py",
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


def scaffold_fingerprint(provider: str) -> str | None:
    """Fingerprint the prompt scaffold a built-in provider row was produced with.

    The scaffold — the shared observation compaction and prompt builder plus the
    provider's adapter script and spec — is part of the measured system: two
    rows with identical contract fingerprints but different prompt text are not
    comparable. The hash is per-provider so fixing one adapter does not
    invalidate other providers' rows. Returns None for unknown providers
    (external --agent-cmd runs have no built-in scaffold to attest).
    """
    from gm_bench.providers import PROVIDERS

    spec = PROVIDERS.get(str(provider).lower())
    if spec is None:
        return None
    digest = hashlib.sha256()
    digest.update(f"{spec.name}\0{spec.model_env}\0{spec.default_profile}\0".encode())
    # scaffold_view.py holds the compaction half of the prompt builder; without
    # it a truncation-limit change would move every model's prompt text while
    # leaving every scaffold fingerprint identical.
    for relative_path in ("gm_bench/scaffold_view.py", "examples/gm_agent_common.py", f"examples/{spec.script}"):
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
        "scoring_scale_fingerprint": scoring_scale_fingerprint(),
        "simulator_version": SIMULATOR_VERSION,
        "observation_version": OBSERVATION_VERSION,
        "contract_fingerprint": contract_fingerprint(),
    }


def expected_contract() -> dict[str, Any]:
    """Return the exact contract block required for current official results."""

    return benchmark_contract()
