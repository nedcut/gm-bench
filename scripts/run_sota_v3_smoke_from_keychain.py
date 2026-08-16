#!/usr/bin/env python3
"""Launch an authorized strict publication smoke without exposing private seeds.

Historical v3/v4 launches verify the private panel in macOS Keychain. SOTA-v5
smokes deliberately do not read it: the public smoke seed needs no private
panel access, and the carried commitment requires an owner attestation before
the later panel. The runner still requires an explicit spend ceiling and
retains every route, reservation, strict-failure, and smoke-manifest gate.
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
from gm_bench.publication import (  # noqa: E402
    canonical_sha256,
    v3_route_acceptance_issues,
    v4_route_acceptance_issues,
    v5_route_acceptance_issues,
)
from scripts.run_publication_matrix import main as publication_main  # noqa: E402
from scripts.seed_panel_commitment import commitment, parse_ordered_seeds  # noqa: E402

KEYCHAIN_ACCOUNT = "nedcutler"
KEYCHAIN_SERVICE = "gm-bench-sota-v3-private-panel"
KEYCHAIN_SERVICES = {
    "sota-v3": KEYCHAIN_SERVICE,
    "sota-v4": KEYCHAIN_SERVICE,
    # V5 deliberately carries the still-unused v3 commitment forward. Reuse
    # the one escrow instead of copying secret material into a new identity.
    "sota-v5": KEYCHAIN_SERVICE,
}
CANONICAL_OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"
SUPPORTED_CONTRACTS = ("sota-v3", "sota-v4", "sota-v5")
ROUTE_ACCEPTANCE_CHECKS = {
    "sota-v3": v3_route_acceptance_issues,
    "sota-v4": v4_route_acceptance_issues,
    "sota-v5": v5_route_acceptance_issues,
}


def _contract_path(contract: str, kind: str) -> Path:
    suffixes = {
        "lane": "lane",
        "models": "models",
        "protocol": "publication_protocol",
    }
    return ROOT / "config" / f"{contract.replace('-', '_')}_{suffixes[kind]}.json"


def _keychain_record(contract: str = "sota-v3") -> dict[str, object]:
    result = subprocess.run(  # noqa: S603 - fixed macOS Keychain command
        [
            "security",
            "find-generic-password",
            "-s",
            KEYCHAIN_SERVICES.get(contract, KEYCHAIN_SERVICE),
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


def _verified_seed_text(contract: str = "sota-v3") -> str:
    lane = json.loads(_contract_path(contract, "lane").read_text())
    panel = lane.get("seed_panel") or {}
    record = _keychain_record(contract)
    seeds_text = record.get("seeds")
    salt = record.get("salt")
    if not isinstance(seeds_text, str) or not isinstance(salt, str):
        raise ValueError("Keychain seed record is missing seeds or salt")
    seeds = parse_ordered_seeds(seeds_text)
    if panel.get("status") != "frozen" or panel.get("name") != "private-env":
        raise ValueError(f"committed {contract} lane does not declare a frozen private panel")
    if len(seeds) != panel.get("count") or seed_panel_hash(seeds) != panel.get("sha256"):
        raise ValueError("Keychain seed order does not match the committed execution hash")
    if commitment(salt, seeds) != panel.get("hiding_commitment_sha256"):
        raise ValueError("Keychain seed panel does not match the committed hiding commitment")
    return seeds_text


def _record_readiness(path: Path, *, contract: str, max_spend_usd: float, mode: str) -> None:
    lane_path = _contract_path(contract, "lane")
    lane = json.loads(lane_path.read_text())
    registry_path = _contract_path(contract, "models")
    registry = json.loads(registry_path.read_text())
    route_issues = ROUTE_ACCEPTANCE_CHECKS[contract](registry)
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
        if (
            isinstance(payload, dict)
            and payload.get("contract") == contract
            and payload.get("format") == f"gm-bench-{contract}-final-preflight-v1"
            and payload.get("contract_fingerprint") == fingerprint
            and (payload.get("route_preflight") or {}).get("evidence_artifact") == route_relative
        ):
            existing = payload
    evidence = {
        "format": f"gm-bench-{contract}-final-preflight-v1",
        "schema_version": 1,
        "contract": contract,
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
    dry_run_key = "smoke_command_dry_run" if contract == "sota-v5" else "keychain_dry_run"
    if mode == "dry-run":
        evidence[dry_run_key] = {
            "status": "passed",
            "model_ids": model_ids,
            "commands_constructed": len(model_ids),
            "operator_ceiling_usd": max_spend_usd,
            "seed_panel_sha256": panel.get("sha256"),
            "hiding_commitment_verified": contract != "sota-v5",
            "private_seed_accessed": contract != "sota-v5",
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
        dry_run = existing.get(dry_run_key)
        if isinstance(dry_run, dict):
            evidence[dry_run_key] = dry_run
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, indent=2, sort_keys=True, allow_nan=False) + "\n")
    relative = str(path.resolve().relative_to(ROOT.resolve()))
    accepted = dry_run_key in evidence and "authenticated_route_and_price_preflight" in evidence
    if accepted:
        dry_run = evidence[dry_run_key]
        live_preflight = evidence["authenticated_route_and_price_preflight"]
        accepted = (
            isinstance(dry_run, dict)
            and dry_run.get("status") == "passed"
            and dry_run.get("model_ids") == model_ids
            and dry_run.get("operator_ceiling_usd") == max_spend_usd
            and dry_run.get("seed_panel_sha256") == panel.get("sha256")
            and dry_run.get("hiding_commitment_verified") is (contract != "sota-v5")
            and dry_run.get("private_seed_accessed") is (contract != "sota-v5")
            and dry_run.get("private_seed_values_included") is False
            and isinstance(live_preflight, dict)
            and live_preflight.get("status") == "passed"
            and live_preflight.get("model_ids") == model_ids
            and live_preflight.get("completion_calls") == 0
            and live_preflight.get("canonical_openrouter_api_base") == CANONICAL_OPENROUTER_API_BASE
            and live_preflight.get("pricing_checked") is True
        )
    lane["final_preflight_evidence"] = {
        "status": "accepted" if accepted else "pending",
        "artifact": relative,
        "sha256": canonical_sha256(evidence),
        "contract_fingerprint": fingerprint,
        "completion_calls": 0,
        "operator_ceiling_usd": max_spend_usd,
    }
    if accepted:
        from gm_bench.publication import v3_final_preflight_issues

        protocol = json.loads(_contract_path(contract, "protocol").read_text())
        validation_issues = v3_final_preflight_issues(
            lane,
            registry,
            protocol,
            contract=contract,
            repo_root=ROOT,
        )
        if validation_issues:
            lane["final_preflight_evidence"]["status"] = "pending"
            lane_path.write_text(json.dumps(lane, indent=2, allow_nan=False) + "\n")
            raise ValueError("recorded final readiness did not validate: " + "; ".join(validation_issues))
    lane_path.write_text(json.dumps(lane, indent=2, allow_nan=False) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", choices=SUPPORTED_CONTRACTS, default="sota-v3")
    parser.add_argument("--max-spend-usd", required=True, type=float)
    parser.add_argument("--run-dir")
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
    run_dir = args.run_dir or str(ROOT / "data" / "publication" / f"{args.contract}-smokes")
    if args.contract == "sota-v5":
        if PRIVATE_SEEDS_ENV in os.environ:
            raise ValueError(f"{PRIVATE_SEEDS_ENV} must be unset for seed-free sota-v5 smoke readiness")
        inherited_private_seeds = None
        private_seed_text = None
    else:
        inherited_private_seeds = os.environ.get(PRIVATE_SEEDS_ENV)
        private_seed_text = _verified_seed_text(args.contract)
    if private_seed_text is not None:
        os.environ[PRIVATE_SEEDS_ENV] = private_seed_text
    runner_args = [
        "smoke",
        "--contract",
        args.contract,
        "--run-dir",
        run_dir,
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
            _record_readiness(
                readiness_path,
                contract=args.contract,
                max_spend_usd=args.max_spend_usd,
                mode=mode,
            )
        return result
    finally:
        if args.contract != "sota-v5":
            if inherited_private_seeds is None:
                os.environ.pop(PRIVATE_SEEDS_ENV, None)
            else:
                os.environ[PRIVATE_SEEDS_ENV] = inherited_private_seeds


if __name__ == "__main__":
    raise SystemExit(main())
