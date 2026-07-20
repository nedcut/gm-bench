#!/usr/bin/env python3
"""Build a deterministic release archive for the frozen public panel."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gm_bench.publication import canonical_sha256  # noqa: E402

RELEASE_FORMAT = "gm-bench-publication-release-v1"
RELEASE_ID = "sota-v2-phase-one-2026-07-19"
FIXED_ZIP_TIMESTAMP = (2026, 7, 19, 0, 0, 0)
CONFIG_PATHS = (
    Path("config/sota_v2_models.json"),
    Path("config/sota_v2_lane.json"),
    Path("config/publication_protocol.json"),
    Path("config/sota_v2_smoke_manifest.json"),
)
ANALYSIS_PATH = Path("results/analysis/publication-panel-analysis.json")
RUN_METADATA_NAMES = ("run-state.json", "openrouter-reservations.json")


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_record(path: str, data: bytes, role: str) -> dict[str, Any]:
    return {"path": path, "role": role, "bytes": len(data), "sha256": _sha256(data)}


def _zip_bytes(entries: dict[str, bytes], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(entries):
            info = zipfile.ZipInfo(name, FIXED_ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, entries[name])


def build_release(
    *,
    repo_root: Path,
    run_dir: Path,
    archive_path: Path,
    manifest_path: Path,
    checksums_path: Path,
) -> dict[str, Any]:
    registry = _read_json(repo_root / "config/sota_v2_models.json")
    analysis = _read_json(repo_root / ANALYSIS_PATH)
    cap = int(registry["output_token_cap"])
    eligible = {str(row["model_id"]): row for row in analysis.get("models") or []}
    rejected = {
        str(row["model_id"]): [str(reason) for reason in row.get("reasons") or []]
        for row in analysis.get("rejected_artifacts") or []
    }
    registered = [row for row in registry.get("models") or [] if isinstance(row, dict)]
    registered_ids = {str(row.get("id")) for row in registered}
    if set(eligible) | set(rejected) != registered_ids or set(eligible) & set(rejected):
        raise ValueError("analysis must classify every registered model exactly once")

    entries: dict[str, bytes] = {}
    files: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []

    def add_file(source: Path, archive_name: str, role: str) -> bytes:
        data = source.read_bytes()
        entries[archive_name] = data
        files.append(_file_record(archive_name, data, role))
        return data

    for relative in CONFIG_PATHS:
        add_file(repo_root / relative, relative.as_posix(), "frozen-config")
    add_file(repo_root / ANALYSIS_PATH, ANALYSIS_PATH.as_posix(), "panel-analysis")
    for name in RUN_METADATA_NAMES:
        source = run_dir / name
        if source.exists():
            add_file(source, f"run-metadata/{name}", "run-metadata")

    for spec in registered:
        model_id = str(spec["id"])
        raw_path = run_dir / "raw" / f"{model_id}--{cap}.json"
        archive_name = f"raw/{raw_path.name}"
        raw_bytes = add_file(raw_path, archive_name, "raw-public-trace")
        raw = json.loads(raw_bytes)
        raw_canonical = canonical_sha256(raw)
        status = "headline" if model_id in eligible else "diagnostic"
        compact_relative = (
            Path("results/leaderboard") / f"{model_id}.json"
            if status == "headline"
            else Path("results/diagnostics") / f"{model_id}.json"
        )
        compact_raw_hash = None
        compact_path = None
        if (repo_root / compact_relative).exists():
            compact = _read_json(repo_root / compact_relative)
            compact_raw_hash = str((compact.get("publication") or {}).get("raw_artifact_sha256") or "")
            if compact_raw_hash != raw_canonical:
                raise ValueError(f"compact artifact does not hash-link to raw evidence for {model_id}")
            compact_path = compact_relative.as_posix()

        candidate = raw.get("candidate") or {}
        summary = candidate.get("summary") or {}
        usage = summary.get("usage") or {}
        artifacts.append(
            {
                "model_id": model_id,
                "provider": spec.get("provider"),
                "model": spec.get("model"),
                "upstream_provider": spec.get("upstream_provider"),
                "status": status,
                "rejection_reasons": rejected.get(model_id, []),
                "raw_path": archive_name,
                "raw_bytes": len(raw_bytes),
                "raw_sha256": _sha256(raw_bytes),
                "raw_canonical_sha256": raw_canonical,
                "compact_artifact": compact_path,
                "compact_raw_artifact_sha256": compact_raw_hash,
                "decisions": summary.get("decisions"),
                "decisions_with_usage": usage.get("decisions_with_usage"),
                "cost_decisions": usage.get("cost_decisions"),
                "cost_usd": usage.get("cost_usd"),
                "mean_score": summary.get("mean_score"),
            }
        )

    manifest = {
        "format": RELEASE_FORMAT,
        "schema_version": 1,
        "release_id": RELEASE_ID,
        "release_date": "2026-07-19",
        "contract": registry.get("contract"),
        "output_token_cap": cap,
        "registered_models": len(registered),
        "eligible_headline_models": len(eligible),
        "diagnostic_models": len(rejected),
        "archive_name": archive_path.name,
        "files": sorted(files, key=lambda row: str(row["path"])),
        "artifacts": artifacts,
        "notes": [
            "Raw artifacts are immutable evidence and hash-link to committed compact rows where available.",
            "Raw operator diagnostics may contain machine-local cache paths; compact publication artifacts do not.",
            "No ordinal model ranking is supported: all eligible rows occupy one overlapping uncertainty tier.",
        ],
    }
    manifest_bytes = _json_bytes(manifest)
    entries["manifest.json"] = manifest_bytes
    _zip_bytes(entries, archive_path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_bytes(manifest_bytes)
    archive_sha = _sha256(archive_path.read_bytes())
    checksums_path.parent.mkdir(parents=True, exist_ok=True)
    checksums_path.write_text(f"{archive_sha}  {archive_path.name}\n")
    return manifest


def verify_archive(archive_path: Path, *, repo_root: Path | None = None) -> dict[str, Any]:
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or "manifest.json" not in names:
            raise ValueError("archive must contain one manifest and no duplicate paths")
        if any(Path(name).is_absolute() or ".." in Path(name).parts for name in names):
            raise ValueError("archive contains an unsafe path")
        manifest = json.loads(archive.read("manifest.json"))
        if manifest.get("format") != RELEASE_FORMAT:
            raise ValueError("unsupported release manifest format")
        expected_names = {str(row["path"]) for row in manifest.get("files") or []} | {"manifest.json"}
        if set(names) != expected_names:
            raise ValueError("archive members do not exactly match the manifest")
        for row in manifest.get("files") or []:
            data = archive.read(str(row["path"]))
            if len(data) != row.get("bytes") or _sha256(data) != row.get("sha256"):
                raise ValueError(f"file checksum mismatch: {row.get('path')}")
        for artifact in manifest.get("artifacts") or []:
            raw = json.loads(archive.read(str(artifact["raw_path"])))
            if canonical_sha256(raw) != artifact.get("raw_canonical_sha256"):
                raise ValueError(f"canonical raw hash mismatch: {artifact.get('model_id')}")
            compact_path = artifact.get("compact_artifact")
            if compact_path and repo_root is not None:
                compact = _read_json(repo_root / str(compact_path))
                linked = (compact.get("publication") or {}).get("raw_artifact_sha256")
                if linked != artifact.get("raw_canonical_sha256"):
                    raise ValueError(f"committed compact link mismatch: {artifact.get('model_id')}")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--checksums", type=Path)
    parser.add_argument("--verify", type=Path, help="verify an existing release archive instead of building")
    args = parser.parse_args()
    if args.verify:
        manifest = verify_archive(args.verify.resolve(), repo_root=ROOT)
        print(
            f"ok: {args.verify} contains {manifest['eligible_headline_models']} headline and "
            f"{manifest['diagnostic_models']} diagnostic model artifact(s)"
        )
        return 0
    if not all((args.run_dir, args.archive, args.manifest, args.checksums)):
        parser.error("build mode requires --run-dir, --archive, --manifest, and --checksums")
    manifest = build_release(
        repo_root=ROOT,
        run_dir=args.run_dir.resolve(),
        archive_path=args.archive.resolve(),
        manifest_path=args.manifest.resolve(),
        checksums_path=args.checksums.resolve(),
    )
    print(
        f"wrote {args.archive} with {manifest['eligible_headline_models']} headline and "
        f"{manifest['diagnostic_models']} diagnostic model artifact(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
