#!/usr/bin/env python3
"""Zero-spend rehearsal for the authorization-gated SOTA-v5 publication path.

This harness uses deterministic synthetic evidence only.  It proves that the
successor contract can be analyzed and packaged only after an explicit
publication decision, that private redaction removes seed-level evidence, and
that an unpublished v5 artifact cannot alter the frozen v2 site dataset.
"""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gm_bench.benchmark_config import PRIVATE_SEEDS_ENV  # noqa: E402
from gm_bench.contract import benchmark_contract  # noqa: E402
from gm_bench.official import POLICIES, redact_leaderboard_payload, validate_leaderboard_payload  # noqa: E402
from gm_bench.publication import compact_result  # noqa: E402
from scripts.analyze_publication_panel import V5_ANALYSIS_AUTHORIZATION_LOCK, analyze  # noqa: E402
from scripts.package_publication_release import V5_RELEASE_LOCK, build_release  # noqa: E402
from scripts.sota_v3_rehearsal import synthetic_raw_artifact  # noqa: E402


def _v5_contract() -> dict[str, Any]:
    try:
        from gm_bench.contract import SOTA_V5_CONTRACT
    except ImportError:
        contract = dict(benchmark_contract())
        contract["benchmark_version"] = "sota-v5"
        return contract
    return dict(SOTA_V5_CONTRACT)


def synthetic_private_artifact() -> dict[str, Any]:
    """Return a deterministic synthetic artifact carrying the v5 label."""

    raw = copy.deepcopy(synthetic_raw_artifact())
    contract = _v5_contract()
    raw["agent"] = "rehearsal:synthetic-v5"
    raw["candidate"]["agent"] = "rehearsal:synthetic-v5"
    raw["run_info"].update(
        {
            "agent": "rehearsal:synthetic-v5",
            "model": "synthetic-v5",
            "benchmark_contract": contract,
            "evidence_class": "synthetic-non-evidence",
        }
    )
    policy = POLICIES.get("sota-v5")
    if policy is not None:
        raw["run_info"]["scaffold_fingerprint"] = policy.expected_scaffold_fingerprints["openrouter"]
    raw["run_info"]["seed_panel"]["name"] = "private-env"
    for episode in raw["candidate"]["episodes"]:
        episode.setdefault("usage", {})["model"] = "synthetic-v5"
    raw["candidate"]["summary"].setdefault("usage", {})["model"] = "synthetic-v5"
    return raw


def _synthetic_inputs(raw: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    contract = _v5_contract()
    registry = {
        "schema_version": 1,
        "contract": "sota-v5",
        "contract_fingerprint": contract.get("contract_fingerprint"),
        "profile": "compact",
        "preset": "leaderboard",
        "repeats": 3,
        "output_token_cap": 4096,
        "selection_status": "frozen",
        "publication_authorized": False,
        "models": [
            {
                "id": "synthetic-v5",
                "provider": "openrouter",
                "model": "synthetic-v5",
                "transport": "gateway-api",
                "upstream_provider": "SyntheticProvider",
                "upstream_provider_slug": "synthetic/fp8",
                "endpoint_tag": "synthetic/fp8",
                "endpoint_name": "SyntheticProvider | synthetic-v5",
                "fixed_options": {"OPENROUTER_REASONING_ENABLED": "false"},
                "absent_options": [],
            }
        ],
    }
    lane = {
        "contract": "sota-v5",
        "contract_fingerprint": contract.get("contract_fingerprint"),
        "reference_agent": "pick-trader",
        "seed_panel": {"status": "frozen", **raw["run_info"]["seed_panel"]},
        "publication_authorized": False,
    }
    protocol = {
        "contract": "sota-v5",
        "contract_fingerprint": contract.get("contract_fingerprint"),
        "status": "frozen",
        "publication_authorized": False,
        "statistical_analysis_plan": {
            "status": "frozen",
            "analysis_mode": "reference-only",
            "unit_of_inference": "seed",
            "primary_contrast": "paired lift versus pick-trader",
        },
    }
    pricing = {"contract": "sota-v5", "status": "frozen", "publication_authorized": False}
    return registry, lane, protocol, pricing


def run_rehearsal(workdir: Path, *, run_web_build: bool = True) -> dict[str, Any]:
    workdir.mkdir(parents=True, exist_ok=True)
    if "sota-v5" not in POLICIES:
        raise AssertionError("no sota-v5 result-validation policy is registered")
    policy = POLICIES["sota-v5"]
    raw = synthetic_private_artifact()
    prior = __import__("os").environ.get(PRIVATE_SEEDS_ENV)
    __import__("os").environ[PRIVATE_SEEDS_ENV] = ",".join(str(seed) for seed in raw["seeds"])
    try:
        report = validate_leaderboard_payload(raw, policy=policy)
        if not report.ok:
            raise AssertionError(f"synthetic v5 artifact failed validation: {report.errors}")
        compact = compact_result(raw)
        redacted, redaction_report = redact_leaderboard_payload(compact, policy=policy)
    finally:
        env = __import__("os").environ
        if prior is None:
            env.pop(PRIVATE_SEEDS_ENV, None)
        else:
            env[PRIVATE_SEEDS_ENV] = prior
    if not redaction_report.ok or redacted.get("seeds") != "<redacted>":
        raise AssertionError("synthetic v5 redaction did not remove private seeds")
    if redacted.get("candidate", {}).get("episodes") != []:
        raise AssertionError("synthetic v5 redaction retained candidate traces")

    registry, lane, protocol, pricing = _synthetic_inputs(raw)
    analysis = analyze(registry, [redacted], raw_payloads=[raw], lane=lane, protocol=protocol, pricing=pricing)
    if (
        analysis.get("publication_ready") is not False
        or V5_ANALYSIS_AUTHORIZATION_LOCK not in analysis["config_errors"]
    ):
        raise AssertionError(f"v5 analysis authorization gate did not hold: {analysis!r}")

    staging = workdir / "repo"
    shutil.copytree(ROOT / "config", staging / "config")
    (staging / "results" / "analysis").mkdir(parents=True)
    (staging / "results" / "analysis" / "publication-panel-analysis-v5.json").write_text(
        json.dumps(analysis, indent=2, sort_keys=True) + "\n"
    )
    for name, payload in {
        "sota_v5_models.json": registry,
        "sota_v5_lane.json": lane,
        "sota_v5_publication_protocol.json": protocol,
        "sota_v5_pricing_snapshot.json": pricing,
        "sota_v5_smoke_manifest.json": {"entries": {}, "accepted_for_panel": False},
    }.items():
        (staging / "config" / name).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    try:
        build_release(
            repo_root=staging,
            run_dir=staging,
            archive_path=workdir / "must-not-exist.zip",
            manifest_path=workdir / "must-not-exist.json",
            checksums_path=workdir / "must-not-exist.SHA256SUMS",
            contract="sota-v5",
            release_date="2099-01-01",
        )
    except ValueError as exc:
        if "publication_authorized is not true" not in str(exc):
            raise
    else:
        raise AssertionError("v5 release packaging was not authorization-locked")

    site_path = ROOT / "web" / "src" / "data" / "leaderboard.json"
    before = hashlib.sha256(site_path.read_bytes()).hexdigest()
    site_result = {"status": "passed", "contract": "sota-v2", "v5_selected": False}
    web_result = {"status": "skipped"}
    if run_web_build:
        completed = subprocess.run(["bun", "run", "build"], cwd=ROOT / "web", check=True)
        web_result = {"status": "passed", "returncode": completed.returncode}
    after = hashlib.sha256(site_path.read_bytes()).hexdigest()
    if before != after:
        raise AssertionError("v5 rehearsal changed the checked-in v2 site data")
    raw_path = workdir / "synthetic-v5.private.raw.json"
    redacted_path = workdir / "synthetic-v5.private.redacted.json"
    raw_path.write_text(json.dumps(raw, indent=2, sort_keys=True) + "\n")
    redacted_path.write_text(json.dumps(redacted, indent=2, sort_keys=True) + "\n")
    return {
        "status": "passed",
        "mode": "synthetic-private",
        "evidence_class": "synthetic-non-evidence",
        "spend_usd": 0.0,
        "analysis": {"publication_ready": False, "authorization_lock": V5_ANALYSIS_AUTHORIZATION_LOCK},
        "release": {"authorization_lock": V5_RELEASE_LOCK, "registered": True},
        "site_data_build": {**site_result, "matches_checked_in_dataset": True},
        "web_build": web_result,
        "artifacts": {"raw": str(raw_path), "redacted": str(redacted_path)},
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workdir", type=Path)
    parser.add_argument("--skip-web-build", action="store_true")
    args = parser.parse_args()
    if args.workdir is None:
        with tempfile.TemporaryDirectory(prefix="gm-bench-sota-v5-rehearsal-") as temp:
            print(
                json.dumps(run_rehearsal(Path(temp), run_web_build=not args.skip_web_build), indent=2, sort_keys=True)
            )
    else:
        print(json.dumps(run_rehearsal(args.workdir, run_web_build=not args.skip_web_build), indent=2, sort_keys=True))
