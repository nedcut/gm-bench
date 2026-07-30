#!/usr/bin/env python3
"""Build a deterministic release archive for the frozen public panel."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gm_bench.benchmark_config import PRIVATE_LEADERBOARD_PANEL_NAME  # noqa: E402
from gm_bench.official import REDACTED_SEEDS_SENTINEL  # noqa: E402
from gm_bench.publication import canonical_sha256, publication_execution_issues  # noqa: E402

RELEASE_FORMAT = "gm-bench-publication-release-v1"
RELEASE_ID = "sota-v2-phase-one-2026-07-19"
RUN_METADATA_NAMES = ("run-state.json", "openrouter-reservations.json")
V3_PUBLIC_ANALYSIS_KEYS = frozenset(
    {
        "schema_version",
        "benchmark_version",
        "status",
        "primary_contrast",
        "registered_model_count",
        "eligible_model_count",
        "holm_family_size",
        "bootstrap",
        "sign_flip_inference",
        "config_errors",
        "missing_models",
        "rejected_artifacts",
        "models",
        "analysis_mode",
        "redaction",
        "publication_ready",
        "model_tiering",
    }
)
V3_PUBLIC_ANALYSIS_ROW_KEYS = frozenset(
    {
        "model_id",
        "provider",
        "model",
        "seed_count",
        "mean_lift",
        "bootstrap_ci95",
        "sign_flip_p_value",
        "seed_win_rate",
        "artifact_sha256",
        "raw_artifact_sha256",
        "holm_adjusted_p_value",
        "holm_reject_at_0_05",
    }
)


@dataclass(frozen=True)
class ReleaseSpec:
    contract: str
    registry_path: Path
    config_paths: tuple[Path, ...]
    analysis_path: Path
    default_release_id: str | None = None
    default_release_date: str | None = None


RELEASE_SPECS = {
    "sota-v2": ReleaseSpec(
        contract="sota-v2",
        registry_path=Path("config/sota_v2_models.json"),
        config_paths=(
            Path("config/sota_v2_models.json"),
            Path("config/sota_v2_lane.json"),
            Path("config/publication_protocol.json"),
            Path("config/sota_v2_smoke_manifest.json"),
        ),
        analysis_path=Path("results/analysis/publication-panel-analysis.json"),
        default_release_id=RELEASE_ID,
        default_release_date="2026-07-19",
    ),
    "sota-v3": ReleaseSpec(
        contract="sota-v3",
        registry_path=Path("config/sota_v3_models.json"),
        config_paths=(
            Path("config/sota_v3_models.json"),
            Path("config/sota_v3_lane.json"),
            Path("config/sota_v3_publication_protocol.json"),
            Path("config/sota_v3_pricing_snapshot.json"),
            Path("config/sota_v3_smoke_manifest.json"),
        ),
        analysis_path=Path("results/analysis/publication-panel-analysis-v3.json"),
    ),
}


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


def _zip_timestamp(release_date: str) -> tuple[int, int, int, int, int, int]:
    parsed = date.fromisoformat(release_date)
    if parsed.year < 1980:
        raise ValueError("release date must be 1980 or later for deterministic ZIP metadata")
    return (parsed.year, parsed.month, parsed.day, 0, 0, 0)


def _zip_bytes(entries: dict[str, bytes], output: Path, *, timestamp: tuple[int, int, int, int, int, int]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(entries):
            info = zipfile.ZipInfo(name, timestamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, entries[name])


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _v3_analysis_rows(analysis: dict[str, Any], registered_ids: set[str]) -> dict[str, dict[str, Any]]:
    issues: list[str] = []
    unexpected_analysis_keys = sorted(set(analysis) - V3_PUBLIC_ANALYSIS_KEYS)
    if unexpected_analysis_keys:
        issues.append(f"analysis contains unexpected public fields: {unexpected_analysis_keys!r}")
    if analysis.get("benchmark_version") != "sota-v3":
        issues.append("benchmark_version must be exactly 'sota-v3'")
    if analysis.get("status") != "complete" or analysis.get("publication_ready") is not True:
        issues.append("analysis must be complete and publication_ready")
    if analysis.get("analysis_mode") != "reference-only":
        issues.append("analysis_mode must be reference-only")
    redaction = analysis.get("redaction")
    if not isinstance(redaction, dict) or redaction != {
        "private_seed_panel": True,
        "seed_identifiers_included": False,
        "per_seed_rows_included": False,
        "public_view": "aggregate-only",
    }:
        issues.append("analysis must declare the aggregate-only private-seed redaction")
    tiering = analysis.get("model_tiering")
    if not isinstance(tiering, dict) or tiering.get("status") != "not-supported":
        issues.append("model_tiering must be explicitly not-supported")
    for field in ("config_errors", "missing_models", "rejected_artifacts"):
        if analysis.get(field) != []:
            issues.append(f"{field} must be present and empty")
    expected_count = len(registered_ids)
    for field in ("registered_model_count", "eligible_model_count", "holm_family_size"):
        if analysis.get(field) != expected_count:
            issues.append(f"{field} must equal the registered model count")

    rows: dict[str, dict[str, Any]] = {}
    raw_rows = analysis.get("models")
    if not isinstance(raw_rows, list):
        issues.append("models must be a list")
        raw_rows = []
    for row in raw_rows:
        if not isinstance(row, dict):
            issues.append("every model analysis row must be an object")
            continue
        model_id = str(row.get("model_id") or "")
        if not model_id or model_id in rows:
            issues.append("model analysis rows must have unique non-empty model_id values")
            continue
        if "tier" in row:
            issues.append(f"reference-only model row {model_id!r} must not assign a tier")
        unexpected_row_keys = sorted(set(row) - V3_PUBLIC_ANALYSIS_ROW_KEYS)
        if unexpected_row_keys:
            issues.append(f"model row {model_id!r} contains unexpected public fields: {unexpected_row_keys!r}")
        if "per_seed" in row:
            issues.append(f"model row {model_id!r} must not contain private per_seed evidence")
        seed_count = row.get("seed_count")
        if not isinstance(seed_count, int) or isinstance(seed_count, bool) or seed_count < 2:
            issues.append(f"model row {model_id!r} must retain an aggregate seed_count")
        if not _is_sha256(row.get("raw_artifact_sha256")):
            issues.append(f"model row {model_id!r} must bind a raw_artifact_sha256")
        rows[model_id] = row
    if set(rows) != registered_ids:
        issues.append("analysis model rows must match the registered model family exactly")
    if issues:
        raise ValueError("sota-v3 release analysis is not publishable: " + "; ".join(dict.fromkeys(issues)))
    return rows


def _require_v3_release_authorized(
    lane: dict[str, Any],
    registry: dict[str, Any],
    protocol: dict[str, Any],
    pricing: dict[str, Any],
    manifest: dict[str, Any],
) -> None:
    """Require the full execution/evidence gate plus explicit release approval."""

    issues = publication_execution_issues(
        lane,
        registry,
        manifest,
        phase="panel",
        protocol=protocol,
        pricing=pricing,
    )
    output_budget_status = str(lane.get("output_budget_status") or "")
    if not output_budget_status.startswith("frozen"):
        issues.append("sota-v3 output-budget state is not frozen for publication")
    for label, payload in (
        ("lane", lane),
        ("model registry", registry),
        ("publication protocol", protocol),
        ("pricing snapshot", pricing),
    ):
        if payload.get("publication_authorized") is not True:
            issues.append(f"sota-v3 {label} publication_authorized is not true")
    if issues:
        raise ValueError("sota-v3 release is not authorized: " + "; ".join(dict.fromkeys(issues)))


def _require_public_v3_artifact(compact: dict[str, Any], model_id: str, raw_hash: str) -> None:
    redaction = compact.get("redaction")
    run_info = compact.get("run_info")
    seed_panel = run_info.get("seed_panel") if isinstance(run_info, dict) else None
    publication = compact.get("publication")
    issues: list[str] = []
    if not isinstance(redaction, dict) or redaction.get("applied") is not True:
        issues.append("redaction.applied must be true")
    if not isinstance(seed_panel, dict) or seed_panel.get("name") != PRIVATE_LEADERBOARD_PANEL_NAME:
        issues.append("run_info.seed_panel must identify the private panel")
    if compact.get("seeds") != REDACTED_SEEDS_SENTINEL:
        issues.append("top-level seeds must be redacted")
    candidate = compact.get("candidate")
    if not isinstance(candidate, dict) or candidate.get("episodes") != []:
        issues.append("candidate episode traces must be removed")
    if not isinstance(candidate, dict) or candidate.get("seeds") != REDACTED_SEEDS_SENTINEL:
        issues.append("candidate seeds must be redacted")
    baselines = compact.get("baselines")
    if not isinstance(baselines, list) or any(
        not isinstance(row, dict) or row.get("episodes") != [] for row in baselines
    ):
        issues.append("baseline episode traces must be removed")
    if not isinstance(baselines, list) or any(
        not isinstance(row, dict) or row.get("seeds") != REDACTED_SEEDS_SENTINEL for row in baselines
    ):
        issues.append("baseline seeds must be redacted")
    paired = compact.get("paired")
    if not isinstance(paired, dict) or paired.get("per_seed") != []:
        issues.append("paired per-seed traces must be removed")
    linked = publication.get("raw_artifact_sha256") if isinstance(publication, dict) else None
    if linked != raw_hash:
        issues.append("publication.raw_artifact_sha256 must match the analysis row")
    if issues:
        raise ValueError(f"public sota-v3 artifact for {model_id!r} is unsafe: " + "; ".join(issues))


def build_release(
    *,
    repo_root: Path,
    run_dir: Path,
    archive_path: Path,
    manifest_path: Path,
    checksums_path: Path,
    contract: str = "sota-v2",
    release_id: str | None = None,
    release_date: str | None = None,
) -> dict[str, Any]:
    try:
        spec = RELEASE_SPECS[contract]
    except KeyError as exc:
        raise ValueError(f"unsupported release contract {contract!r}") from exc
    resolved_release_date = release_date or spec.default_release_date
    if resolved_release_date is None:
        raise ValueError(f"{contract} release packaging requires an explicit release_date")
    resolved_release_id = release_id or spec.default_release_id or f"{contract}-publication-{resolved_release_date}"
    zip_timestamp = _zip_timestamp(resolved_release_date)
    registry = _read_json(repo_root / spec.registry_path)
    if registry.get("contract") != contract:
        raise ValueError(f"{spec.registry_path} declares contract {registry.get('contract')!r}, expected {contract!r}")
    analysis = _read_json(repo_root / spec.analysis_path)
    if contract == "sota-v2" and analysis.get("benchmark_version") not in (None, contract):
        raise ValueError(
            f"{spec.analysis_path} declares benchmark_version {analysis.get('benchmark_version')!r}, "
            f"expected {contract!r}"
        )
    cap = int(registry["output_token_cap"])
    registered = [row for row in registry.get("models") or [] if isinstance(row, dict)]
    registered_ids = {str(row.get("id")) for row in registered}
    if contract == "sota-v3":
        lane = _read_json(repo_root / "config/sota_v3_lane.json")
        protocol = _read_json(repo_root / "config/sota_v3_publication_protocol.json")
        pricing = _read_json(repo_root / "config/sota_v3_pricing_snapshot.json")
        smoke_manifest = _read_json(repo_root / "config/sota_v3_smoke_manifest.json")
        _require_v3_release_authorized(lane, registry, protocol, pricing, smoke_manifest)
        eligible = _v3_analysis_rows(analysis, registered_ids)
        rejected: dict[str, list[str]] = {}
    else:
        eligible = {str(row["model_id"]): row for row in analysis.get("models") or []}
        rejected = {
            str(row["model_id"]): [str(reason) for reason in row.get("reasons") or []]
            for row in analysis.get("rejected_artifacts") or []
        }
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

    for relative in spec.config_paths:
        add_file(repo_root / relative, relative.as_posix(), "frozen-config")
    add_file(repo_root / spec.analysis_path, spec.analysis_path.as_posix(), "panel-analysis")
    for name in RUN_METADATA_NAMES:
        source = run_dir / name
        if source.exists():
            add_file(source, f"run-metadata/{name}", "run-metadata")

    for model_spec in registered:
        model_id = str(model_spec["id"])
        status = "headline" if model_id in eligible else "diagnostic"
        compact_relative = (
            Path("results/leaderboard") / f"{model_id}.json"
            if status == "headline"
            else Path("results/diagnostics") / f"{model_id}.json"
        )
        compact_source = repo_root / compact_relative
        compact_raw_hash = None
        compact_path = None
        raw_path: Path | None = None
        raw_archive_name: str | None = None
        raw_bytes: bytes | None = None
        if contract == "sota-v3":
            compact = _read_json(compact_source)
            compact_raw_hash = str(eligible[model_id]["raw_artifact_sha256"])
            _require_public_v3_artifact(compact, model_id, compact_raw_hash)
            compact_path = compact_relative.as_posix()
            add_file(compact_source, compact_path, "redacted-headline-artifact")
            candidate = compact.get("candidate") or {}
            raw_canonical = compact_raw_hash
        else:
            raw_path = run_dir / "raw" / f"{model_id}--{cap}.json"
            raw_archive_name = f"raw/{raw_path.name}"
            raw_bytes = add_file(raw_path, raw_archive_name, "raw-public-trace")
            raw = json.loads(raw_bytes)
            raw_canonical = canonical_sha256(raw)
            if compact_source.exists():
                compact = _read_json(compact_source)
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
                "provider": model_spec.get("provider"),
                "model": model_spec.get("model"),
                "upstream_provider": model_spec.get("upstream_provider"),
                "status": status,
                "rejection_reasons": rejected.get(model_id, []),
                "raw_path": raw_archive_name,
                "raw_bytes": len(raw_bytes) if raw_bytes is not None else None,
                "raw_sha256": _sha256(raw_bytes) if raw_bytes is not None else None,
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
        "release_id": resolved_release_id,
        "release_date": resolved_release_date,
        "contract": registry.get("contract"),
        "output_token_cap": cap,
        "registered_models": len(registered),
        "eligible_headline_models": len(eligible),
        "diagnostic_models": len(rejected),
        "archive_name": archive_path.name,
        "files": sorted(files, key=lambda row: str(row["path"])),
        "artifacts": artifacts,
        "notes": [
            (
                "Raw public-panel artifacts are immutable evidence and hash-link to committed compact rows."
                if contract == "sota-v2"
                else "Private-panel raw artifacts and seeds are excluded; archived headline artifacts are validated redactions."
            ),
            "Raw operator diagnostics may contain machine-local cache paths; compact publication artifacts do not.",
            (
                "No ordinal model ranking is supported: all eligible rows occupy one overlapping uncertainty tier."
                if contract == "sota-v2"
                else "The predeclared sota-v3 analysis is reference-only; no model-to-model tiers are assigned."
            ),
        ],
    }
    manifest_bytes = _json_bytes(manifest)
    entries["manifest.json"] = manifest_bytes
    _zip_bytes(entries, archive_path, timestamp=zip_timestamp)
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
        v3_private_release = manifest.get("contract") == "sota-v3"
        if v3_private_release and any(name.startswith("raw/") for name in names):
            raise ValueError("sota-v3 release archives must not contain private raw artifacts")
        expected_names = {str(row["path"]) for row in manifest.get("files") or []} | {"manifest.json"}
        if set(names) != expected_names:
            raise ValueError("archive members do not exactly match the manifest")
        for row in manifest.get("files") or []:
            data = archive.read(str(row["path"]))
            if len(data) != row.get("bytes") or _sha256(data) != row.get("sha256"):
                raise ValueError(f"file checksum mismatch: {row.get('path')}")
        for artifact in manifest.get("artifacts") or []:
            raw_path = artifact.get("raw_path")
            if v3_private_release and raw_path:
                raise ValueError("sota-v3 release manifest must not reference a private raw artifact")
            if raw_path:
                raw = json.loads(archive.read(str(raw_path)))
                if canonical_sha256(raw) != artifact.get("raw_canonical_sha256"):
                    raise ValueError(f"canonical raw hash mismatch: {artifact.get('model_id')}")
            compact_path = artifact.get("compact_artifact")
            if v3_private_release and (not compact_path or str(compact_path) not in names):
                raise ValueError("sota-v3 release must archive every redacted headline artifact")
            if compact_path:
                if str(compact_path) in names:
                    compact = json.loads(archive.read(str(compact_path)))
                elif repo_root is not None:
                    compact = _read_json(repo_root / str(compact_path))
                else:
                    continue
                linked = (compact.get("publication") or {}).get("raw_artifact_sha256")
                if linked != artifact.get("raw_canonical_sha256"):
                    raise ValueError(f"committed compact link mismatch: {artifact.get('model_id')}")
                if v3_private_release:
                    _require_public_v3_artifact(
                        compact,
                        str(artifact.get("model_id") or ""),
                        str(artifact.get("raw_canonical_sha256") or ""),
                    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--checksums", type=Path)
    parser.add_argument("--contract", choices=sorted(RELEASE_SPECS), default="sota-v2")
    parser.add_argument("--release-id")
    parser.add_argument("--release-date", help="ISO release date; required for a new contract release")
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
        contract=args.contract,
        release_id=args.release_id,
        release_date=args.release_date,
    )
    print(
        f"wrote {args.archive} with {manifest['eligible_headline_models']} headline and "
        f"{manifest['diagnostic_models']} diagnostic model artifact(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
