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
  the seeds themselves;
- for a ``panel`` row only, embeds the spec's one supported inference: the
  predeclared ``reference`` contrast against ``pick-trader`` on the same
  seeds and seasons (``docs/bench_v2_spec.md``, Panel design). It is computed
  here, from the seeds in the raw ``run.json``, by the 1.0 runner's cached
  scripted-baseline machinery and its paired statistics, so the numbers are
  the ones a 1.0 run on those seeds would report. Like a redacted 1.0 row it
  keeps the aggregates and empties ``per_seed``: a per-seed lift plus the
  deterministic pick-trader score on that seed is the row's per-seed score. A
  ``smoke`` row gets no reference block.

:func:`validate_agentic_artifact` checks a committed artifact against the
contract this checkout computes and against those grade rules. A panel-grade
row must also be a run of the lane's frozen private panel: its
``panel.sha256`` and distinct-seed count must equal ``seed_panel`` in
``config/bench_v2_lane.json``. CI runs it on every file under
``results/agentic/``.
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
from gm_bench.runner import _paired_analysis, _precise_mean_score, run_many_cached_baselines

AGENTIC_PUBLICATION_FORMAT = "gm-bench-agentic-summary-v1"
RESULTS_DIR = Path("results") / "agentic"
LANE_CONFIG = Path("config") / "bench_v2_lane.json"
# The lane config is a checkout file, not package data: panel rows are only
# ever validated from a checkout (CI, the operator before committing).
_CHECKOUT_ROOT = Path(__file__).resolve().parents[2]
PANEL_MIN_SEEDS = 32
REDACTED_SEEDS = "<redacted>"
ISOLATION_LEVELS = ("same-user", "separate-user", "container")
_PANEL_ISOLATION = {"separate-user", "container"}
# The spec's predeclared contrast (config/bench_v2_lane.json
# panel_design.reference_agent) and a floor shown beside it. Both are
# deterministic scripted 1.0 baselines.
REFERENCE_AGENT = "pick-trader"
REFERENCE_FLOOR_AGENT = "random"
_REFERENCE_KEYS = (
    "agent",
    "mean_score",
    "floor",
    "seasons",
    "num_seeds",
    "paired_lift_mean",
    "paired_lift_stddev",
    "paired_lift_ci95",
    "sign_flip_p_value",
    "significant_at_95",
    "candidate_seed_win_rate",
    "per_seed",
)
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
    artifact: dict[str, Any] = {
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
    if grade == "panel":
        artifact["reference"] = reference_contrast(raw)
    return artifact


def reference_contrast(raw: dict[str, Any]) -> dict[str, Any]:
    """The predeclared ``pick-trader`` contrast on the raw run's own seeds and seasons.

    ``pick-trader`` and ``random`` are played by
    :func:`gm_bench.runner.run_many_cached_baselines` with the default episode
    config, exactly as ``gm-bench evaluate`` plays 1.0 baselines, so they hit
    the same baseline-cache entries and give the same scores a 1.0 run on these
    seeds reports. A 2.0 episode is scored by the same functions on the same
    simulator (``score_components`` and ``breakdown_from_components`` on
    ``League.new(seed)``), so the per-seed difference is like for like. The
    paired statistics are 1.0's :func:`gm_bench.runner._paired_analysis` with
    ``pick-trader`` as the only baseline: lifts are the row's per-seed score
    (mean over repeats) minus pick-trader's, over distinct seeds in first
    appearance order, so the seeded bootstrap and sign-flip draws repeat
    exactly on re-redaction. Nothing seed-level leaves this function:
    ``per_seed`` is emptied and no cache path or hit count is kept.
    """
    raw_episodes = raw.get("episodes") or []
    seasons = raw.get("seasons")
    if not _is_int(seasons) or seasons < 1:
        raise ValueError("the raw run has no positive integer seasons; cannot run the reference")
    if any(episode.get("seasons", seasons) != seasons for episode in raw_episodes):
        raise ValueError("raw run episodes disagree on seasons; cannot pair them with one reference run")
    candidate = {
        "episodes": [
            {"seed": int(episode["seed"]), "final_score": float(episode["final_score"])} for episode in raw_episodes
        ]
    }
    seeds = list(dict.fromkeys(episode["seed"] for episode in candidate["episodes"]))
    if not seeds:
        raise ValueError("the raw run has no episodes to pair with the reference")
    reference, _ = run_many_cached_baselines(REFERENCE_AGENT, seeds, seasons)
    floor, _ = run_many_cached_baselines(REFERENCE_FLOOR_AGENT, seeds, seasons)
    paired = _paired_analysis(seeds, candidate, [reference])
    return {
        "agent": REFERENCE_AGENT,
        "mean_score": paired["best_baseline"]["mean_score"],
        "floor": {"agent": REFERENCE_FLOOR_AGENT, "mean_score": round(_precise_mean_score(floor), 3)},
        "seasons": seasons,
        "num_seeds": paired["num_seeds"],
        "paired_lift_mean": paired["paired_lift_mean"],
        "paired_lift_stddev": paired["paired_lift_stddev"],
        "paired_lift_ci95": paired["paired_lift_ci95"],
        "sign_flip_p_value": paired["sign_flip_p_value"],
        "significant_at_95": paired["significant_at_95"],
        "candidate_seed_win_rate": paired["candidate_seed_win_rate"],
        # Withheld, as in a redacted 1.0 row: per-seed lifts on private seeds
        # invert to per-seed scores.
        "per_seed": [],
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


def load_lane_config(path: str | Path | None = None) -> dict[str, Any] | None:
    """The committed 2.0 lane config, or ``None`` when this is not a checkout."""
    lane_path = Path(path) if path is not None else _CHECKOUT_ROOT / LANE_CONFIG
    if not lane_path.is_file():
        return None
    payload = json.loads(lane_path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else None


def validate_agentic_artifact(
    artifact: dict[str, Any],
    *,
    checkout_contract: dict[str, Any] | None = None,
    raw_run: str | Path | None = None,
    lane: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Check a committed row: format, contract, grade rules, redaction, internal consistency.

    A ``panel`` row must also carry the lane's frozen private panel: its
    ``panel.sha256`` must equal ``seed_panel.artifact_panel_sha256`` in
    ``lane`` (default: this checkout's ``config/bench_v2_lane.json``) and its
    distinct-seed count must equal ``seed_panel.count``. Without a lane config
    a panel row fails closed. ``smoke`` rows are exempt.

    A ``panel`` row must carry the ``reference`` block (the predeclared
    ``pick-trader`` contrast) with ``num_seeds`` equal to its distinct seed
    groups and ``per_seed`` empty; a ``smoke`` row must not carry one.

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
        errors.extend(_lane_panel_errors(panel, distinct, lane if lane is not None else load_lane_config()))
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
    candidate_mean: float | None = None
    if episodes and not all(_is_finite_number(score) for score in scores):
        errors.append("every episode needs a finite final_score")
    elif groups_ok:
        by_group: dict[int, list[float]] = {}
        for group, score in zip(groups, scores, strict=True):
            by_group.setdefault(group, []).append(float(score))
        seed_means = [sum(values) / len(values) for values in by_group.values()]
        mean = candidate_mean = sum(seed_means) / len(seed_means)
        recorded_mean = (artifact.get("summary") or {}).get("mean_score")
        if not _is_finite_number(recorded_mean):
            errors.append("summary.mean_score must be a finite number")
        elif abs(mean - float(recorded_mean)) > 1e-3:
            errors.append(f"summary.mean_score {recorded_mean} does not match the per-seed episode mean {mean:.3f}")

    if grade == "smoke" and "reference" in artifact:
        errors.append("a smoke row carries no reference contrast (spec, Panel design); drop the reference block")
    elif grade == "panel":
        errors.extend(_reference_errors(artifact.get("reference"), distinct, artifact.get("seasons"), candidate_mean))

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


def _reference_errors(reference: Any, distinct: int, seasons: Any, candidate_mean: float | None) -> list[str]:
    """Shape and internal consistency of a panel row's ``pick-trader`` contrast.

    The numbers can only be recomputed from the raw run (``raw_run``); here
    they are checked for being on this row's panel, seed-free, and coherent.
    """
    if not isinstance(reference, dict):
        return [f"panel grade needs the reference block: the predeclared {REFERENCE_AGENT} contrast on the same seeds"]
    errors: list[str] = []
    keys = set(reference)
    if keys != set(_REFERENCE_KEYS):
        missing = sorted(set(_REFERENCE_KEYS) - keys)
        extra = sorted(keys - set(_REFERENCE_KEYS))
        errors.append(f"reference has missing keys {missing} and unexpected keys {extra}")
    if reference.get("agent") != REFERENCE_AGENT:
        errors.append(f"reference.agent must be {REFERENCE_AGENT!r}, the spec's predeclared contrast")
    floor = reference.get("floor")
    if not (
        isinstance(floor, dict)
        and set(floor) == {"agent", "mean_score"}
        and floor.get("agent") == REFERENCE_FLOOR_AGENT
        and _is_finite_number(floor.get("mean_score"))
    ):
        errors.append(f"reference.floor must be {{agent: {REFERENCE_FLOOR_AGENT!r}, mean_score: <number>}}")
    if reference.get("num_seeds") != distinct:
        errors.append(
            f"reference.num_seeds is {reference.get('num_seeds')!r} but the row has {distinct} distinct seeds; "
            "the reference must run on exactly the row's seeds"
        )
    if reference.get("seasons") != seasons:
        errors.append(f"reference.seasons is {reference.get('seasons')!r} but the row played {seasons!r} seasons")
    if reference.get("per_seed") != []:
        errors.append("reference.per_seed must be empty: per-seed lifts on private seeds invert to per-seed scores")
    for key in ("mean_score", "paired_lift_mean", "paired_lift_stddev", "candidate_seed_win_rate"):
        if not _is_finite_number(reference.get(key)):
            errors.append(f"reference.{key} must be a finite number")
    ci = reference.get("paired_lift_ci95")
    ci_ok = isinstance(ci, list) and len(ci) == 2 and all(_is_finite_number(bound) for bound in ci) and ci[0] <= ci[1]
    if not ci_ok:
        errors.append("reference.paired_lift_ci95 must be [low, high] with low <= high")
    p_value = reference.get("sign_flip_p_value")
    if not (_is_finite_number(p_value) and 0.0 <= p_value <= 1.0):
        errors.append("reference.sign_flip_p_value must be a number between 0 and 1")
    significant = reference.get("significant_at_95")
    if not isinstance(significant, bool):
        errors.append("reference.significant_at_95 must be a boolean")
    elif ci_ok and significant != (distinct >= 2 and (ci[0] > 0.0 or ci[1] < 0.0)):
        errors.append("reference.significant_at_95 contradicts reference.paired_lift_ci95")
    win_rate = reference.get("candidate_seed_win_rate")
    if _is_finite_number(win_rate) and not 0.0 <= win_rate <= 1.0:
        errors.append("reference.candidate_seed_win_rate must be between 0 and 1")
    lift = reference.get("paired_lift_mean")
    ref_mean = reference.get("mean_score")
    # With one baseline and every seed in both, the mean lift is the row's
    # per-seed mean minus the reference mean (each rounded to 3 places).
    if candidate_mean is not None and _is_finite_number(lift) and _is_finite_number(ref_mean):
        if abs(candidate_mean - ref_mean - lift) > 2e-3:
            errors.append(
                f"reference.paired_lift_mean {lift} is not the row mean {candidate_mean:.3f} "
                f"minus the {REFERENCE_AGENT} mean {ref_mean}"
            )
    return errors


def _lane_panel_errors(panel: dict[str, Any], distinct: int, lane: dict[str, Any] | None) -> list[str]:
    """A panel row is a run of the lane's frozen private panel, checked by digest and size only."""
    if lane is None:
        return [f"{LANE_CONFIG} not found; a panel-grade row can only be validated against the lane's frozen panel"]
    seed_panel = lane.get("seed_panel") or {}
    expected_sha = seed_panel.get("artifact_panel_sha256")
    expected_count = seed_panel.get("count")
    errors: list[str] = []
    if not _SHA256_RE.match(str(expected_sha or "")) or not _is_int(expected_count):
        return [f"{LANE_CONFIG} has no seed_panel.artifact_panel_sha256 and count to check a panel row against"]
    if panel.get("sha256") != expected_sha:
        errors.append(
            f"panel.sha256 is not the lane's frozen private panel ({LANE_CONFIG} seed_panel.artifact_panel_sha256)"
        )
    if distinct != expected_count:
        errors.append(
            f"panel grade has {distinct} distinct seeds; the lane's frozen private panel has {expected_count}"
        )
    reference_agent = (lane.get("panel_design") or {}).get("reference_agent", REFERENCE_AGENT)
    if reference_agent != REFERENCE_AGENT:
        errors.append(
            f"{LANE_CONFIG} panel_design.reference_agent is {reference_agent!r}; this checkout computes {REFERENCE_AGENT!r}"
        )
    return errors


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
