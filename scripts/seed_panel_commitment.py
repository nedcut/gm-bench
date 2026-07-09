#!/usr/bin/env python3
"""Salted commitments for GM-Bench seed panels.

The seed-panel SHA-256 in ``gm_bench/benchmark_config.py`` is an integrity check
for operators who already know a panel, not a secrecy mechanism: small integer
seed lists are brute-forceable straight from the digest. This tool upgrades that
to a real hiding commitment by hashing a fresh random salt together with the
canonical seed list, so a private panel can be announced (publish the
commitment) before it is used and revealed (publish salt + seeds) after it is
rotated out, with anyone able to verify the two match.

Canonical seed list: seeds are parsed (comma lists and ``a-b`` ranges accepted),
deduplicated, and sorted ascending, then joined with commas. Seed order and
input formatting therefore never change the commitment. The committed preimage
is ``"<salt>:<canonical>"`` encoded as UTF-8; ``salt`` is lowercase hex.

Usage:

    scripts/seed_panel_commitment.py commit --seeds 101,102,110-115 \\
        --salt-file panelQ3.seed-salt.json
    scripts/seed_panel_commitment.py verify --seeds 101,102,110-115 \\
        --salt <hex> --commitment <hex>
    scripts/seed_panel_commitment.py verify --salt-file panelQ3.seed-salt.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

_SALT_BYTES = 32


def parse_seeds(value: str) -> list[int]:
    """Parse ``"101,102,110-115"`` into a sorted, deduplicated seed list."""

    seeds: set[int] = set()
    for part in value.replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            head, tail = part.split("-", 1)
            start, end = int(head), int(tail)
            if start < 0 or end < start:
                raise ValueError(f"invalid seed range {part!r}")
            seeds.update(range(start, end + 1))
        else:
            seed = int(part)
            if seed < 0:
                raise ValueError(f"negative seeds are not supported: {part!r}")
            seeds.add(seed)
    if not seeds:
        raise ValueError("no seeds parsed")
    return sorted(seeds)


def canonical_seed_list(seeds: list[int]) -> str:
    return ",".join(str(seed) for seed in sorted(set(seeds)))


def commitment(salt: str, seeds: list[int]) -> str:
    """SHA-256 over the salted canonical seed list."""

    if not salt or any(char not in "0123456789abcdef" for char in salt):
        raise ValueError("salt must be lowercase hex")
    preimage = f"{salt}:{canonical_seed_list(seeds)}".encode()
    return hashlib.sha256(preimage).hexdigest()


def _commit(args: argparse.Namespace) -> int:
    seeds = parse_seeds(args.seeds)
    salt = secrets.token_hex(_SALT_BYTES)
    digest = commitment(salt, seeds)
    record = {
        "salt": salt,
        "commitment": digest,
        "seeds": canonical_seed_list(seeds),
        "count": len(seeds),
        "created_utc": datetime.now(timezone.utc).isoformat(),
    }
    if args.salt_file:
        path = Path(args.salt_file)
        if path.exists() and not args.force:
            sys.stderr.write(f"refusing to overwrite existing salt file {path} (pass --force)\n")
            return 1
        path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
        sys.stderr.write(
            f"wrote salt to {path}; keep it out of git and reveal it only when the panel rotates out\n"
        )
    print(f"commitment {digest}")
    print(f"count {len(seeds)}")
    if not args.salt_file:
        print(f"salt {salt}")
    return 0


def _verify(args: argparse.Namespace) -> int:
    salt = args.salt
    expected = args.commitment
    seeds_text = args.seeds
    if args.salt_file:
        record = json.loads(Path(args.salt_file).read_text())
        salt = salt or record.get("salt")
        expected = expected or record.get("commitment")
        seeds_text = seeds_text or record.get("seeds")
    if not salt or not expected or not seeds_text:
        sys.stderr.write("verify needs seeds, salt, and commitment (directly or via --salt-file)\n")
        return 2
    digest = commitment(salt, parse_seeds(seeds_text))
    if secrets.compare_digest(digest, expected):
        print(f"ok commitment matches {digest}")
        return 0
    sys.stderr.write(f"MISMATCH computed {digest} != expected {expected}\n")
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True)

    commit_parser = subparsers.add_parser("commit", help="commit to a seed panel with a fresh random salt")
    commit_parser.add_argument("--seeds", required=True, help="seed list, e.g. 101,102,110-115")
    commit_parser.add_argument("--salt-file", help="gitignored path to store {salt, commitment, seeds}")
    commit_parser.add_argument("--force", action="store_true", help="overwrite an existing salt file")
    commit_parser.set_defaults(func=_commit)

    verify_parser = subparsers.add_parser("verify", help="verify seeds + salt reproduce a commitment")
    verify_parser.add_argument("--seeds", help="seed list to check")
    verify_parser.add_argument("--salt", help="salt hex from the commit step")
    verify_parser.add_argument("--commitment", help="published commitment hex to match")
    verify_parser.add_argument("--salt-file", help="salt file written by commit; fills any missing field")
    verify_parser.set_defaults(func=_verify)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
