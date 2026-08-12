#!/usr/bin/env python3
"""Launch the authorized SOTA-v3 smoke without exposing private seeds.

The private panel is read from macOS Keychain, verified against the committed
ordered hash and salted hiding commitment, and passed to the publication runner
only through ``GM_BENCH_PRIVATE_SEEDS`` in this process. The runner still
requires an explicit spend ceiling and retains every normal route, reservation,
strict-failure, and smoke-manifest gate.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gm_bench.benchmark_config import PRIVATE_SEEDS_ENV, seed_panel_hash  # noqa: E402
from gm_bench.contract import contract_fingerprint, scaffold_fingerprint  # noqa: E402
from gm_bench.publication import canonical_sha256, v3_route_acceptance_issues  # noqa: E402
from scripts.run_publication_matrix import main as publication_main  # noqa: E402
from scripts.seed_panel_commitment import commitment, parse_ordered_seeds  # noqa: E402

KEYCHAIN_ACCOUNT = "nedcutler"
KEYCHAIN_SERVICE = "gm-bench-sota-v3-private-panel"
CANONICAL_OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"


def _keychain_record() -> dict[str, object]:
    result = subprocess.run(  # noqa: S603 - fixed macOS Keychain command
        [
            "security",
            "find-generic-password",
            "-s",
            KEYCHAIN_SERVICE,
            "-a",
            KEYCHAIN_ACCOUNT,
            "-w",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    raw = result.stdout.strip()
    try:
        decoded = bytes.fromhex(raw).decode() if not raw.startswith("{") else raw
        record = json.loads(decoded)
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Keychain seed record is not valid gm-bench JSON") from exc
    if not isinstance(record, dict):
        raise ValueError("Keychain seed record must be a JSON object")
    return record


def _verified_seed_text() -> str:
    lane = json.loads((ROOT / "config" / "sota_v3_lane.json").read_text())
    panel = lane.get("seed_panel") or {}
    record = _keychain_record()
    seeds_text = record.get("seeds")
    salt = record.get("salt")
    if not isinstance(seeds_text, str) or not isinstance(salt, str):
        raise ValueError("Keychain seed record is missing seeds or salt")
    seeds = parse_ordered_seeds(seeds_text)
    if panel.get("status") != "frozen" or panel.get("name") != "private-env":
        raise ValueError("committed SOTA-v3 lane does not declare a frozen private panel")
    if len(seeds) != panel.get("count") or seed_panel_hash(seeds) != panel.get("sha256"):
        raise ValueError("Keychain seed order does not match the committed execution hash")
    if commitment(salt, seeds) != panel.get("hiding_commitment_sha256"):
        raise ValueError("Keychain seed panel does not match the committed hiding commitment")
    return seeds_text


def _record_readiness(path: Path, *, max_spend_usd: float, mode: str) -> None:
    lane = json.loads((ROOT / "config" / "sota_v3_lane.json").read_text())
    registry_path = ROOT / "config" / "sota_v3_models.json"
    registry = json.loads(registry_path.read_text())
    route_issues = v3_route_acceptance_issues(registry)
    if route_issues:
        raise ValueError("cannot record final readiness before route acceptance: " + "; ".join(route_issues))
    fingerprint = contract_fingerprint()
    if lane.get("contract_fingerprint") != fingerprint or registry.get("contract_fingerprint") != fingerprint:
        raise ValueError("cannot record final readiness against a stale contract fingerprint")
    acceptance = registry["exact_route_acceptance"]
    route_relative = str(acceptance["evidence_artifact"])
    route_payload = json.loads((ROOT / route_relative).read_text())
    panel = lane.get("seed_panel") or {}
    model_ids = [str(model["id"]) for model in registry.get("models") or []]
    existing: dict[str, object] = {}
    if path.exists():
        payload = json.loads(path.read_text())
        if isinstance(payload, dict) and payload.get("contract_fingerprint") == fingerprint:
            existing = payload
    evidence = {
        "format": "gm-bench-sota-v3-final-preflight-v1",
        "schema_version": 1,
        "contract": "sota-v3",
        "contract_fingerprint": fingerprint,
        "openrouter_scaffold_fingerprint": scaffold_fingerprint("openrouter"),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "canonical_openrouter_api_base": CANONICAL_OPENROUTER_API_BASE,
        "completion_calls": 0,
        "route_preflight": {
            "status": "accepted",
            "evidence_artifact": route_relative,
            "evidence_sha256": canonical_sha256(route_payload),
            "verified_at_utc": route_payload.get("generated_at_utc"),
        },
    }
    if mode == "dry-run":
        evidence["keychain_dry_run"] = {
            "status": "passed",
            "model_ids": model_ids,
            "commands_constructed": len(model_ids),
            "operator_ceiling_usd": max_spend_usd,
            "seed_panel_sha256": panel.get("sha256"),
            "hiding_commitment_verified": True,
            "private_seed_values_included": False,
        }
        live_preflight = existing.get("authenticated_route_and_price_preflight")
        if isinstance(live_preflight, dict):
            evidence["authenticated_route_and_price_preflight"] = live_preflight
    else:
        evidence["authenticated_route_and_price_preflight"] = {
            "status": "passed",
            "model_ids": model_ids,
            "commands_executed": len(model_ids),
            "completion_calls": 0,
            "canonical_openrouter_api_base": CANONICAL_OPENROUTER_API_BASE,
            "pricing_checked": True,
        }
        dry_run = existing.get("keychain_dry_run")
        if isinstance(dry_run, dict):
            evidence["keychain_dry_run"] = dry_run
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, indent=2, sort_keys=True, allow_nan=False) + "\n")
    relative = str(path.resolve().relative_to(ROOT.resolve()))
    accepted = "keychain_dry_run" in evidence and "authenticated_route_and_price_preflight" in evidence
    lane["final_preflight_evidence"] = {
        "status": "accepted" if accepted else "pending",
        "artifact": relative,
        "sha256": canonical_sha256(evidence),
        "contract_fingerprint": fingerprint,
        "completion_calls": 0,
        "operator_ceiling_usd": max_spend_usd,
    }
    (ROOT / "config" / "sota_v3_lane.json").write_text(json.dumps(lane, indent=2, allow_nan=False) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-spend-usd", required=True, type=float)
    parser.add_argument("--run-dir", default=str(ROOT / "data" / "publication" / "sota-v3-smokes"))
    parser.add_argument("--model-id")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument(
        "--record-readiness",
        type=Path,
        help="after a successful dry run or authenticated preflight, record final-fingerprint readiness evidence",
    )
    args = parser.parse_args(argv)
    if args.dry_run and args.preflight_only:
        parser.error("--dry-run and --preflight-only are mutually exclusive")
    if args.record_readiness is not None and not (args.dry_run or args.preflight_only):
        parser.error("--record-readiness requires --dry-run or --preflight-only")
    readiness_path = None
    if args.record_readiness is not None:
        readiness_path = args.record_readiness
        if not readiness_path.is_absolute():
            readiness_path = ROOT / readiness_path
        readiness_path = readiness_path.resolve()
        if not readiness_path.is_relative_to(ROOT.resolve()):
            parser.error("--record-readiness must be inside the repository")
    os.environ[PRIVATE_SEEDS_ENV] = _verified_seed_text()
    runner_args = [
        "smoke",
        "--contract",
        "sota-v3",
        "--run-dir",
        args.run_dir,
        "--max-spend-usd",
        str(args.max_spend_usd),
    ]
    if args.model_id:
        runner_args.extend(["--model-id", args.model_id])
    if args.dry_run:
        runner_args.append("--dry-run")
    if args.preflight_only:
        runner_args.append("--preflight-only")
    try:
        result = publication_main(runner_args)
        if result == 0 and readiness_path is not None:
            mode = "preflight-only" if args.preflight_only else "dry-run"
            _record_readiness(readiness_path, max_spend_usd=args.max_spend_usd, mode=mode)
        return result
    finally:
        os.environ.pop(PRIVATE_SEEDS_ENV, None)


if __name__ == "__main__":
    raise SystemExit(main())
