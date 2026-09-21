"""Publication artifacts for GM-Bench 2.0 rows.

A run directory written by ``gm-bench agentic`` is raw evidence: it holds the
seeds, every ledger, the harness event stream, and local paths. None of that
is committed. What is committed under ``results/agentic/`` is one compact
artifact per row, produced by :func:`compact_agentic_run`, which

- binds itself to the raw run by ``canonical_sha256`` of the run's
  ``run.json`` (the same binding the 1.0 lanes use), so an analysis can be
  checked against the operator-held raw file later;
- carries the 2.0 contract block, the harness identity, the panel size and
  a hash of the sorted seeds, per-episode scores and agentic telemetry, and
  the validation report computed at redaction time;
- drops ledgers, event streams, commands, and every local path;
- names its own grade. ``panel`` rows need at least :data:`PANEL_MIN_SEEDS`
  seeds, redacted seeds, and the harness isolated from the driver by user or
  container (``docs/bench_v2_spec.md``, sandbox section). Anything else is a
  ``smoke`` row and says so.

:func:`validate_agentic_artifact` checks a committed artifact against the
contract this checkout computes and against those grade rules. CI runs it on
every file under ``results/agentic/``.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
from pathlib import Path
from typing import Any

from gm_bench.agentic.contract import agentic_contract
from gm_bench.agentic.validate import validate_run
from gm_bench.publication import canonical_sha256

AGENTIC_PUBLICATION_FORMAT = "gm-bench-agentic-summary-v1"
RESULTS_DIR = Path("results") / "agentic"
PANEL_MIN_SEEDS = 32
REDACTED_SEEDS = "<redacted>"
ISOLATION_LEVELS = ("same-user", "separate-user", "container")
_PANEL_ISOLATION = {"separate-user", "container"}
_CONTRACT_KEYS = (
    "benchmark_version",
    "base_benchmark_version",
    "base_contract_fingerprint",
    "agentic_fingerprint",
    "tool_surface",
    "brief",
    "scoring_version",
    "scoring_scale_fingerprint",
    "simulator_version",
)
_LOCAL_PATH_RE = re.compile(r"(^|[\s\"'=:])(/Users/|/home/|/tmp/|/var/folders/|/private/|[A-Za-z]:\\)")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_EPISODE_SCALARS = (
    "final_score",
    "strategy_score",
    "wins",
    "championships",
    "decisions",
    "failed_decisions",
    "illegal_actions",
    "malformed_decisions",
    "protocol_penalty",
    "memo_writes",
)
_HARNESS_RUN_KEYS = (
    "exit_code",
    "timed_out",
    "wall_seconds",
    "nudges_used",
    "nudges_without_progress",
    "proxy_connections",
    "tool_call_agreement",
)
_USAGE_KEYS = (
    "input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "cached_input_tokens",
    "api_calls",
    "cost_usd",
)


def seed_panel_sha256(seeds: list[int]) -> str:
    return canonical_sha256({"seeds": sorted(int(seed) for seed in seeds)})


def compact_agentic_run(
    run_path: str | Path,
    *,
    isolation: str,
    public_seeds: bool = False,
    now: _dt.datetime | None = None,
) -> dict[str, Any]:
    """Build the committed artifact for one row from its run directory.

    ``isolation`` is the operator's statement of how the harness was separated
    from the driver; it cannot be measured from inside the run, so it is
    recorded verbatim and gates the grade. Seeds stay in the artifact only
    when ``public_seeds`` is set, which is never true for a panel row.
    """
    if isolation not in ISOLATION_LEVELS:
        raise ValueError(f"isolation must be one of {ISOLATION_LEVELS}, not {isolation!r}")
    run_path = Path(run_path)
    if run_path.is_dir():
        run_path = run_path / "run.json"
    raw = json.loads(run_path.read_text(encoding="utf-8"))
    validation = validate_run(run_path)
    seeds = [int(seed) for seed in raw.get("seeds") or []]
    grade = (
        "panel" if (len(seeds) >= PANEL_MIN_SEEDS and isolation in _PANEL_ISOLATION and not public_seeds) else "smoke"
    )
    stamp = (now or _dt.datetime.now(_dt.timezone.utc)).replace(microsecond=0).isoformat()
    episodes = [
        _compact_episode(index, episode, public_seeds) for index, episode in enumerate(raw.get("episodes") or [])
    ]
    return {
        "publication": {
            "format": AGENTIC_PUBLICATION_FORMAT,
            "raw_artifact_sha256": canonical_sha256(raw),
            "traces_included": False,
            "compacted_at_utc": stamp,
        },
        "lane": "agentic",
        "grade": grade,
        "isolation": isolation,
        "agent": raw.get("agent"),
        "harness": raw.get("harness"),
        "contract": raw.get("contract"),
        "panel": {
            "seed_count": len(seeds),
            "seeds": seeds if public_seeds else REDACTED_SEEDS,
            "sha256": seed_panel_sha256(seeds),
        },
        "seasons": raw.get("seasons"),
        "phase_guard_seconds": raw.get("phase_guard_seconds"),
        "max_nudges": raw.get("max_nudges"),
        "summary": raw.get("summary"),
        "agentic_summary": raw.get("agentic_summary"),
        "episodes": episodes,
        "validation": {
            "ok": validation["ok"],
            "problems": validation["problems"],
            "warnings": validation["warnings"],
            "audits": [report.get("audit") for report in validation["per_episode"]],
        },
    }


def _compact_episode(index: int, episode: dict[str, Any], public_seeds: bool) -> dict[str, Any]:
    usage = episode.get("usage") or {}
    harness_run = episode.get("harness_run") or {}
    compact: dict[str, Any] = {"index": index}
    if public_seeds:
        compact["seed"] = episode.get("seed")
    for key in _EPISODE_SCALARS:
        if key in episode:
            compact[key] = episode[key]
    compact["agentic"] = episode.get("agentic")
    compact["usage"] = {key: usage.get(key) for key in _USAGE_KEYS if key in usage}
    harness_usage = usage.get("harness") or {}
    compact["usage"]["harness"] = {
        key: harness_usage.get(key)
        for key in ("telemetry_reported", "compactions", "cache_write_tokens", "tool_events", "errors")
        if key in harness_usage
    }
    compact["harness_run"] = {key: harness_run.get(key) for key in _HARNESS_RUN_KEYS if key in harness_run}
    compact["harness_run"]["nudges"] = [
        {key: nudge.get(key) for key in ("number", "season", "phase", "new_tool_calls", "phases_closed", "exit_code")}
        for nudge in harness_run.get("nudges") or []
    ]
    return compact


def validate_agentic_artifact(
    artifact: dict[str, Any], *, checkout_contract: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Check a committed row: format, contract, grade rules, redaction, internal consistency."""
    errors: list[str] = []
    warnings: list[str] = []
    publication = artifact.get("publication") or {}
    if publication.get("format") != AGENTIC_PUBLICATION_FORMAT:
        errors.append(f"publication.format must be {AGENTIC_PUBLICATION_FORMAT!r}")
    if publication.get("traces_included") is not False:
        errors.append("publication.traces_included must be false")
    if not _SHA256_RE.match(str(publication.get("raw_artifact_sha256") or "")):
        errors.append("publication.raw_artifact_sha256 must be a 64-character lowercase hex digest")
    if artifact.get("lane") != "agentic":
        errors.append("lane must be 'agentic'")

    expected = checkout_contract if checkout_contract is not None else agentic_contract()
    recorded = artifact.get("contract") or {}
    for key in _CONTRACT_KEYS:
        if recorded.get(key) != expected.get(key):
            errors.append(f"contract.{key}: artifact has {recorded.get(key)!r}, checkout has {expected.get(key)!r}")

    harness = artifact.get("harness") or {}
    for key in ("name", "version", "model"):
        if not harness.get(key):
            errors.append(f"harness.{key} is missing; a row is model + harness + harness version")
    if not artifact.get("agent"):
        errors.append("agent id is missing")

    isolation = artifact.get("isolation")
    if isolation not in ISOLATION_LEVELS:
        errors.append(f"isolation must be one of {ISOLATION_LEVELS}")
    panel = artifact.get("panel") or {}
    seed_count = int(panel.get("seed_count") or 0)
    seeds = panel.get("seeds")
    redacted = seeds == REDACTED_SEEDS
    if not redacted and not (isinstance(seeds, list) and len(seeds) == seed_count):
        errors.append("panel.seeds must be the redaction sentinel or a list matching panel.seed_count")
    if not _SHA256_RE.match(str(panel.get("sha256") or "")):
        errors.append("panel.sha256 missing")
    elif not redacted and isinstance(seeds, list) and seed_panel_sha256(seeds) != panel["sha256"]:
        errors.append("panel.sha256 does not match panel.seeds")
    grade = artifact.get("grade")
    if grade == "panel":
        if seed_count < PANEL_MIN_SEEDS:
            errors.append(f"panel grade needs at least {PANEL_MIN_SEEDS} seeds, has {seed_count}")
        if isolation not in _PANEL_ISOLATION:
            errors.append("panel grade needs the harness isolated from the driver by user or container")
        if not redacted:
            errors.append("panel grade needs redacted seeds")
    elif grade != "smoke":
        errors.append("grade must be 'panel' or 'smoke'")

    episodes = artifact.get("episodes") or []
    if len(episodes) != seed_count:
        errors.append(f"{len(episodes)} episodes for {seed_count} seeds")
    if redacted and any("seed" in episode for episode in episodes):
        errors.append("episodes carry seeds in a seed-redacted artifact")
    for episode in episodes:
        for key in ("transactions", "season_summaries", "ledger", "events"):
            if key in episode:
                errors.append(f"episode {episode.get('index')} carries traces ({key})")
        agreement = (episode.get("harness_run") or {}).get("tool_call_agreement") or {}
        if not agreement.get("agree", False):
            errors.append(f"episode {episode.get('index')}: ledger and harness disagree on tool calls")
    if episodes:
        mean = sum(float(episode.get("final_score", 0.0)) for episode in episodes) / len(episodes)
        recorded_mean = float((artifact.get("summary") or {}).get("mean_score", float("nan")))
        if abs(mean - recorded_mean) > 1e-3:
            errors.append(f"summary.mean_score {recorded_mean} does not match episode mean {mean:.3f}")

    validation = artifact.get("validation") or {}
    if validation.get("ok") is not True:
        errors.append("validation.ok is not true; the raw run did not validate at redaction time")
    for warning in validation.get("warnings") or []:
        warnings.append(f"raw run warning: {warning}")

    text = json.dumps(artifact, ensure_ascii=False)
    if _LOCAL_PATH_RE.search(text):
        errors.append("artifact contains a local filesystem path")
    if len(text.encode()) >= 1_000_000:
        errors.append("artifact is 1 MB or larger")
    return {"ok": not errors, "errors": errors, "warnings": warnings, "grade": grade, "agent": artifact.get("agent")}


def is_agentic_artifact(payload: dict[str, Any]) -> bool:
    return (payload.get("publication") or {}).get("format") == AGENTIC_PUBLICATION_FORMAT
