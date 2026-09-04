#!/usr/bin/env python3
"""Zero-spend rehearsal for the authorization-gated SOTA-v5 publication path.

This harness uses deterministic synthetic evidence only.  It proves that the
successor contract can be analyzed and packaged only after an explicit
publication decision, that private redaction removes seed-level evidence, and
that an unpublished v5 artifact cannot alter the frozen v2 site dataset.

It also proves the accounted-for rule end to end: with the four frozen records
authorized only in memory (and materialized only inside a temporary staging
tree), a synthetic sixteen-row family with eleven eligible rows and the five
committed register exclusions analyzes as publication_ready, packages into a
release archive, and verifies. The repository's own records are never written;
the proof holds whether their publication_authorized flags are false (before
the release decision) or true (after it), because it authorizes only copies.
"""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gm_bench.benchmark_config import PRESETS, PRIVATE_SEEDS_ENV, seed_panel_metadata  # noqa: E402
from gm_bench.contract import benchmark_contract  # noqa: E402
from gm_bench.official import POLICIES, redact_leaderboard_payload, validate_leaderboard_payload  # noqa: E402
from gm_bench.publication import compact_result  # noqa: E402
from gm_bench.runner import _paired_analysis, _precise_mean_score, summarize_episodes  # noqa: E402
from scripts.analyze_publication_panel import V5_ANALYSIS_AUTHORIZATION_LOCK, _registry_specs, analyze  # noqa: E402
from scripts.package_publication_release import V5_RELEASE_LOCK, build_release, verify_archive  # noqa: E402
from scripts.sota_v3_rehearsal import _score_components, synthetic_raw_artifact  # noqa: E402

V5_RECORD_FILES = {
    "lane": "config/sota_v5_lane.json",
    "registry": "config/sota_v5_models.json",
    "protocol": "config/sota_v5_publication_protocol.json",
    "pricing": "config/sota_v5_pricing_snapshot.json",
}
V5_REGISTER_FILE = "config/sota_v5_panel_exclusions.json"
V5_ROUTE_EVIDENCE_FILE = "results/route_evidence/sota-v5-route-acceptance-evidence.json"
INELIGIBLE_MODEL_BEHAVIOR = "ineligible-model-behavior"


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
            # v6 buys no paid retry; the shared v3 fixture predates that rule.
            "protocol_repair_attempts": 0,
        }
    )
    raw["run_info"]["provider_options"]["GM_BENCH_PROTOCOL_REPAIR_ATTEMPTS"] = "0"
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


def synthetic_panel_seeds() -> list[int]:
    """Twenty-nine deterministic seeds standing in for the private v6 panel."""
    return [900000001 + 7 * index for index in range(29)]


def synthetic_panel_artifact(spec: dict[str, Any], seeds: list[int], *, score_offset: float) -> dict[str, Any]:
    """Return a 29-seed, one-repeat synthetic artifact shaped for one registered route.

    ``spec`` is a resolved registry spec (fixed options already merged), so the
    artifact satisfies the analyzer's route-identity checks without any provider
    call. Scores are arithmetic, not evidence.
    """
    seasons = int(PRESETS["leaderboard"]["seasons"])
    decisions = seasons * 4
    agent = f"rehearsal:{spec['id']}"
    episodes = []
    for index, seed in enumerate(seeds):
        score = 330.0 + (4.0 * index) + score_offset
        episodes.append(
            {
                "seed": seed,
                "repeat": 1,
                "seasons": seasons,
                "final_score": score,
                "strategy_score": score,
                "protocol_penalty": 0.0,
                "score_components": _score_components(score),
                "wins": 110 + index,
                "championships": index % 2,
                "illegal_actions": 0,
                "decisions": decisions,
                "failed_decisions": 0,
                "usage": {
                    "decisions_with_usage": decisions,
                    "cost_decisions": decisions,
                    "cost_usd": 0.0,
                    "provider": "openrouter",
                    "model": spec["model"],
                    "upstream_provider": spec["upstream_provider"],
                    "upstream_providers": [spec["upstream_provider"]],
                },
            }
        )
    candidate = {
        "agent": agent,
        "seeds": seeds,
        "seasons": seasons,
        "repeats": 1,
        "episodes": episodes,
        "summary": summarize_episodes(episodes),
    }
    baselines = []
    for baseline_index, name in enumerate(PRESETS["leaderboard"]["baselines"]):
        baseline_episodes = []
        for index, seed in enumerate(seeds):
            score = 300.0 + (2.0 * index) if name == "pick-trader" else 100.0 + baseline_index + index
            baseline_episodes.append(
                {
                    "seed": seed,
                    "seasons": seasons,
                    "final_score": score,
                    "strategy_score": score,
                    "protocol_penalty": 0.0,
                    "score_components": _score_components(score),
                    "wins": 80 + index,
                    "championships": index % 2,
                    "illegal_actions": 0,
                    "decisions": decisions,
                    "failed_decisions": 0,
                }
            )
        baselines.append(
            {
                "agent": name,
                "seeds": seeds,
                "seasons": seasons,
                "episodes": baseline_episodes,
                "summary": summarize_episodes(baseline_episodes),
            }
        )
    candidate_mean = _precise_mean_score(candidate)
    baseline_mean = sum(_precise_mean_score(baseline) for baseline in baselines) / len(baselines)
    return {
        "agent": agent,
        "seeds": seeds,
        "seasons": seasons,
        "candidate": candidate,
        "baselines": baselines,
        "normalized": {
            "candidate_mean_score": round(candidate_mean, 3),
            "baseline_panel_mean_score": round(baseline_mean, 3),
            "score_lift": round(candidate_mean - baseline_mean, 3),
            "score_lift_pct": round(((candidate_mean / baseline_mean) - 1.0) * 100.0, 2),
            "candidate_illegal_actions": 0,
            "baseline_illegal_actions": 0,
        },
        "paired": _paired_analysis(seeds, candidate, baselines),
        "run_info": {
            "command": "model",
            "agent": agent,
            "provider": "openrouter",
            "model": spec["model"],
            "transport": spec["transport"],
            "preset": "leaderboard",
            "profile": "compact",
            "gm_bench_version": "0.0.0+rehearsal",
            "evidence_class": "synthetic-non-evidence",
            "benchmark_contract": _v5_contract(),
            "scaffold_fingerprint": POLICIES["sota-v5"].expected_scaffold_fingerprints["openrouter"],
            "seed_panel": seed_panel_metadata(seeds, "leaderboard"),
            "protocol_repair_attempts": 0,
            "strict_fallback": True,
            "provider_options": {key: str(value) for key, value in spec["fixed_options"].items()},
        },
    }


def _authorized_copy(record: dict[str, Any]) -> dict[str, Any]:
    return {**copy.deepcopy(record), "publication_authorized": True}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def stage_accounted_for_inputs(workdir: Path) -> dict[str, Any]:
    """Stage a synthetic accounted-for sota-v5 release under ``workdir``.

    The four frozen records are authorized in memory only; the authorized
    copies are materialized solely inside the temporary staging tree, never in
    the repository. Returns the staging root, the results root holding the
    contract-scoped artifacts, the analysis, the register entries, and the
    synthetic seeds so callers can build, mutate, and verify.
    """
    records = {label: json.loads((ROOT / relative).read_text()) for label, relative in V5_RECORD_FILES.items()}
    register = json.loads((ROOT / V5_REGISTER_FILE).read_text())
    # The proof authorizes its own in-memory copies, so it must not depend on
    # whether the checked-in records are locked (before the 2026-09-03 release
    # decision) or authorized (after it); it only requires the flag to exist.
    for label, record in records.items():
        if not isinstance(record.get("publication_authorized"), bool):
            raise AssertionError(f"checked-in sota-v5 {label} publication_authorized is not a boolean")

    specs, spec_errors = _registry_specs(records["registry"])
    if spec_errors:
        raise AssertionError(f"checked-in sota-v5 registry is not analyzable: {spec_errors}")
    register_entries = {str(entry["id"]): entry for entry in register["entries"]}
    if len(specs) != 16 or len(register_entries) != 5:
        raise AssertionError("the accounted-for proof expects the sixteen-row family with five register entries")

    seeds = synthetic_panel_seeds()
    policy = POLICIES["sota-v5"]
    raws: list[dict[str, Any]] = []
    compacts: list[dict[str, Any]] = []
    redacted_headlines: dict[str, dict[str, Any]] = {}
    redacted_diagnostics: dict[str, dict[str, Any]] = {}
    env = __import__("os").environ
    prior = env.get(PRIVATE_SEEDS_ENV)
    env[PRIVATE_SEEDS_ENV] = ",".join(str(seed) for seed in seeds)
    try:
        for index, spec in enumerate(specs):
            raw = synthetic_panel_artifact(spec, seeds, score_offset=3.0 * index)
            report = validate_leaderboard_payload(raw, policy=policy)
            if not report.ok:
                raise AssertionError(f"synthetic artifact for {spec['id']} failed validation: {report.errors}")
            compact = compact_result(raw)
            redacted, redaction_report = redact_leaderboard_payload(compact, policy=policy)
            if not redaction_report.ok or redacted.get("seeds") != "<redacted>":
                raise AssertionError(f"synthetic redaction for {spec['id']} did not remove private seeds")
            entry = register_entries.get(spec["id"])
            if entry is None:
                raws.append(raw)
                compacts.append(compact)
                redacted_headlines[spec["id"]] = redacted
            elif entry["status"] == INELIGIBLE_MODEL_BEHAVIOR:
                # Stand-in for the redacted diagnostic the Artifacts step builds
                # from the retained checkpoint; only its shape and hash link
                # matter here. The register digest is the byte SHA-256 of the
                # checkpoint file, which redact-result's canonical
                # raw_artifact_sha256 can never equal, hence the separate field.
                redacted["publication"]["source_checkpoint_sha256"] = entry["evidence"]["checkpoint_sha256"]
                redacted_diagnostics[spec["id"]] = redacted
        # The analyzer validates unredacted private payloads, so it needs the
        # synthetic panel in the environment just as the real run does.
        authorized = {label: _authorized_copy(record) for label, record in records.items()}
        authorized["lane"]["seed_panel"] = {
            **authorized["lane"]["seed_panel"],
            "count": len(seeds),
            "sha256": raws[0]["run_info"]["seed_panel"]["sha256"],
        }
        analysis = analyze(
            authorized["registry"],
            compacts,
            raw_payloads=raws,
            lane=authorized["lane"],
            protocol=authorized["protocol"],
            pricing=authorized["pricing"],
            exclusions=register,
        )
    finally:
        if prior is None:
            env.pop(PRIVATE_SEEDS_ENV, None)
        else:
            env[PRIVATE_SEEDS_ENV] = prior

    staging = workdir / "accounted-for-repo"
    results_root = workdir / "accounted-for-results"
    shutil.copytree(ROOT / "config", staging / "config")
    (staging / V5_ROUTE_EVIDENCE_FILE).parent.mkdir(parents=True)
    shutil.copy2(ROOT / V5_ROUTE_EVIDENCE_FILE, staging / V5_ROUTE_EVIDENCE_FILE)
    for label, relative in V5_RECORD_FILES.items():
        _write_json(staging / relative, authorized[label])
    _write_json(staging / "results/analysis/publication-panel-analysis-v5.json", analysis)
    for model_id, payload in redacted_headlines.items():
        _write_json(results_root / "results/leaderboard/sota-v5" / f"{model_id}.json", payload)
    for model_id, payload in redacted_diagnostics.items():
        _write_json(results_root / "results/diagnostics/sota-v5" / f"{model_id}.json", payload)
    return {
        "staging": staging,
        "results_root": results_root,
        "analysis": analysis,
        "register_entries": register_entries,
        "seeds": seeds,
    }


def run_accounted_for_proof(workdir: Path) -> dict[str, Any]:
    """Prove the accounted-for release path on synthetic rows without touching the repo records."""
    guarded = [ROOT / relative for relative in V5_RECORD_FILES.values()] + [ROOT / V5_REGISTER_FILE]
    guard_before = [hashlib.sha256(path.read_bytes()).hexdigest() for path in guarded]
    staged = stage_accounted_for_inputs(workdir)
    analysis = staged["analysis"]
    register_entries = staged["register_entries"]
    expected = {
        "publication_ready": True,
        "status": "complete",
        "eligible_model_count": 11,
        "accounted_for_model_count": 16,
        "holm_family_size": 16,
        "registered_model_count": 16,
        "minimum_headline_models": 8,
    }
    observed = {key: analysis.get(key) for key in expected}
    if observed != expected or len(analysis.get("excluded_models") or []) != 5 or analysis.get("config_errors"):
        raise AssertionError(f"accounted-for analysis did not pass: {observed} {analysis.get('config_errors')}")

    archive_path = workdir / "accounted-for-release.zip"
    manifest = build_release(
        repo_root=staged["staging"],
        run_dir=staged["staging"],
        archive_path=archive_path,
        manifest_path=workdir / "accounted-for-manifest.json",
        checksums_path=workdir / "accounted-for-release.SHA256SUMS",
        contract="sota-v5",
        release_id="sota-v5-rehearsal-accounted-for",
        release_date="2099-01-01",
        results_root=staged["results_root"],
    )
    verified = verify_archive(archive_path)
    statuses = {str(row["model_id"]): str(row["status"]) for row in verified["artifacts"]}
    excluded_ids = sorted(model_id for model_id, status in statuses.items() if status == "excluded")
    if (
        manifest["eligible_headline_models"] != 11
        or manifest["diagnostic_models"] != 3
        or manifest["excluded_models"] != 5
        or excluded_ids != sorted(register_entries)
    ):
        raise AssertionError(f"accounted-for release did not classify the family as expected: {manifest}")
    with zipfile.ZipFile(archive_path) as packaged:
        names = packaged.namelist()
        public_bytes = b"\n".join(packaged.read(name) for name in names)
    if V5_REGISTER_FILE not in names or any(name.startswith("raw/") for name in names):
        raise AssertionError("accounted-for release archive is missing the register or carries raw evidence")
    if any(str(seed).encode() in public_bytes for seed in staged["seeds"]):
        raise AssertionError("accounted-for release archive leaked a synthetic private seed value")

    guard_after = [hashlib.sha256(path.read_bytes()).hexdigest() for path in guarded]
    if guard_before != guard_after:
        raise AssertionError("accounted-for proof modified a checked-in sota-v5 record")
    return {
        "status": "passed",
        "records_authorized_in_memory_only": True,
        "analysis": {key: analysis[key] for key in expected},
        "release": {
            "archive": str(archive_path),
            "eligible_headline_models": manifest["eligible_headline_models"],
            "diagnostic_models": manifest["diagnostic_models"],
            "excluded_models": manifest["excluded_models"],
            "verified": True,
        },
    }


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
    accounted_for = run_accounted_for_proof(workdir)
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
        "accounted_for_release": accounted_for,
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
