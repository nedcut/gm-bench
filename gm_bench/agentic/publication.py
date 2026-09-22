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
  distinct seeds, redacted seeds, and the harness isolated from the driver by
  user or container (``docs/bench_v2_spec.md``, sandbox section). Anything
  else is a ``smoke`` row and says so. Each episode carries a ``seed_group``
  (episodes of one seed share a group, numbered in first-appearance order)
  so the distinct-seed count and the per-seed mean can be checked without
  the seeds themselves.

:func:`validate_agentic_artifact` checks a committed artifact against the
contract this checkout computes and against those grade rules. CI runs it on
every file under ``results/agentic/``.
"""

from __future__ import annotations

import datetime as _dt
import json
import math
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
    "guard_kills",
    "server_drained",
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
    raw_episodes = raw.get("episodes") or []
    groups = seed_groups([episode.get("seed") for episode in raw_episodes])
    distinct = len(set(groups))
    grade = "panel" if (distinct >= PANEL_MIN_SEEDS and isolation in _PANEL_ISOLATION and not public_seeds) else "smoke"
    stamp = (now or _dt.datetime.now(_dt.timezone.utc)).replace(microsecond=0).isoformat()
    episodes = [
        _compact_episode(index, episode, groups[index], public_seeds) for index, episode in enumerate(raw_episodes)
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
            "distinct_seeds": distinct,
            "seeds": seeds if public_seeds else REDACTED_SEEDS,
            "sha256": seed_panel_sha256(seeds),
        },
        "seasons": raw.get("seasons"),
        "phase_guard_seconds": raw.get("phase_guard_seconds"),
        "max_nudges": raw.get("max_nudges"),
        "summary": raw.get("summary"),
        "agentic_summary": raw.get("agentic_summary"),
        "episodes": episodes,
        # Rebuilt by episode index: the raw report labels entries with the
        # seed, which must not reach a redacted artifact.
        "validation": {
            "ok": validation["ok"],
            "problems": _by_index(validation, "problems"),
            "warnings": _by_index(validation, "warnings"),
            "audits": [report.get("audit") for report in validation["per_episode"]],
        },
    }


def seed_groups(seeds: list[Any]) -> list[int]:
    """Number each seed by first appearance: ``[11, 12, 11]`` -> ``[0, 1, 0]``."""
    order: dict[Any, int] = {}
    return [order.setdefault(seed, len(order)) for seed in seeds]


def _by_index(validation: dict[str, Any], key: str) -> list[str]:
    entries = list(validation[f"run_{key}"])
    for index, report in enumerate(validation["per_episode"]):
        entries.extend(f"episode {index}: {item}" for item in report[key])
    return entries


def _compact_episode(index: int, episode: dict[str, Any], group: int, public_seeds: bool) -> dict[str, Any]:
    usage = episode.get("usage") or {}
    harness_run = episode.get("harness_run") or {}
    compact: dict[str, Any] = {"index": index, "seed_group": group}
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
    artifact: dict[str, Any],
    *,
    checkout_contract: dict[str, Any] | None = None,
    raw_run: str | Path | None = None,
) -> dict[str, Any]:
    """Check a committed row: format, contract, grade rules, redaction, internal consistency.

    With ``raw_run`` (the operator-held run directory or ``run.json``) the
    artifact is also checked against its evidence: the SHA-256 binding must
    hold and the artifact must equal a fresh redaction of that run. That is
    the only check that can tell an honest panel row from a hand-edited one,
    so it is what an operator runs before committing a panel-grade row; CI
    cannot, because raw runs are never committed.
    """
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
    distinct = panel.get("distinct_seeds")
    if not _is_int(distinct) or not 0 < distinct <= seed_count:
        errors.append("panel.distinct_seeds must be an integer between 1 and panel.seed_count")
        distinct = 0
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
        if distinct < PANEL_MIN_SEEDS:
            errors.append(f"panel grade needs at least {PANEL_MIN_SEEDS} distinct seeds, has {distinct}")
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
    # Seed groups tie the episodes to the distinct-seed count and let the
    # mean be recomputed the way the runner computes it (mean of per-seed
    # means), which is the only way a repeated-seed run can be checked.
    groups = [episode.get("seed_group") for episode in episodes]
    scores = [episode.get("final_score") for episode in episodes]
    groups_ok = bool(episodes) and all(_is_int(group) and group >= 0 for group in groups)
    if episodes and not groups_ok:
        errors.append("every episode needs a non-negative integer seed_group")
    if groups_ok:
        if len(set(groups)) != distinct:
            errors.append(f"panel.distinct_seeds is {distinct} but the episodes form {len(set(groups))} seed groups")
        if not redacted and isinstance(seeds, list) and len(seeds) == len(episodes) and groups != seed_groups(seeds):
            errors.append("episode seed_group values do not follow panel.seeds")
    if episodes and not all(_is_finite_number(score) for score in scores):
        errors.append("every episode needs a finite final_score")
    elif groups_ok:
        by_group: dict[int, list[float]] = {}
        for group, score in zip(groups, scores, strict=True):
            by_group.setdefault(group, []).append(float(score))
        seed_means = [sum(values) / len(values) for values in by_group.values()]
        mean = sum(seed_means) / len(seed_means)
        recorded_mean = (artifact.get("summary") or {}).get("mean_score")
        if not _is_finite_number(recorded_mean):
            errors.append("summary.mean_score must be a finite number")
        elif abs(mean - float(recorded_mean)) > 1e-3:
            errors.append(f"summary.mean_score {recorded_mean} does not match the per-seed episode mean {mean:.3f}")

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
    if raw_run is not None and not errors:
        errors.extend(_check_against_raw_run(artifact, raw_run))
    return {"ok": not errors, "errors": errors, "warnings": warnings, "grade": grade, "agent": artifact.get("agent")}


def _check_against_raw_run(artifact: dict[str, Any], raw_run: str | Path) -> list[str]:
    raw_path = Path(raw_run)
    if raw_path.is_dir():
        raw_path = raw_path / "run.json"
    if not raw_path.is_file():
        return [f"raw run not found at {raw_path}"]
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    publication = artifact.get("publication") or {}
    if canonical_sha256(raw) != publication.get("raw_artifact_sha256"):
        return ["publication.raw_artifact_sha256 does not match the raw run.json"]
    try:
        stamp = _dt.datetime.fromisoformat(str(publication.get("compacted_at_utc")))
    except ValueError:
        return ["publication.compacted_at_utc is not a timestamp"]
    fresh = compact_agentic_run(
        raw_path,
        isolation=str(artifact.get("isolation")),
        public_seeds=(artifact.get("panel") or {}).get("seeds") != REDACTED_SEEDS,
        now=stamp,
    )
    if canonical_sha256(fresh) == canonical_sha256(artifact):
        return []
    differing = sorted(key for key in set(fresh) | set(artifact) if fresh.get(key) != artifact.get(key))
    return [f"artifact does not equal a fresh redaction of the raw run (differs in: {', '.join(differing)})"]


def is_agentic_artifact(payload: dict[str, Any]) -> bool:
    return (payload.get("publication") or {}).get("format") == AGENTIC_PUBLICATION_FORMAT


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
