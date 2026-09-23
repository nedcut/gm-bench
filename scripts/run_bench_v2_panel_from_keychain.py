#!/usr/bin/env python3
"""Run a GM-Bench 2.0 (agentic) panel on the escrowed 32-seed private panel.

``config/bench_v2_lane.json`` commits to the panel by digest and names its
macOS Keychain escrow in ``seed_panel.secret_escrow``. This launcher reads that
escrow, checks the seeds against every committed digest (count, execution
hash, salted hiding commitment, the hash a published row carries, and that the
first 29 are the sota-v5 panel in its committed order), and then runs
``gm-bench agentic`` in this process with the seeds on its standard input
(``--seeds-stdin``). The seeds never reach a command line or an environment
variable, so ``ps`` on the host shows neither. Episode directories
(``episode-00`` ...) and progress lines name episodes by position, not seed,
and the harness gets ``/dev/null`` as stdin, so its open-file table (``lsof``)
names no seed either. The run directory still holds the seeds (every ledger
header does, as does each finished episode's ``result.json``), which is why a
panel-grade row also needs the harness isolated from the driver by user or
container; this launcher does not provide that.

Episodes run serially: the driver has no parallel mode, on purpose.

Arguments this launcher does not know are passed to ``gm-bench agentic``
unchanged, so driver options (``--harness``, ``--codex-auth-file``,
``--variant``, ``--phase-guard-seconds``, ``--max-provider-stalls``,
``--max-provider-stall-wait-seconds``, ``--binary``, ``--isolation``) work
here without a change to this file. ``--seeds`` and ``--json`` are refused: the first would
put seeds on a command line, the second would print them.

    python scripts/run_bench_v2_panel_from_keychain.py --verify-only
    python scripts/run_bench_v2_panel_from_keychain.py \\
        --model opencode/big-pickle --output /path/outside/the/checkout/run
"""

from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gm_bench.agentic.publication import seed_panel_sha256  # noqa: E402
from gm_bench.benchmark_config import PRIVATE_SEEDS_ENV, seed_panel_hash  # noqa: E402
from scripts.seed_panel_commitment import commitment, parse_ordered_seeds  # noqa: E402

LANE_PATH = Path("config") / "bench_v2_lane.json"
SHARED_LANE_PATH = Path("config") / "sota_v5_lane.json"
KEYCHAIN_ACCOUNT = "nedcutler"
KEYCHAIN_ESCROW_PREFIX = "macos-keychain:"
PANEL_SEASONS = 5
_REFUSED_PASSTHROUGH = ("--seeds", "--seeds-stdin", "--json")


def _load(path: Path) -> dict[str, Any]:
    return json.loads((ROOT / path).read_text())


def _lane() -> dict[str, Any]:
    return _load(LANE_PATH)


def _shared_lane() -> dict[str, Any]:
    return _load(SHARED_LANE_PATH)


def keychain_service(lane: dict[str, Any]) -> str:
    """Return the Keychain service the committed lane names for its private panel."""
    panel = lane.get("seed_panel") or {}
    if not isinstance(panel, dict):
        raise ValueError("committed bench-v2 lane has no seed_panel record")
    escrow = panel.get("secret_escrow")
    if not isinstance(escrow, str) or not escrow.startswith(KEYCHAIN_ESCROW_PREFIX):
        raise ValueError("committed bench-v2 seed panel does not name a macOS Keychain escrow")
    service = escrow[len(KEYCHAIN_ESCROW_PREFIX) :]
    if not service:
        raise ValueError("committed bench-v2 seed panel names an empty Keychain service")
    return service


def _keychain_record(service: str) -> dict[str, Any]:
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


def verify_seeds(seeds_text: str, salt: str, lane: dict[str, Any], shared_lane: dict[str, Any]) -> list[int]:
    """Check an ordered seed list against every digest the lane commits to."""
    panel = lane.get("seed_panel") or {}
    seeds = parse_ordered_seeds(seeds_text)
    if len(seeds) != panel.get("count") or seed_panel_hash(seeds) != panel.get("sha256"):
        raise ValueError("Keychain seed order does not match the committed execution hash")
    if commitment(salt, seeds) != panel.get("hiding_commitment_sha256"):
        raise ValueError("Keychain seed panel does not match the committed hiding commitment")
    if seed_panel_sha256(seeds) != panel.get("artifact_panel_sha256"):
        raise ValueError("Keychain seed panel does not match the committed artifact panel hash")
    lineage = panel.get("lineage") or {}
    shared = lineage.get("shared_prefix_count")
    shared_panel = shared_lane.get("seed_panel") or {}
    if (
        not isinstance(shared, int)
        or shared != shared_panel.get("count")
        or lineage.get("shared_prefix_sha256") != shared_panel.get("sha256")
        or seed_panel_hash(seeds[:shared]) != shared_panel.get("sha256")
    ):
        raise ValueError("the panel's shared prefix is not the committed sota-v5 panel in its committed order")
    return seeds


def verified_seed_text(lane: dict[str, Any], shared_lane: dict[str, Any], *, require_attestation: bool = True) -> str:
    """Return the escrowed seed list only if it reproduces every committed digest."""
    panel = lane.get("seed_panel") or {}
    if not isinstance(panel, dict) or panel.get("status") != "frozen" or panel.get("name") != "private-env":
        raise ValueError("committed bench-v2 lane does not declare a frozen private panel")
    if require_attestation and panel.get("owner_attestation_status") != "attested-before-seed-access":
        raise ValueError("bench-v2 private seed access requires the owner attestation in the lane")
    record = _keychain_record(keychain_service(lane))
    seeds_text = record.get("seeds")
    salt = record.get("salt")
    if not isinstance(seeds_text, str) or not isinstance(salt, str):
        raise ValueError("Keychain seed record is missing seeds or salt")
    verify_seeds(seeds_text, salt, lane, shared_lane)
    return seeds_text


def _require_fresh_output(output: Path) -> None:
    # The driver refuses a populated episode directory, but its error names the
    # directory, and the directory names the seed. Refuse before that point.
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError(f"{output} is not an empty directory; a panel run needs a fresh run directory")
    try:
        output.resolve().relative_to(ROOT.resolve())
    except ValueError:
        return
    raise ValueError(f"{output} is inside the checkout; keep private-seed run directories outside it")


def agentic_argv(args: argparse.Namespace, passthrough: list[str]) -> list[str]:
    """The in-process ``gm-bench`` argument list. Seeds are not part of it."""
    for arg in passthrough:
        if arg.split("=", 1)[0] in _REFUSED_PASSTHROUGH:
            raise ValueError(f"{arg} is not allowed here: the launcher owns the seed input and output format")
    return [
        "agentic",
        "--seeds-stdin",
        "--model",
        args.model,
        "--output",
        str(args.output),
        "--seasons",
        str(args.seasons),
        *passthrough,
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", help="model id as the harness names it")
    parser.add_argument("--output", type=Path, help="fresh run directory outside the checkout")
    parser.add_argument("--seasons", type=int, default=PANEL_SEASONS, help="must be 5, the frozen panel length")
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="check the escrow against the committed digests and print only the result",
    )
    args, passthrough = parser.parse_known_args(argv)
    if PRIVATE_SEEDS_ENV in os.environ:
        raise ValueError(f"{PRIVATE_SEEDS_ENV} must be unset; the panel takes its seeds only from the verified escrow")
    lane, shared_lane = _lane(), _shared_lane()
    if args.verify_only:
        seeds = parse_ordered_seeds(verified_seed_text(lane, shared_lane, require_attestation=False))
        print(json.dumps({"status": "escrow-matches-commitment", "count": len(seeds), "seed_values_included": False}))
        return 0
    if not args.model or args.output is None:
        parser.error("--model and --output are required unless --verify-only is given")
    if args.seasons != PANEL_SEASONS:
        parser.error(f"the frozen 2.0 panel is {PANEL_SEASONS} seasons")
    output = args.output if args.output.is_absolute() else Path.cwd() / args.output
    args.output = output
    _require_fresh_output(output)
    cli_argv = agentic_argv(args, passthrough)
    seeds_text = verified_seed_text(lane, shared_lane)

    from gm_bench import cli

    saved_stdin = sys.stdin
    sys.stdin = io.StringIO(seeds_text)
    try:
        cli.main(cli_argv)
    finally:
        sys.stdin = saved_stdin
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
