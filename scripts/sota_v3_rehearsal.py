"""Zero-spend end-to-end rehearsal for the future sota-v3 evidence lane.

The rehearsal creates deterministic synthetic raw and compact artifacts in a
temporary directory, validates them under the live sota-v3 policy, proves
selected mutations fail closed, and runs the public leaderboard builder in an
isolated repository copy.  No model/provider is invoked and no file under
``results/leaderboard`` is written.

Run from the repository root:

    python3 scripts/sota_v3_rehearsal.py

Pass ``--skip-web-build`` when Bun is unavailable.  The Python site-data
builder still runs and must reproduce the checked-in frozen sota-v2 dataset.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import io
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gm_bench.benchmark_config import PRESETS, seed_panel_metadata  # noqa: E402
from gm_bench.contract import SOTA_V2_CONTRACT, benchmark_contract, scaffold_fingerprint  # noqa: E402
from gm_bench.official import (  # noqa: E402
    POLICIES,
    SOTA_V2_POLICY,
    SOTA_V3_POLICY,
    validate_leaderboard_payload,
)
from gm_bench.publication import (  # noqa: E402
    canonical_sha256,
    compact_result,
    publication_execution_issues,
    raw_artifact_link_issues,
)
from gm_bench.runner import _paired_analysis, _precise_mean_score, summarize_episodes  # noqa: E402
from gm_bench.scoring import ACTIVE_SCORE_SCALE, SCORE_COMPONENT_KEYS  # noqa: E402
from scripts.analyze_publication_panel import analyze  # noqa: E402
from web.scripts import build_leaderboard  # noqa: E402


def _score_components(strategy_score: float) -> dict[str, float]:
    components = {name: 0.0 for name in SCORE_COMPONENT_KEYS}
    components["recent_wins"] = round(strategy_score / ACTIVE_SCORE_SCALE.recent_win, 6)
    components["recent_wins_contribution"] = strategy_score
    return components


def synthetic_raw_artifact() -> dict[str, Any]:
    """Build deterministic, internally consistent evidence without a model call."""
    preset = PRESETS["leaderboard"]
    seeds = list(preset["seeds"])
    seasons = int(preset["seasons"])
    repeats = 3
    candidate_episodes = []
    for seed_index, seed in enumerate(seeds):
        seed_center = 330.0 + (4.0 * seed_index)
        for repeat, repeat_offset in enumerate((-6.0, 0.0, 6.0), start=1):
            score = seed_center + repeat_offset
            candidate_episodes.append(
                {
                    "seed": seed,
                    "repeat": repeat,
                    "seasons": seasons,
                    "final_score": score,
                    "strategy_score": score,
                    "protocol_penalty": 0.0,
                    "score_components": _score_components(score),
                    "wins": 110 + seed_index,
                    "championships": seed_index % 2,
                    "illegal_actions": 0,
                    "decisions": seasons * 4,
                    "failed_decisions": 0,
                    "usage": {
                        "decisions_with_usage": seasons * 4,
                        "cost_decisions": seasons * 4,
                        "cost_usd": 0.0,
                        "provider": "openrouter",
                        "model": "synthetic-v3",
                        "upstream_provider": "SyntheticProvider",
                        "upstream_providers": ["SyntheticProvider"],
                    },
                }
            )
    candidate = {
        "agent": "rehearsal:synthetic-v3",
        "seeds": seeds,
        "seasons": seasons,
        "repeats": repeats,
        "episodes": candidate_episodes,
        "summary": summarize_episodes(candidate_episodes),
    }
    baselines = []
    for baseline_index, name in enumerate(preset["baselines"]):
        episodes = []
        for seed_index, seed in enumerate(seeds):
            score = 300.0 + (2.0 * seed_index) if name == "pick-trader" else 100.0 + baseline_index + seed_index
            episodes.append(
                {
                    "seed": seed,
                    "seasons": seasons,
                    "final_score": score,
                    "strategy_score": score,
                    "protocol_penalty": 0.0,
                    "score_components": _score_components(score),
                    "wins": 80 + seed_index,
                    "championships": seed_index % 2,
                    "illegal_actions": 0,
                    "decisions": seasons * 4,
                    "failed_decisions": 0,
                }
            )
        baselines.append(
            {
                "agent": name,
                "seeds": seeds,
                "seasons": seasons,
                "episodes": episodes,
                "summary": summarize_episodes(episodes),
            }
        )
    candidate_mean = _precise_mean_score(candidate)
    baseline_mean = sum(_precise_mean_score(baseline) for baseline in baselines) / len(baselines)
    payload = {
        "agent": "rehearsal:synthetic-v3",
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
            "agent": "rehearsal:synthetic-v3",
            "provider": "openrouter",
            "model": "synthetic-v3",
            "transport": "gateway-api",
            "preset": "leaderboard",
            "profile": "compact",
            "gm_bench_version": "0.0.0+rehearsal",
            "evidence_class": "synthetic-non-evidence",
            "benchmark_contract": benchmark_contract(),
            "scaffold_fingerprint": scaffold_fingerprint("openrouter"),
            "seed_panel": seed_panel_metadata(seeds, "leaderboard"),
            "protocol_repair_attempts": 1,
            "strict_fallback": True,
            "provider_options": {
                "GM_BENCH_PROTOCOL_REPAIR_ATTEMPTS": "1",
                "GM_AGENT_STRICT": "1",
                "GM_BENCH_OUTPUT_BUDGET_CELL": "4096",
                "OPENROUTER_ALLOW_FALLBACKS": "false",
                "OPENROUTER_REQUIRE_PARAMETERS": "true",
                "OPENROUTER_DATA_COLLECTION": "deny",
                "OPENROUTER_REASONING_ENABLED": "false",
                "OPENROUTER_PROVIDER_ONLY": "synthetic/fp8",
                "OPENROUTER_EXPECTED_UPSTREAM_PROVIDER": "SyntheticProvider",
                "OPENROUTER_EXPECTED_ENDPOINT_NAME": "SyntheticProvider | synthetic-v3",
                "OPENROUTER_MAX_TOKENS": "4096",
            },
        },
    }
    return payload


def synthetic_analysis_registry() -> dict[str, Any]:
    """Return a frozen synthetic registry used only inside the rehearsal."""
    return {
        "schema_version": 1,
        "contract": "sota-v3",
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
                "id": "synthetic-v3",
                "provider": "openrouter",
                "model": "synthetic-v3",
                "transport": "gateway-api",
                "upstream_provider": "SyntheticProvider",
                "upstream_provider_slug": "synthetic/fp8",
                "endpoint_tag": "synthetic/fp8",
                "endpoint_name": "SyntheticProvider | synthetic-v3",
                "fixed_options": {"OPENROUTER_REASONING_ENABLED": "false"},
                "absent_options": [],
            }
        ],
    }


def _require_valid(payload: dict[str, Any]) -> None:
    report = validate_leaderboard_payload(payload, policy=SOTA_V3_POLICY)
    if not report.ok:
        raise AssertionError(f"synthetic sota-v3 artifact failed validation: {report.errors}")


def _require_failure(name: str, payload: dict[str, Any], expected_text: str) -> dict[str, Any]:
    report = validate_leaderboard_payload(payload, policy=SOTA_V3_POLICY)
    if report.ok or not any(expected_text in error for error in report.errors):
        raise AssertionError(
            f"mutation {name!r} did not fail as expected; wanted {expected_text!r}, got {report.errors!r}"
        )
    return {"name": name, "status": "rejected", "matched": expected_text}


def _exercise_mutations(raw: dict[str, Any], compact: dict[str, Any]) -> list[dict[str, Any]]:
    wrong_contract = copy.deepcopy(compact)
    wrong_contract["run_info"]["benchmark_contract"] = SOTA_V2_CONTRACT

    soft_fallback = copy.deepcopy(compact)
    soft_fallback["run_info"]["strict_fallback"] = False
    soft_fallback["run_info"]["provider_options"]["GM_AGENT_STRICT"] = "0"

    stale_scaffold = copy.deepcopy(compact)
    stale_scaffold["run_info"]["scaffold_fingerprint"] = "0" * 16

    tampered_score = copy.deepcopy(compact)
    tampered_score["candidate"]["episodes"][0]["final_score"] = 9999.0

    unknown_version = copy.deepcopy(compact)
    unknown_version["run_info"]["benchmark_contract"]["benchmark_version"] = "sota-v999"
    declared_version = unknown_version["run_info"]["benchmark_contract"]["benchmark_version"]
    if declared_version in POLICIES:
        raise AssertionError("unknown benchmark version unexpectedly dispatched to a validation policy")

    changed_raw = copy.deepcopy(raw)
    changed_raw["run_info"]["rehearsal_mutation"] = True
    link_issues = raw_artifact_link_issues(compact, [changed_raw])
    expected_link_issue = "publication.raw_artifact_sha256 does not match any supplied raw artifact"
    if expected_link_issue not in link_issues:
        raise AssertionError(f"repository raw-link verifier did not reject changed evidence: {link_issues!r}")

    unregistered_row = build_leaderboard.model_row(
        compact,
        {
            "models": [
                {
                    "id": "registered-rehearsal",
                    "provider": "openai",
                    "model": "different-registered-model",
                }
            ]
        },
    )
    identity_issue = next(
        (issue for issue in unregistered_row["publication_issues"] if "provider/model is not pre-registered" in issue),
        None,
    )
    if identity_issue is None:
        raise AssertionError("shared row-ingestion policy accepted an unregistered provider/model route")

    return [
        _require_failure("wrong-contract", wrong_contract, "run_info.benchmark_contract"),
        _require_failure("soft-fallback", soft_fallback, "strict failure handling"),
        _require_failure("stale-scaffold", stale_scaffold, "does not match current scaffold"),
        {
            "name": "unknown-version-dispatch",
            "status": "rejected",
            "matched": f"no policy registered for {declared_version}",
        },
        {
            "name": "unregistered-route",
            "status": "rejected",
            "matched": identity_issue,
        },
        _require_failure("tampered-compact-score", tampered_score, "episode-derived"),
        {
            "name": "raw-link-mismatch",
            "status": "rejected",
            "matched": expected_link_issue,
        },
    ]


@contextlib.contextmanager
def _isolated_builder_globals(staging: Path):
    names = (
        "ROOT",
        "RESULTS_DIR",
        "OUTPUT_PATH",
        "MODEL_CONFIG_PATH",
        "PROTOCOL_CONFIG_PATH",
        "PANEL_ANALYSIS_PATH",
    )
    original = {name: getattr(build_leaderboard, name) for name in names}
    build_leaderboard.ROOT = staging
    build_leaderboard.RESULTS_DIR = staging / "results" / "leaderboard"
    build_leaderboard.OUTPUT_PATH = staging / "web" / "src" / "data" / "leaderboard.json"
    build_leaderboard.MODEL_CONFIG_PATH = staging / "config" / "sota_v2_models.json"
    build_leaderboard.PROTOCOL_CONFIG_PATH = staging / "config" / "publication_protocol.json"
    build_leaderboard.PANEL_ANALYSIS_PATH = staging / "results" / "analysis" / "publication-panel-analysis.json"
    try:
        yield
    finally:
        for name, value in original.items():
            setattr(build_leaderboard, name, value)


def _stage_site_inputs(staging: Path, compact: dict[str, Any]) -> None:
    shutil.copytree(ROOT / "config", staging / "config")
    shutil.copytree(ROOT / "results" / "leaderboard", staging / "results" / "leaderboard")
    shutil.copytree(ROOT / "results" / "analysis", staging / "results" / "analysis")
    shutil.copytree(
        ROOT / "web",
        staging / "web",
        ignore=shutil.ignore_patterns("dist", "node_modules"),
    )
    source_modules = ROOT / "web" / "node_modules"
    if source_modules.is_dir():
        (staging / "web" / "node_modules").symlink_to(source_modules, target_is_directory=True)
    (staging / "results" / "leaderboard" / "synthetic-sota-v3.json").write_text(
        json.dumps(compact, indent=2, sort_keys=True) + "\n"
    )


def _exercise_site_builder(staging: Path, compact: dict[str, Any]) -> dict[str, Any]:
    _stage_site_inputs(staging, compact)
    model_config = json.loads((staging / "config" / "sota_v2_models.json").read_text())
    transformed = build_leaderboard.model_row(compact, model_config)
    if transformed["benchmark_version"] != "sota-v3":
        raise AssertionError("shared row-ingestion logic lost the artifact's sota-v3 identity")
    if transformed["artifact_sha256"] != canonical_sha256(compact):
        raise AssertionError("shared row-ingestion logic did not preserve the compact artifact identity")
    stdout = io.StringIO()
    stderr = io.StringIO()
    with (
        _isolated_builder_globals(staging),
        contextlib.redirect_stdout(stdout),
        contextlib.redirect_stderr(stderr),
    ):
        build_leaderboard.main()
    generated_path = staging / "web" / "src" / "data" / "leaderboard.json"
    generated = json.loads(generated_path.read_text())
    frozen = json.loads((ROOT / "web" / "src" / "data" / "leaderboard.json").read_text())
    if generated != frozen:
        raise AssertionError("isolated site-data build changed the frozen sota-v2 dataset")
    if generated["contract"]["benchmark_version"] != "sota-v2":
        raise AssertionError("isolated site-data build did not remain on sota-v2")
    if not any("synthetic-v3" in line and "not sota-v2" in line for line in stderr.getvalue().splitlines()):
        raise AssertionError("site-data build did not explicitly report excluding the synthetic sota-v3 artifact")
    return {
        "status": "passed",
        "contract": generated["contract"]["benchmark_version"],
        "synthetic_v3_excluded": True,
        "matches_checked_in_dataset": True,
        "shared_row_ingestion": "passed",
        "public_v3_strategy_selected": False,
    }


def execution_authorization_issues(
    lane: dict[str, Any],
    *,
    mode: str,
    registry: dict[str, Any] | None = None,
    manifest: dict[str, Any] | None = None,
    protocol: dict[str, Any] | None = None,
    pricing: dict[str, Any] | None = None,
) -> list[str]:
    """Expose the runner's shared authorization gate in rehearsal output."""
    if mode == "synthetic":
        return []
    return publication_execution_issues(
        lane,
        registry or {},
        manifest,
        phase=mode,
        protocol=protocol,
        pricing=pricing,
    )


def _live_v3_readiness() -> dict[str, Any]:
    lane = json.loads((ROOT / "config" / "sota_v3_lane.json").read_text())
    registry = json.loads((ROOT / "config" / "sota_v3_models.json").read_text())
    manifest = json.loads((ROOT / "config" / "sota_v3_smoke_manifest.json").read_text())
    protocol = json.loads((ROOT / "config" / "sota_v3_publication_protocol.json").read_text())
    pricing = json.loads((ROOT / "config" / "sota_v3_pricing_snapshot.json").read_text())
    return {
        "synthetic_validation_issues": execution_authorization_issues(
            lane,
            mode="synthetic",
            registry=registry,
            manifest=manifest,
        ),
        "smoke_execution_issues": execution_authorization_issues(
            lane,
            mode="smoke",
            registry=registry,
            manifest=manifest,
            protocol=protocol,
            pricing=pricing,
        ),
        "panel_execution_issues": execution_authorization_issues(
            lane,
            mode="panel",
            registry=registry,
            manifest=manifest,
            protocol=protocol,
            pricing=pricing,
        ),
    }


def _run_web_build(staging: Path) -> dict[str, Any]:
    bun = shutil.which("bun")
    if bun is None:
        candidate = Path.home() / ".bun" / "bin" / "bun"
        bun = str(candidate) if candidate.is_file() else None
    if bun is None:
        raise RuntimeError("Bun is not installed; rerun with --skip-web-build")
    completed = subprocess.run(
        [bun, "run", "build"],
        cwd=staging / "web",
        check=True,
        capture_output=True,
        text=True,
    )
    return {"status": "passed", "command": f"{bun} run build", "output": completed.stdout.strip().splitlines()[-1:]}


def run_rehearsal(workdir: Path, *, run_web_build: bool, mode: str = "synthetic") -> dict[str, Any]:
    if mode != "synthetic":
        raise ValueError(
            "this zero-spend harness only implements synthetic mode; panel execution belongs to the "
            "publication runner and must independently clear both authorization locks"
        )
    workdir.mkdir(parents=True, exist_ok=True)
    raw = synthetic_raw_artifact()
    _require_valid(raw)
    compact = compact_result(raw)
    _require_valid(compact)
    raw_hash = canonical_sha256(raw)
    if compact["publication"]["raw_artifact_sha256"] != raw_hash:
        raise AssertionError("compact artifact does not hash-link to its raw evidence")

    raw_path = workdir / "synthetic-sota-v3.raw.json"
    compact_path = workdir / "synthetic-sota-v3.compact.json"
    raw_path.write_text(json.dumps(raw, indent=2, sort_keys=True) + "\n")
    compact_path.write_text(json.dumps(compact, indent=2, sort_keys=True) + "\n")

    wrong_policy = validate_leaderboard_payload(compact, policy=SOTA_V2_POLICY)
    if wrong_policy.ok:
        raise AssertionError("sota-v2 policy unexpectedly accepted a sota-v3 artifact")
    analysis = analyze(synthetic_analysis_registry(), [compact], raw_payloads=[raw])
    if analysis["status"] != "complete" or analysis["eligible_model_count"] != 1:
        raise AssertionError(f"sota-v3 analysis rehearsal failed: {analysis!r}")
    analyzed = analysis["models"][0]
    if analyzed["bootstrap_ci95"][0] == analyzed["bootstrap_ci95"][1]:
        raise AssertionError("analysis rehearsal remained degenerate; expected a non-zero lift interval")

    site_staging = Path(tempfile.mkdtemp(prefix="site-staging-", dir=workdir))
    result = {
        "status": "passed",
        "mode": mode,
        "evidence_class": "synthetic-non-evidence",
        "spend_usd": 0.0,
        "workdir": str(workdir),
        "artifacts": {
            "raw": str(raw_path),
            "compact": str(compact_path),
            "canonical_raw_sha256": raw_hash,
        },
        "policy_selection": {
            "sota_v3": "accepted",
            "sota_v2": "rejected",
        },
        "analysis": {
            "status": analysis["status"],
            "eligible_model_count": analysis["eligible_model_count"],
            "holm_family_size": analysis["holm_family_size"],
            "mean_lift": analyzed["mean_lift"],
            "bootstrap_ci95": analyzed["bootstrap_ci95"],
            "tier": analyzed["tier"],
        },
        "mutations": _exercise_mutations(raw, compact),
        "site_data_build": _exercise_site_builder(site_staging, compact),
        "live_v3_readiness": _live_v3_readiness(),
        "web_build": _run_web_build(site_staging) if run_web_build else {"status": "skipped"},
    }
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workdir",
        type=Path,
        help="disposable output directory (default: a new system temporary directory)",
    )
    parser.add_argument("--skip-web-build", action="store_true", help="skip `bun run build`")
    parser.add_argument(
        "--mode",
        choices=("synthetic",),
        default="synthetic",
        help="zero-spend validation mode; this harness cannot execute a panel",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.workdir is None:
        with tempfile.TemporaryDirectory(prefix="gm-bench-sota-v3-rehearsal-") as temporary:
            result = run_rehearsal(Path(temporary), run_web_build=not args.skip_web_build, mode=args.mode)
            result["workdir"] = "<temporary-directory-removed>"
            for artifact in result["artifacts"]:
                result["artifacts"][artifact] = (
                    "<temporary-directory-removed>"
                    if artifact != "canonical_raw_sha256"
                    else result["artifacts"][artifact]
                )
    else:
        result = run_rehearsal(args.workdir.resolve(), run_web_build=not args.skip_web_build, mode=args.mode)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
