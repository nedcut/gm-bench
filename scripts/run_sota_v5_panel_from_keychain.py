#!/usr/bin/env python3
"""Launch the authorized sota-v5 (v6) panel with the escrowed private seed panel.

The lane commits to a 29-seed private panel by salted digest and names its
macOS Keychain escrow in ``seed_panel.secret_escrow``. This launcher reads that
escrow, verifies the seed order against the committed execution hash and the
salted hiding commitment, and hands the seeds to the publication runner only
through the child environment. It never prints, logs, or writes a seed value.

Every runner gate still applies: the four ``panel_execution_authorized`` flags,
the accepted smoke manifest, the exact-route preflight, the explicit spend
ceiling at or under the committed operator ceiling, and the per-cell
reservation guard. A ``--dry-run`` constructs the sixteen commands without a
provider call but still needs the escrow, because the runner binds a panel run
to its frozen seeds before any cell exists.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gm_bench.benchmark_config import PRIVATE_SEEDS_ENV, seed_panel_hash  # noqa: E402
from scripts.run_publication_matrix import main as publication_main  # noqa: E402
from scripts.seed_panel_commitment import commitment, parse_ordered_seeds  # noqa: E402

CONTRACT = "sota-v5"
KEYCHAIN_ACCOUNT = "nedcutler"
KEYCHAIN_ESCROW_PREFIX = "macos-keychain:"
DEFAULT_RUN_DIR = ROOT / "data" / "publication" / "sota-v5-panel"


def _lane() -> dict[str, object]:
    return json.loads((ROOT / "config" / "sota_v5_lane.json").read_text())


def keychain_service(lane: dict[str, object]) -> str:
    """Return the Keychain service the committed lane names for its private panel."""
    panel = lane.get("seed_panel") or {}
    if not isinstance(panel, dict):
        raise ValueError("committed sota-v5 lane has no seed_panel record")
    escrow = panel.get("secret_escrow")
    if not isinstance(escrow, str) or not escrow.startswith(KEYCHAIN_ESCROW_PREFIX):
        raise ValueError("committed sota-v5 seed panel does not name a macOS Keychain escrow")
    service = escrow[len(KEYCHAIN_ESCROW_PREFIX) :]
    if not service:
        raise ValueError("committed sota-v5 seed panel names an empty Keychain service")
    return service


def _keychain_record(service: str) -> dict[str, object]:
    result = subprocess.run(  # noqa: S603 - fixed macOS Keychain command
        ["security", "find-generic-password", "-s", service, "-a", KEYCHAIN_ACCOUNT, "-w"],
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


def verified_seed_text(lane: dict[str, object]) -> str:
    """Return the escrowed seed list only if it reproduces both committed digests."""
    panel = lane.get("seed_panel") or {}
    if not isinstance(panel, dict) or panel.get("status") != "frozen" or panel.get("name") != "private-env":
        raise ValueError("committed sota-v5 lane does not declare a frozen private panel")
    if panel.get("owner_attestation_status") != "attested-before-seed-access":
        raise ValueError("sota-v5 private seed access requires the frozen owner attestation")
    record = _keychain_record(keychain_service(lane))
    seeds_text = record.get("seeds")
    salt = record.get("salt")
    if not isinstance(seeds_text, str) or not isinstance(salt, str):
        raise ValueError("Keychain seed record is missing seeds or salt")
    seeds = parse_ordered_seeds(seeds_text)
    if len(seeds) != panel.get("count") or seed_panel_hash(seeds) != panel.get("sha256"):
        raise ValueError("Keychain seed order does not match the committed execution hash")
    if commitment(salt, seeds) != panel.get("hiding_commitment_sha256"):
        raise ValueError("Keychain seed panel does not match the committed hiding commitment")
    return seeds_text


def _require_panel_run_dir(run_dir: Path) -> None:
    """Refuse a run directory that carries another phase's reservations or state.

    Smoke and panel cells share reservation keys, so a leftover smoke
    reservation would be counted as a consumed panel attempt. The rerun policy
    says earlier attempts do not carry forward; keep the panel in its own
    directory.
    """
    state_path = run_dir / "run-state.json"
    if not state_path.exists():
        return
    try:
        state = json.loads(state_path.read_text())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read existing run state in {run_dir}: {exc}") from exc
    phase = state.get("phase") if isinstance(state, dict) else None
    if phase != "panel":
        raise ValueError(
            f"{run_dir} already holds {phase or 'unknown'!r} run state; the panel needs its own run directory"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--max-spend-usd", required=True, type=float)
    parser.add_argument("--run-dir", default=str(DEFAULT_RUN_DIR))
    parser.add_argument("--model-id")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args(argv)
    if args.dry_run and args.preflight_only:
        parser.error("--dry-run and --preflight-only are mutually exclusive")
    if PRIVATE_SEEDS_ENV in os.environ:
        raise ValueError(f"{PRIVATE_SEEDS_ENV} must be unset; the panel takes its seeds only from the verified escrow")
    run_dir = Path(args.run_dir)
    if not run_dir.is_absolute():
        run_dir = ROOT / run_dir
    _require_panel_run_dir(run_dir)
    runner_args = [
        "panel",
        "--contract",
        CONTRACT,
        "--run-dir",
        str(run_dir),
        "--max-spend-usd",
        str(args.max_spend_usd),
    ]
    if args.model_id:
        runner_args.extend(["--model-id", args.model_id])
    if args.dry_run:
        runner_args.append("--dry-run")
    if args.preflight_only:
        runner_args.append("--preflight-only")
    os.environ[PRIVATE_SEEDS_ENV] = verified_seed_text(_lane())
    try:
        return publication_main(runner_args)
    finally:
        os.environ.pop(PRIVATE_SEEDS_ENV, None)


if __name__ == "__main__":
    raise SystemExit(main())
