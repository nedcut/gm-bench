#!/usr/bin/env python3
"""One-time draw of the GM-Bench 2.0 private seed panel (run 2026-09-22).

``docs/bench_v2_spec.md`` fixes the 2.0 panel at 32 private seeds: the 29-seed
sota-v5 private panel plus three new seeds drawn the same way and kept in the
same keychain. This script is the record of how that was done:

1. Read the sota-v5 escrow and verify it against ``config/sota_v5_lane.json``
   (count, execution hash, salted hiding commitment) with the v5 launcher's
   own check.
2. Draw three seeds with ``generate_private_seeds`` from
   ``scripts/seed_panel_commitment.py``, the generator that drew the v5 panel
   (``secrets.randbelow`` rejection sampling over ``[2**32, 2**63 - 1]``,
   preset seeds excluded), also excluding the 29 v5 seeds and every public
   seed the docs use (1 to 58 covers the dev, leaderboard, smoke, and 48-seed
   calibration panels; all sit far below ``2**32`` anyway).
3. Order the panel as the 29 v5 seeds in their committed order followed by
   the three new ones, draw a fresh 32-byte salt, and build a record with the
   same shape as the v5 escrow record.
4. Add it to the Keychain under the new service by feeding
   ``add-generic-password -X <hex>`` to ``security -i`` on standard input, so
   neither the seeds nor the salt appear on any command line. The item must
   not already exist; nothing is overwritten.
5. Read the item back, check it equals what was written, and print only the
   public digests for ``config/bench_v2_lane.json``.

No seed value or salt is printed, logged, or written to disk.
"""

from __future__ import annotations

import json
import secrets
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import scripts.run_sota_v5_panel_from_keychain as v5  # noqa: E402
from gm_bench.agentic.publication import seed_panel_sha256  # noqa: E402
from gm_bench.benchmark_config import seed_panel_hash  # noqa: E402
from scripts.run_bench_v2_panel_from_keychain import KEYCHAIN_ACCOUNT, _keychain_record  # noqa: E402
from scripts.seed_panel_commitment import (  # noqa: E402
    _GENERATION_METHOD,
    _PRIVATE_SEED_MAX,
    _PRIVATE_SEED_MIN,
    _SALT_BYTES,
    commitment,
    generate_private_seeds,
    parse_ordered_seeds,
)

SERVICE = "gm-bench-bench-v2-private-panel"
NEW_SEEDS = 3
PUBLIC_SEEDS = frozenset(range(1, 59))


def _service_exists(service: str) -> bool:
    result = subprocess.run(  # noqa: S603 - fixed macOS Keychain command
        ["security", "find-generic-password", "-s", service, "-a", KEYCHAIN_ACCOUNT],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _add_to_keychain(service: str, payload: str) -> None:
    command = f"add-generic-password -s {service} -a {KEYCHAIN_ACCOUNT} -X {payload.encode().hex()}\n"
    result = subprocess.run(  # noqa: S603 - fixed macOS Keychain command, secret on stdin only
        ["security", "-i"],
        input=command,
        capture_output=True,
        text=True,
    )
    # security -i may echo its input on error; report the status only.
    if result.returncode != 0 or result.stderr.strip():
        raise RuntimeError(f"security -i add-generic-password failed (exit {result.returncode})")


def main() -> int:
    if _service_exists(SERVICE):
        raise SystemExit(f"Keychain service {SERVICE} already exists; this draw runs once and never overwrites")
    v5_lane = v5._lane()
    v5_panel = v5_lane["seed_panel"]
    shared = parse_ordered_seeds(v5.verified_seed_text(v5_lane))
    new = generate_private_seeds(NEW_SEEDS, exclude=set(shared) | PUBLIC_SEEDS)
    seeds = shared + new
    if len(set(seeds)) != len(seeds) or set(seeds) & PUBLIC_SEEDS:
        raise SystemExit("drawn panel is not disjoint; nothing was written")
    salt = secrets.token_hex(_SALT_BYTES)
    created = datetime.now(timezone.utc).replace(microsecond=0)
    record = {
        "format": "gm-bench-private-seed-secret-v1",
        "generation_method": _GENERATION_METHOD,
        "range": [_PRIVATE_SEED_MIN, _PRIVATE_SEED_MAX],
        "salt": salt,
        "hiding_commitment_sha256": commitment(salt, seeds),
        "execution_sha256": seed_panel_hash(seeds),
        "seeds": ",".join(str(seed) for seed in seeds),
        "ordered": True,
        "count": len(seeds),
        "created_utc": created.isoformat(),
        "lineage": {
            "shared_prefix_count": len(shared),
            "shared_prefix_escrow": v5_panel["secret_escrow"],
            "shared_prefix_sha256": v5_panel["sha256"],
            "new_seed_count": len(new),
        },
    }
    _add_to_keychain(SERVICE, json.dumps(record, indent=2, sort_keys=True) + "\n")
    if _keychain_record(SERVICE) != record:
        raise SystemExit(f"Keychain item {SERVICE} does not read back as written; inspect it before any use")
    print(
        json.dumps(
            {
                "service": SERVICE,
                "count": len(seeds),
                "sha256": record["execution_sha256"],
                "artifact_panel_sha256": seed_panel_sha256(seeds),
                "hiding_commitment_sha256": record["hiding_commitment_sha256"],
                "shared_prefix_count": len(shared),
                "shared_prefix_sha256": seed_panel_hash(seeds[: len(shared)]),
                "generated_at_utc": created.isoformat().replace("+00:00", "Z"),
                "generation_method": _GENERATION_METHOD,
                "seed_values_included": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
