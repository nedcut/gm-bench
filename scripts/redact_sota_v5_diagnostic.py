"""Write a redacted diagnostic artifact for an ineligible sota-v5 panel row.

``gm-bench redact-result`` refuses to write when the publication policy fails,
and ineligible rows fail by definition (a failure rate over the gate, or an
aborted seed panel). It also only reads result payloads, while two of the
ineligible rows exist only as checkpoints. This script reuses the same
redaction helper, evaluates a checkpoint's completed episodes against the
cached baselines when no raw result exists, and stamps
``publication.source_checkpoint_sha256`` with the byte digest of the retained
checkpoint so the packager can bind the diagnostic to the frozen exclusion
register. It never writes under the run directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from gm_bench import __version__  # noqa: E402
from gm_bench.benchmark_config import PRESETS, seed_panel_hash  # noqa: E402
from gm_bench.model_runs import evaluate_resumable_candidate  # noqa: E402
from gm_bench.official import PRIVATE_LEADERBOARD_PANEL_NAME, SOTA_V5_POLICY, redact_leaderboard_payload  # noqa: E402
from gm_bench.publication import PUBLICATION_FORMAT, canonical_sha256, mechanic_breakdown  # noqa: E402
from gm_bench.runner import _episodes_payload  # noqa: E402

OUTPUT_BUDGET_CELL = "4096"


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


SEED_MESSAGE_SENTINEL = "seeds must match the registered private panel (seed lists redacted)"


def _scrub_seed_message(message: str) -> str:
    return SEED_MESSAGE_SENTINEL if message.startswith("seeds must be") else message


def _register_entry(register: dict[str, Any], model_id: str) -> dict[str, Any]:
    for entry in register.get("entries", []):
        if entry.get("id") == model_id:
            return entry
    raise SystemExit(f"{model_id} is not in the exclusion register")


def _run_info_from_checkpoint(checkpoint: dict[str, Any], *, recorded_at_utc: str) -> dict[str, Any]:
    """Mirror gm_bench.cli._run_info from the checkpoint's stored metadata and provenance."""
    metadata = checkpoint["metadata"]
    provenance = checkpoint["provenance"]
    registered_seeds = list(checkpoint["seeds"])
    info: dict[str, Any] = {
        "command": "model",
        "agent": checkpoint["agent"],
        "provider": metadata["provider"],
        "model": metadata["model"],
        "agent_timeout": metadata["agent_timeout"],
        "preset": "leaderboard",
        "gm_bench_version": __version__,
        "benchmark_contract": provenance["benchmark_contract"],
        "scaffold_fingerprint": provenance["scaffold_fingerprint"],
        "session": bool(metadata.get("session", False)),
        "seed_panel": {
            "name": PRIVATE_LEADERBOARD_PANEL_NAME,
            "count": len(registered_seeds),
            "sha256": seed_panel_hash(registered_seeds),
            "preset": "leaderboard",
        },
        "python_version": platform.python_version(),
        "timestamp_utc": recorded_at_utc,
    }
    for key in ("profile", "transport", "protocol_repair_attempts"):
        if key in metadata:
            info[key] = metadata[key]
    if "strict_fallback" in metadata:
        info["strict_fallback"] = bool(metadata["strict_fallback"])
    if metadata.get("provider_options"):
        info["provider_options"] = metadata["provider_options"]
    return info


def payload_from_checkpoint(checkpoint: dict[str, Any], *, recorded_at_utc: str) -> dict[str, Any]:
    """Turn an aborted checkpoint's completed episodes into a result-shaped payload."""
    repeats = int(checkpoint.get("repeats") or 1)
    seasons = int(checkpoint["seasons"])
    by_key = {(int(ep["seed"]), int(ep.get("repeat") or 1)): ep for ep in checkpoint["episodes"]}
    completed_seeds = [seed for seed in checkpoint["seeds"] if all((seed, r) in by_key for r in range(1, repeats + 1))]
    ordered = [by_key[(seed, r)] for seed in completed_seeds for r in range(1, repeats + 1)]
    candidate = _episodes_payload(checkpoint["agent"], completed_seeds, seasons, ordered)
    candidate["repeats"] = repeats
    payload = evaluate_resumable_candidate(candidate, list(PRESETS["leaderboard"]["baselines"]))
    payload["run_info"] = _run_info_from_checkpoint(checkpoint, recorded_at_utc=recorded_at_utc)
    return payload


def build_diagnostic(
    *,
    model_id: str,
    run_dir: Path,
    register: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    entry = _register_entry(register, model_id)
    checkpoint_path = run_dir / entry["evidence"]["checkpoint"]
    checkpoint_bytes = checkpoint_path.read_bytes()
    checkpoint_sha256 = hashlib.sha256(checkpoint_bytes).hexdigest()
    if checkpoint_sha256 != entry["evidence"]["checkpoint_sha256"]:
        raise SystemExit(f"{checkpoint_path} does not match the register digest for {model_id}")
    checkpoint = json.loads(checkpoint_bytes)

    raw_path = run_dir / "raw" / f"{model_id}--{OUTPUT_BUDGET_CELL}.json"
    if raw_path.exists():
        payload = json.loads(raw_path.read_text())
        source = {"kind": "raw-result", "path": f"raw/{raw_path.name}"}
    else:
        payload = payload_from_checkpoint(checkpoint, recorded_at_utc=entry["recorded_at_utc"])
        source = {"kind": "checkpoint-episodes", "path": entry["evidence"]["checkpoint"]}

    redacted, report = redact_leaderboard_payload(payload, policy=SOTA_V5_POLICY)
    if not redacted["redaction"]["applied"]:
        raise SystemExit(f"{model_id}: payload is not a private-panel result; refusing to write")
    # The seed-panel gate message quotes the expected and observed seed lists,
    # and the redaction helper stores the validation report inside the
    # artifact, so scrub it before the payload can leave this process.
    errors = [_scrub_seed_message(error) for error in report.errors]
    redacted["validation_reports"][report.policy]["errors"] = errors
    redacted["publication"] = {
        "format": PUBLICATION_FORMAT,
        "raw_artifact_sha256": canonical_sha256(payload),
        "source_checkpoint": entry["evidence"]["checkpoint"],
        "source_checkpoint_sha256": checkpoint_sha256,
        "traces_included": False,
        "mechanic_breakdown": mechanic_breakdown((payload.get("candidate") or {}).get("episodes", [])),
    }
    redacted["diagnostic"] = {
        "role": "ineligible-model-behavior",
        "exclusion_register": "config/sota_v5_panel_exclusions.json",
        "exclusion_status": entry["status"],
        "exclusion_rule": entry["rule"],
        "exclusion_reason": entry["reason"],
        "checkpoint_status": checkpoint.get("status"),
        "checkpoint_error": checkpoint.get("error"),
        "registered_seed_count": len(checkpoint["seeds"]),
        "completed_seed_count": len(checkpoint["completed"]),
        "decisions_completed": entry["decisions_completed"],
        "source": source,
    }
    return redacted, {"policy": report.policy, "ok": report.ok, "errors": errors}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("model_id")
    parser.add_argument("--run-dir", type=Path, default=REPO_ROOT / "data/publication/sota-v5-panel")
    parser.add_argument("--register", type=Path, default=REPO_ROOT / "config/sota_v5_panel_exclusions.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    register = json.loads(args.register.read_text())
    redacted, report = build_diagnostic(model_id=args.model_id, run_dir=args.run_dir, register=register)
    output = args.output.resolve()
    if args.run_dir.resolve() in output.parents:
        raise SystemExit("refusing to write inside the run directory")
    _write_json_atomic(output, redacted)
    print(f"wrote {output} (policy={report['policy']} ok={report['ok']}, {len(report['errors'])} expected gate errors)")
    for error in report["errors"]:
        print(f"  gate: {error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
