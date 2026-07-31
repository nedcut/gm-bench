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
import os
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

_SALT_BYTES = 32
_PRIVATE_SEED_MIN = 1 << 32
_PRIVATE_SEED_MAX = (1 << 63) - 1
_GENERATION_METHOD = "uniform-rejection-sampling-secrets-randbelow-63bit-v1"
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from gm_bench.benchmark_config import PRESETS, PRIVATE_SEEDS_ENV, seed_panel_hash  # noqa: E402


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


def parse_ordered_seeds(value: str) -> list[int]:
    """Parse an execution panel without sorting or silently deduplicating it."""
    seeds: list[int] = []
    for part in value.replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            head, tail = part.split("-", 1)
            start, end = int(head), int(tail)
            if start < 0 or end < start:
                raise ValueError(f"invalid seed range {part!r}")
            seeds.extend(range(start, end + 1))
        else:
            seed = int(part)
            if seed < 0:
                raise ValueError(f"negative seeds are not supported: {part!r}")
            seeds.append(seed)
    if not seeds:
        raise ValueError("no seeds parsed")
    if len(set(seeds)) != len(seeds):
        raise ValueError("execution panel seeds must be unique")
    return seeds


def canonical_seed_list(seeds: list[int]) -> str:
    return ",".join(str(seed) for seed in sorted(set(seeds)))


def commitment(salt: str, seeds: list[int]) -> str:
    """SHA-256 over the salted canonical seed list."""

    if not salt or any(char not in "0123456789abcdef" for char in salt):
        raise ValueError("salt must be lowercase hex")
    preimage = f"{salt}:{canonical_seed_list(seeds)}".encode()
    return hashlib.sha256(preimage).hexdigest()


def generate_private_seeds(count: int) -> list[int]:
    """Return ordered unique seeds sampled uniformly from the private range."""

    if not isinstance(count, int) or isinstance(count, bool) or count < 2:
        raise ValueError("private seed count must be an integer >= 2")
    span = _PRIVATE_SEED_MAX - _PRIVATE_SEED_MIN + 1
    committed = {seed for preset in PRESETS.values() for seed in preset["seeds"]}
    seeds: list[int] = []
    seen: set[int] = set()
    while len(seeds) < count:
        seed = _PRIVATE_SEED_MIN + secrets.randbelow(span)
        if seed in committed or seed in seen:
            continue
        seeds.append(seed)
        seen.add(seed)
    return seeds


def _create_secret_file(path: Path, record: dict[str, object]) -> None:
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise FileExistsError(f"refusing to overwrite existing secret file {path}") from None
    with os.fdopen(descriptor, "w") as stream:
        stream.write(json.dumps(record, indent=2, sort_keys=True) + "\n")


def _require_external_secret_path(path: Path) -> None:
    resolved = path.resolve()
    if resolved.is_relative_to(_ROOT.resolve()):
        raise ValueError(
            f"refusing to write private seed material inside the repository: {path}; "
            "choose a recoverable encrypted escrow or secret-manager path outside the checkout"
        )


def _generate(args: argparse.Namespace) -> int:
    lane = json.loads(Path(args.lane).read_text())
    panel = lane.get("seed_panel") or {}
    count = panel.get("count")
    if not isinstance(count, int) or isinstance(count, bool):
        raise ValueError("lane seed_panel.count must be frozen before private seed generation")
    if panel.get("status") not in {"pending-authorized-generation", "generated-pending-commit"}:
        raise ValueError("lane seed panel is not awaiting authorized generation")
    seeds = generate_private_seeds(count)
    salt = secrets.token_hex(_SALT_BYTES)
    hiding_commitment = commitment(salt, seeds)
    ordered_hash = seed_panel_hash(seeds)
    record: dict[str, object] = {
        "format": "gm-bench-private-seed-secret-v1",
        "generation_method": _GENERATION_METHOD,
        "range": [_PRIVATE_SEED_MIN, _PRIVATE_SEED_MAX],
        "salt": salt,
        "hiding_commitment_sha256": hiding_commitment,
        "execution_sha256": ordered_hash,
        "seeds": ",".join(str(seed) for seed in seeds),
        "ordered": True,
        "count": count,
        "created_utc": datetime.now(timezone.utc).isoformat(),
    }
    secret_path = Path(args.secret_file)
    _require_external_secret_path(secret_path)
    _create_secret_file(secret_path, record)
    sys.stderr.write(
        f"wrote private seeds and salt to {secret_path} with mode 0600; "
        "move it into recoverable encrypted escrow or a secret manager before committing public metadata\n"
    )
    print(
        json.dumps(
            {
                "status": "generated-pending-commit",
                "generation_method": _GENERATION_METHOD,
                "count": count,
                "hiding_commitment_sha256": hiding_commitment,
                "sha256": ordered_hash,
                "seed_values_included": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _commit(args: argparse.Namespace) -> int:
    seeds_text = os.environ.get(PRIVATE_SEEDS_ENV) if args.seeds_env else args.seeds
    if not seeds_text:
        raise ValueError(f"{PRIVATE_SEEDS_ENV} is required with --seeds-env")
    seeds = parse_seeds(seeds_text)
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
        try:
            _require_external_secret_path(path)
            _create_secret_file(path, record)
        except FileExistsError as exc:
            sys.stderr.write(f"{exc}\n")
            return 1
        sys.stderr.write(
            f"wrote plaintext secret material to {path} with mode 0600; "
            "gitignore is not encryption—move it into recoverable encrypted escrow or a secret manager\n"
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


def _execution_hash(args: argparse.Namespace) -> int:
    """Print the unsalted ordered hash required by run metadata, never seeds."""
    raw = os.environ.get(PRIVATE_SEEDS_ENV)
    if not raw:
        raise ValueError(f"{PRIVATE_SEEDS_ENV} is required")
    seeds = parse_ordered_seeds(raw)
    lane = json.loads(Path(args.lane).read_text())
    expected = lane.get("seed_panel") or {}
    expected_count = expected.get("count")
    if expected.get("name") != "private-env" or not isinstance(expected_count, int):
        raise ValueError("lane does not declare a pending private seed panel")
    if len(seeds) != expected_count:
        raise ValueError(f"private panel must contain exactly {expected_count} ordered seeds")
    committed = {seed for preset in PRESETS.values() for seed in preset["seeds"]}
    if committed.intersection(seeds):
        raise ValueError("private panel must not overlap any committed preset seed")
    if any(seed < 1 << 32 or seed > (1 << 63) - 1 for seed in seeds):
        raise ValueError("private seeds must be high-entropy positive 63-bit integers (at least 2**32)")
    print(
        json.dumps(
            {
                "status": "execution-hash-ready",
                "name": "private-env",
                "count": len(seeds),
                "sha256": seed_panel_hash(seeds),
                "ordered": True,
                "seed_values_included": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate_parser = subparsers.add_parser(
        "generate",
        help="uniformly generate the lane's private panel and write it only to a new 0600 secret file",
    )
    generate_parser.add_argument(
        "--lane",
        default=str(_ROOT / "config" / "sota_v3_lane.json"),
        help="lane whose pending private seed count is authoritative",
    )
    generate_parser.add_argument(
        "--secret-file",
        required=True,
        help="new escrow-bound file outside the repository for seeds and salt",
    )
    generate_parser.set_defaults(func=_generate)

    commit_parser = subparsers.add_parser("commit", help="commit to a seed panel with a fresh random salt")
    commit_source = commit_parser.add_mutually_exclusive_group(required=True)
    commit_source.add_argument("--seeds", help="seed list, e.g. 101,102,110-115")
    commit_source.add_argument(
        "--seeds-env",
        action="store_true",
        help=f"read seeds from {PRIVATE_SEEDS_ENV} instead of a process argument",
    )
    commit_parser.add_argument(
        "--salt-file",
        help="new path for plaintext {salt, commitment, seeds}; created once with mode 0600 and never overwritten",
    )
    commit_parser.set_defaults(func=_commit)

    verify_parser = subparsers.add_parser("verify", help="verify seeds + salt reproduce a commitment")
    verify_parser.add_argument("--seeds", help="seed list to check")
    verify_parser.add_argument("--salt", help="salt hex from the commit step")
    verify_parser.add_argument("--commitment", help="published commitment hex to match")
    verify_parser.add_argument("--salt-file", help="salt file written by commit; fills any missing field")
    verify_parser.set_defaults(func=_verify)

    execution_parser = subparsers.add_parser(
        "execution-hash",
        help="read GM_BENCH_PRIVATE_SEEDS and print only the ordered unsalted run-identity hash",
    )
    execution_parser.add_argument(
        "--lane",
        default=str(_ROOT / "config" / "sota_v3_lane.json"),
        help="lane whose pending private seed count must match",
    )
    execution_parser.set_defaults(func=_execution_hash)
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
