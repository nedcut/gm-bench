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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gm_bench.benchmark_config import PRIVATE_SEEDS_ENV, seed_panel_hash  # noqa: E402
from scripts.run_publication_matrix import main as publication_main  # noqa: E402
from scripts.seed_panel_commitment import commitment, parse_ordered_seeds  # noqa: E402

KEYCHAIN_ACCOUNT = "nedcutler"
KEYCHAIN_SERVICE = "gm-bench-sota-v3-private-panel"


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-spend-usd", required=True, type=float)
    parser.add_argument("--run-dir", default=str(ROOT / "data" / "publication" / "sota-v3-smokes"))
    parser.add_argument("--model-id")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args(argv)
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
        return publication_main(runner_args)
    finally:
        os.environ.pop(PRIVATE_SEEDS_ENV, None)


if __name__ == "__main__":
    raise SystemExit(main())
