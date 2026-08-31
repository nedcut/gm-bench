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

# SOTA-v4 is a frozen historical lane.  SOTA-v5 is the current contract; the
# mechanics are intentionally unchanged, so both contracts share the same
# source-derived fingerprint.  The benchmark version remains part of the
# contract identity and must never be inferred from the fingerprint alone.
BENCHMARK_VERSION = "sota-v5"
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
SOTA_V3_CONTRACT = {
    "benchmark_version": "sota-v3",
    "action_protocol_version": "actions-v3",
    "scoring_version": "score-v1",
    "scoring_scale_fingerprint": "05a60ff4f691e734",
    "simulator_version": "sim-v3",
    "observation_version": "observation-v2",
    "contract_fingerprint": "247e12fe5a7d4f5b",
}
SOTA_V4_CONTRACT = {
    "benchmark_version": "sota-v4",
    "action_protocol_version": "actions-v3",
    "scoring_version": "score-v1",
    "scoring_scale_fingerprint": "05a60ff4f691e734",
    "simulator_version": "sim-v3",
    "observation_version": "observation-v2",
    "contract_fingerprint": "247e12fe5a7d4f5b",
}
SOTA_V5_CONTRACT = {
    "benchmark_version": "sota-v5",
    "action_protocol_version": "actions-v3",
    "scoring_version": "score-v1",
    "scoring_scale_fingerprint": "05a60ff4f691e734",
    "simulator_version": "sim-v3",
    "observation_version": "observation-v2",
    # sota-v5 is the live (not yet frozen) lane; its fingerprint tracks the
    # in-flight v6 mechanic work. Moved from 247e12fe5a7d4f5b when the draft
    # lottery replaced deterministic draft order and traded picks gained
    # original-team identity; moved from d30fe7eddc093d97 when free-agent
    # willingness began pricing the signing team's record and lineup role;
    # moved from b7f53b7d638de7a3 when forwards gained a published
    # center-or-wing sub_position and lineups earned a bonus for dressing
    # enough natural centers; moved from d9722e44b0cf991c when an
    # extension-eligible incumbent left unresigned began expiring into an
    # immediate rival scramble for the best expiring players leaguewide;
    # moved from 20e42898d8069386 when the inert morale, market, and
    # patience fields (never read by any mechanic) were removed from the
    # model, generator, and observation; moved from 2501fcfbcb5133e9 when a
    # team lost the right to re-sign a player it released until the next
    # season, closing the release-then-re-sign dodge around extensions; moved
    # from ad97fb57f513a751 when that release block became a set of
    # (team, player) pairs, so a later drop by another team no longer erases
    # an earlier team's block, and waiver claims began honouring the block the
    # same way free-agent signings do; moved from b97c8a1d61b321cc when the
    # v6 compact observation render replaced the verbose JSON view with
    # pipe-delimited tables inside the ~6,500-token budget, tightened the
    # candidate lists a model reads, and gave the transaction ledger its
    # roster-changing two-season selection rule; moved from 989775a0ca5c7ad1
    # when the runner adopted the v6 execution rules: one paid model call per
    # decision phase, no paid retry, and deterministic local repair of
    # malformed output with a structured no-op when intent is ambiguous; moved
    # from 3167d95f860770c5 when the rendered pick_holdings column and
    # team.draft_picks stopped publishing seasons already drafted in, which had
    # made every team that had ever used a pick read as having traded it away;
    # moved from bcfe0ce8c23ddc85 when the roster column header stopped
    # labelling the four extension quotes as a five-term 1y..5y table.
    "contract_fingerprint": "5db845650f34d4db",
}
# Hidden-info diagnostic mean on the frozen public panel (seeds 11-18 × 5).
# Pinned with the release identity so the site headroom strip cannot drift when
# the live engine moves under sota-v3.
SOTA_V2_ORACLE_MEAN = 431.153

_ROOT = Path(__file__).resolve().parents[1]
_PACKAGE_ROOT = Path(__file__).resolve().parent
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
    # Decision phases, interaction limits, partial-season length, injury
    # duration, and the canonical action set all affect played-out episodes.
    "gm_bench/protocol.py",
    "gm_bench/runner.py",
    # Local repair decides which malformed model outputs still reach the
    # simulator and which become structured no-ops, so two rows produced under
    # different repair rules played different episodes.
    "gm_bench/repair.py",
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


def _repository_checkout_root() -> Path | None:
    """Return the source root only when this package belongs to the repo."""

    git_marker = _ROOT / ".git"
    project_marker = _ROOT / "pyproject.toml"
    package_dir = _ROOT / "gm_bench"
    if not git_marker.exists() or not project_marker.is_file() or not package_dir.is_dir():
        return None
    try:
        if not package_dir.samefile(_PACKAGE_ROOT):
            return None
    except OSError:
        return None
    return _ROOT


def _source_path(relative_path: str) -> Path:
    """Resolve a contract/scaffold source in a checkout or installed wheel."""

    group, separator, remainder = relative_path.partition("/")
    if separator and group == "gm_bench":
        return _PACKAGE_ROOT / remainder
    if separator and group in {"examples", "schemas"}:
        checkout_root = _repository_checkout_root()
        if checkout_root is not None:
            checkout_path = checkout_root / relative_path
            if checkout_path.is_file():
                return checkout_path
        packaged_path = _PACKAGE_ROOT / "_resources" / group / remainder
        return packaged_path
    return _ROOT / relative_path


@lru_cache(maxsize=1)
def contract_fingerprint() -> str:
    digest = hashlib.sha256()
    for relative_path in _CONTRACT_SOURCES:
        digest.update(relative_path.encode())
        digest.update(b"\0")
        digest.update(_source_path(relative_path).read_bytes())
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
    for relative_path in (
        "gm_bench/providers.py",
        "gm_bench/scaffold_view.py",
        "examples/gm_agent_common.py",
        f"examples/{spec.script}",
    ):
        digest.update(relative_path.encode())
        digest.update(b"\0")
        digest.update(_source_path(relative_path).read_bytes())
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
