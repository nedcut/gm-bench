#!/usr/bin/env python3
"""Zero-spend rehearsal for the authorization-locked SOTA-v4 evidence lane."""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gm_bench.benchmark_config import PRIVATE_SEEDS_ENV  # noqa: E402
from gm_bench.contract import SOTA_V2_CONTRACT, benchmark_contract, scaffold_fingerprint  # noqa: E402
from gm_bench.official import (  # noqa: E402
    POLICIES,
    SOTA_V2_POLICY,
    SOTA_V3_POLICY,
    redact_leaderboard_payload,
    validate_leaderboard_payload,
)
from gm_bench.publication import canonical_sha256, compact_result  # noqa: E402
from scripts.analyze_publication_panel import V4_ANALYSIS_LOCK, analyze  # noqa: E402
from scripts.package_publication_release import RELEASE_SPECS, V4_RELEASE_LOCK, build_release  # noqa: E402
from scripts.sota_v3_rehearsal import (  # noqa: E402
    _exercise_site_builder,
    _run_web_build,
)
from scripts.sota_v3_rehearsal import (  # noqa: E402
    synthetic_raw_artifact as synthetic_v3_raw_artifact,
)


def synthetic_private_artifact() -> dict[str, Any]:
    """Build deterministic private-shaped v4 evidence without a provider call."""
    raw = copy.deepcopy(synthetic_v3_raw_artifact())
    contract = benchmark_contract()
    if contract.get("benchmark_version") != "sota-v4":
        raise AssertionError("SOTA-v4 rehearsal requires current code to declare benchmark_version='sota-v4'")

    raw["agent"] = "rehearsal:synthetic-v4"
    raw["candidate"]["agent"] = "rehearsal:synthetic-v4"
    run_info = raw["run_info"]
    run_info.update(
        {
            "agent": "rehearsal:synthetic-v4",
            "model": "synthetic-v4",
            "benchmark_contract": contract,
            "scaffold_fingerprint": scaffold_fingerprint("openrouter"),
        }
    )
    run_info["seed_panel"]["name"] = "private-env"
    run_info["provider_options"]["OPENROUTER_EXPECTED_ENDPOINT_NAME"] = "SyntheticProvider | synthetic-v4"
    for episode in raw["candidate"]["episodes"]:
        episode["usage"]["model"] = "synthetic-v4"
    raw["candidate"]["summary"]["usage"]["model"] = "synthetic-v4"
    return raw


def _registry() -> dict[str, Any]:
    contract = benchmark_contract()
    return {
        "schema_version": 1,
        "contract": "sota-v4",
        "contract_fingerprint": contract["contract_fingerprint"],
        "provider": "openrouter",
        "profile": "compact",
        "preset": "leaderboard",
        "repeats": 3,
        "selection_status": "frozen",
        "output_token_cap": 4096,
        "shared_fixed_options": {
            "OPENROUTER_ALLOW_FALLBACKS": "false",
            "OPENROUTER_REQUIRE_PARAMETERS": "true",
            "OPENROUTER_DATA_COLLECTION": "deny",
            "GM_BENCH_PROTOCOL_REPAIR_ATTEMPTS": "1",
        },
        "shared_absent_options": [],
        "models": [
            {
                "id": "synthetic-v4",
                "provider": "openrouter",
                "model": "synthetic-v4",
                "transport": "gateway-api",
                "upstream_provider": "SyntheticProvider",
                "upstream_provider_slug": "synthetic/fp8",
                "endpoint_tag": "synthetic/fp8",
                "endpoint_name": "SyntheticProvider | synthetic-v4",
                "fixed_options": {"OPENROUTER_REASONING_ENABLED": "false"},
                "absent_options": [],
            }
        ],
    }


def _lane(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract": "sota-v4",
        "contract_fingerprint": raw["run_info"]["benchmark_contract"]["contract_fingerprint"],
        "reference_agent": "pick-trader",
        "seed_panel": {"status": "frozen", **raw["run_info"]["seed_panel"]},
        "publication_authorized": False,
    }


def _protocol() -> dict[str, Any]:
    return {
        "contract": "sota-v4",
        "contract_fingerprint": benchmark_contract()["contract_fingerprint"],
        "status": "frozen",
        "statistical_analysis_plan": {"status": "frozen", "analysis_mode": "reference-only"},
        "publication_authorized": False,
    }


def _require_policy_failure(payload: dict[str, Any], policy_name: str) -> None:
    report = validate_leaderboard_payload(payload, policy=POLICIES[policy_name])
    if report.ok:
        raise AssertionError(f"{policy_name} unexpectedly accepted a sota-v4 artifact")


def run_rehearsal(workdir: Path, *, run_web_build: bool = True) -> dict[str, Any]:
    workdir.mkdir(parents=True, exist_ok=True)
    policy = POLICIES.get("sota-v4")
    if policy is None:
        raise AssertionError("no sota-v4 result-validation policy is registered")

    raw = synthetic_private_artifact()
    prior_private_seeds = os.environ.get(PRIVATE_SEEDS_ENV)
    os.environ[PRIVATE_SEEDS_ENV] = ",".join(str(seed) for seed in raw["seeds"])
    try:
        report = validate_leaderboard_payload(raw, policy=policy)
        if not report.ok:
            raise AssertionError(f"synthetic sota-v4 artifact failed validation: {report.errors}")
        compact = compact_result(raw)
        redacted, redaction_report = redact_leaderboard_payload(compact, policy=policy)
    finally:
        if prior_private_seeds is None:
            os.environ.pop(PRIVATE_SEEDS_ENV, None)
        else:
            os.environ[PRIVATE_SEEDS_ENV] = prior_private_seeds
    if not redaction_report.ok or redacted.get("seeds") != "<redacted>":
        raise AssertionError("synthetic private sota-v4 artifact did not produce a valid public-safe redaction")

    _require_policy_failure(compact, SOTA_V2_POLICY.name)
    _require_policy_failure(compact, SOTA_V3_POLICY.name)

    wrong_contract = copy.deepcopy(compact)
    wrong_contract["run_info"]["benchmark_contract"] = SOTA_V2_CONTRACT
    wrong_report = validate_leaderboard_payload(wrong_contract, policy=policy)
    if wrong_report.ok:
        raise AssertionError("sota-v4 policy accepted a frozen sota-v2 contract block")

    analysis = analyze(
        _registry(),
        [redacted],
        raw_payloads=[raw],
        lane=_lane(raw),
        protocol=_protocol(),
    )
    if V4_ANALYSIS_LOCK not in analysis["config_errors"] or analysis.get("publication_ready") is not False:
        raise AssertionError(f"sota-v4 analysis authorization lock did not hold: {analysis!r}")

    try:
        build_release(
            repo_root=workdir,
            run_dir=workdir,
            archive_path=workdir / "must-not-exist.zip",
            manifest_path=workdir / "must-not-exist.json",
            checksums_path=workdir / "must-not-exist.SHA256SUMS",
            contract="sota-v4",
            release_date="2099-01-01",
        )
    except ValueError as exc:
        if str(exc) != V4_RELEASE_LOCK:
            raise
    else:
        raise AssertionError("sota-v4 release packaging was not authorization-locked")

    raw_path = workdir / "synthetic-sota-v4.private.raw.json"
    redacted_path = workdir / "synthetic-sota-v4.private.redacted.json"
    raw_path.write_text(json.dumps(raw, indent=2, sort_keys=True) + "\n")
    redacted_path.write_text(json.dumps(redacted, indent=2, sort_keys=True) + "\n")

    staging = Path(tempfile.mkdtemp(prefix="site-staging-", dir=workdir))
    site_result = _exercise_site_builder(
        staging,
        redacted,
        excluded_contract="sota-v4",
        model_label="synthetic-v4",
    )
    return {
        "status": "passed",
        "mode": "synthetic-private",
        "evidence_class": "synthetic-non-evidence",
        "spend_usd": 0.0,
        "policy_selection": {"sota_v4": "accepted", "sota_v3": "rejected", "sota_v2": "rejected"},
        "analysis": {
            "status": analysis["status"],
            "publication_ready": analysis["publication_ready"],
            "authorization_lock": V4_ANALYSIS_LOCK,
        },
        "release": {"registered": "sota-v4" in RELEASE_SPECS, "authorization_lock": V4_RELEASE_LOCK},
        "site_data_build": site_result,
        "artifacts": {
            "raw": str(raw_path),
            "redacted": str(redacted_path),
            "canonical_raw_sha256": canonical_sha256(raw),
        },
        "web_build": _run_web_build(staging) if run_web_build else {"status": "skipped"},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workdir", type=Path)
    parser.add_argument("--skip-web-build", action="store_true")
    args = parser.parse_args()
    if args.workdir is None:
        with tempfile.TemporaryDirectory(prefix="gm-bench-sota-v4-rehearsal-") as temporary:
            result = run_rehearsal(Path(temporary), run_web_build=not args.skip_web_build)
    else:
        result = run_rehearsal(args.workdir, run_web_build=not args.skip_web_build)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
