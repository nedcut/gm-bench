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
- carries the run's ``driver`` block (``provenance.py``): the digest of the
  driver code that played it, the commit, and whether the driver files
  matched that commit. Runs recorded before the block existed have none;
- names its own grade. ``panel`` rows need at least :data:`PANEL_MIN_SEEDS`
  distinct seeds, redacted seeds, the harness isolated from the driver by
  user or container (``docs/bench_v2_spec.md``, sandbox section), and a
  driver that matched a commit for the whole run. Anything else is a
  ``smoke`` row and says so. Each episode carries a ``seed_group``
  (episodes of one seed share a group, numbered in first-appearance order)
  so the distinct-seed count and the per-seed mean can be checked without
  the seeds themselves;
- for a ``panel`` row only, embeds the spec's one supported inference: the
  predeclared ``reference`` contrast against ``pick-trader`` on the same
  seeds and seasons (``docs/bench_v2_spec.md``, Panel design). It is computed
  here, from the seeds in the raw ``run.json``, by the 1.0 runner's
  scripted-baseline machinery and its paired statistics, so the numbers are
  the ones a 1.0 run on those seeds would report. The baselines are played
  live, never read from or written to the local baseline cache: the cache has
  no integrity check, so ``--raw`` would otherwise only re-read whatever the
  first redaction (or a hand edit) left there, and its keys would put the
  private seeds on disk. Like a redacted 1.0 row it
  keeps the aggregates and empties ``per_seed``: a per-seed lift plus the
  deterministic pick-trader score on that seed is the row's per-seed score. A
  ``smoke`` row gets no reference block. A sign-flip p-value the Monte
  Carlo test cannot resolve (no draw as extreme, so the runner reports 0.0)
  is stored as its bound, ``1 / (draws + 1)``, flagged
  ``sign_flip_p_value_upper_bound``;
- re-derives, for a Claude Code row, each episode's API-equivalent cost from
  the retained ``claude-events.jsonl`` with this checkout's parser. The run
  recorded its cost when it played, so a parser fixed since then (the 1-hour
  cache-write match of 2026-09-28) would otherwise never reach the row. The
  re-derivation must reproduce the recorded token counts exactly; when its
  cost differs, the row carries the new figure with the recorded one beside
  it under ``api_equivalent_recomputed`` (and the driver digest that did the
  re-derivation), as the tool-call recount does;
- counts each episode's empty phases (``validate.EMPTY_PHASE_DEFINITION``)
  from its ledger, and states the reasoning effort the run asked for and
  what the harness reported (``effective_reasoning_effort``);
- refuses a run with an episode the provider ended
  (``validate.provider_ended``): its open phases were never played.

:func:`validate_agentic_artifact` checks a committed artifact against the
contract this checkout computes and against those grade rules. A panel-grade
row must also be a run of the lane's frozen private panel: its
``panel.sha256`` and distinct-seed count must equal ``seed_panel`` in
``config/bench_v2_lane.json``. Once the operator records the frozen panel's
``pick-trader`` and ``random`` means under ``reference_scores`` in that file,
a panel row's reference must carry exactly those means. CI runs it on every
file under ``results/agentic/``.
"""

from __future__ import annotations

import datetime as _dt
import json
import math
import re
from pathlib import Path
from typing import Any

from gm_bench.agentic import claude
from gm_bench.agentic.contract import agentic_contract
from gm_bench.agentic.opencode import TOKEN_SHAPE, _api_equivalent_summary, normalized_tokens
from gm_bench.agentic.provenance import driver_digest, provenance_problems, reproducible_driver
from gm_bench.agentic.validate import EMPTY_PHASE_DEFINITION, provider_ended, validate_run
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
# Present only when the sign-flip p-value is a bound (see ``reference_contrast``).
_REFERENCE_OPTIONAL_KEYS = ("sign_flip_p_value_upper_bound",)
# ``runner._sign_flip_p_value`` samples this many sign flips beyond 20 seeds (a 1.0
# contract source, so the constant is restated here, not imported).
SIGN_FLIP_DRAWS = 20000
SIGN_FLIP_EXACT_MAX_SEEDS = 20
SIGN_FLIP_P_BOUND = round(1 / (SIGN_FLIP_DRAWS + 1), 6)
_API_EQUIVALENT_KEYS = (
    "api_equivalent_cost_usd",
    "cost_basis",
    "billed_by_harness",
    "pricing_source",
    "long_context_requests_possible",
)
_API_SUMMARY_KEYS = (
    "api_equivalent_cost_usd",
    "api_equivalent_cost_episodes",
    "api_equivalent_long_context_possible",
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
    # The last invocation's exit code; absent from runs recorded before it.
    "final_exit_code",
    "timed_out",
    "wall_seconds",
    "nudges_used",
    "nudges_without_progress",
    "proxy_connections",
    "guard_kills",
    "provider_stalls",
    "provider_stall_wait_seconds",
    "silent_kills",
    "server_drained",
    "tool_call_agreement",
    # A subscription harness's usage windows as it last reported them (Codex),
    # and the plan; absent for OpenCode and for runs recorded before them.
    "quota_windows",
    "plan_type",
    # Pauses for a spent subscription window inside the episode, and the
    # reset time when the episode stopped because it was beyond the budget.
    "quota_pauses",
    "ended_by_quota",
    # Absent from runs recorded before the driver marked them (validate.provider_ended infers it).
    "ended_by_provider",
    "max_provider_wait_seconds",
    # What the harness reported about reasoning effort (absent before it was recorded).
    "reasoning_effort",
)
# Present on every nudge a driver records; the provider-stall keys only on runs
# recorded since the driver learned to retry provider stalls, and ``silent``
# only since it learned to stop a silent harness.
_NUDGE_KEYS = (
    "number",
    "season",
    "phase",
    "new_tool_calls",
    "phases_closed",
    "exit_code",
    "stall_retry",
    "backoff_seconds",
    "provider_stall",
    "quota_resume",
    "silent",
)
_USAGE_KEYS = (
    "input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "cached_input_tokens",
    "api_calls",
    "cost_usd",
    # The shared token shape (``opencode.TOKEN_SHAPE``). Rows recorded before it
    # carry none of these three and used each harness's own convention.
    "uncached_input_tokens",
    "cache_write_input_tokens",
    "token_shape",
)
_HARNESS_USAGE_KEYS = (
    "telemetry_reported",
    "compactions",
    "cache_write_tokens",
    "tool_events",
    "errors",
    # A harness that reports tokens but no cost (Codex): what those tokens would
    # cost at API list price, labelled as an estimate nobody was billed. Absent
    # from runs recorded before the estimate existed, and from OpenCode runs.
    "api_equivalent_cost_usd",
    "cost_basis",
    "billed_by_harness",
    "pricing_source",
    "long_context_requests_possible",
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
    from the driver, and it gates the grade. It may not be stronger than what
    the driver recorded in the run (:func:`recorded_isolation`): an operator
    can understate a container run as ``same-user``, never the reverse. Seeds
    stay in the artifact only when ``public_seeds`` is set, which is never
    true for a panel row.
    """
    if isolation not in ISOLATION_LEVELS:
        raise ValueError(f"isolation must be one of {ISOLATION_LEVELS}, not {isolation!r}")
    run_path = Path(run_path)
    if run_path.is_dir():
        run_path = run_path / "run.json"
    raw = json.loads(run_path.read_text(encoding="utf-8"))
    recorded = recorded_isolation(raw)
    if isolation not in (recorded, "same-user"):
        raise ValueError(f"the run records isolation {recorded!r}; refusing to publish it as {isolation!r}")
    validation = validate_run(run_path)
    seeds = [int(seed) for seed in raw.get("seeds") or []]
    raw_episodes = raw.get("episodes") or []
    for index, episode in enumerate(raw_episodes):
        ended = provider_ended(episode)
        if ended is not None:
            raise ValueError(
                f"episode {index} was ended by the provider ({ended.get('reason')}), not played to the end; "
                "its open phases were never played, so the run cannot be published: rerun it"
            )
    groups = seed_groups([episode.get("seed") for episode in raw_episodes])
    distinct = len(set(groups))
    panel_ready = distinct >= PANEL_MIN_SEEDS and isolation in _PANEL_ISOLATION and not public_seeds
    grade = "panel" if panel_ready and reproducible_driver(raw.get("driver")) else "smoke"
    stamp = (now or _dt.datetime.now(_dt.timezone.utc)).replace(microsecond=0).isoformat()
    episodes = [
        _compact_episode(index, episode, groups[index], public_seeds) for index, episode in enumerate(raw_episodes)
    ]
    for episode, report in zip(episodes, validation["per_episode"], strict=True):
        _publish_recount(episode, report)
        episode["empty_phases"] = report.get("empty_phases")
    if (raw.get("harness") or {}).get("name") == claude.HARNESS_NAME:
        for episode, raw_episode in zip(episodes, raw_episodes, strict=True):
            _recost_claude_episode(episode, raw_episode, run_path.parent)
    agentic_summary = _published_agentic_summary(raw.get("agentic_summary"), episodes)
    empty = [episode["empty_phases"] for episode in episodes]
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
        # Absent from runs recorded before the driver recorded itself.
        **({"driver": raw["driver"]} if "driver" in raw else {}),
        "panel": {
            "seed_count": len(seeds),
            "distinct_seeds": distinct,
            "seeds": seeds if public_seeds else REDACTED_SEEDS,
            "sha256": seed_panel_sha256(seeds),
        },
        "seasons": raw.get("seasons"),
        "phase_guard_seconds": raw.get("phase_guard_seconds"),
        "max_nudges": raw.get("max_nudges"),
        # Absent from runs recorded before the driver retried provider stalls.
        **{
            key: raw[key]
            for key in (
                "max_provider_stalls",
                "max_provider_stall_wait_seconds",
                "max_provider_wait_seconds",
                "silent_harness_seconds",
            )
            if key in raw
        },
        # Panel pauses for an exhausted subscription window (positions, never seeds).
        **{
            key: raw[key]
            for key in ("quota_pause_percent", "quota_pauses", "stopped_for_quota", "stopped_for_provider")
            if key in raw
        },
        "summary": raw.get("summary"),
        "agentic_summary": agentic_summary,
        "effective_reasoning_effort": effective_reasoning_effort(raw, run_path.parent),
        # Phases where the agent only read the status and ended the phase, over the whole row.
        "empty_phases": {
            "count": sum(empty) if all(isinstance(value, int) for value in empty) else None,
            "phases": sum(int(episode.get("decisions") or 0) for episode in episodes),
            "definition": EMPTY_PHASE_DEFINITION,
        },
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
    config, exactly as ``gm-bench evaluate`` plays 1.0 baselines, so they give
    the same scores a 1.0 run on these seeds reports. They run with the cache
    off (about 0.2 s per 5-season episode, deterministic), so ``--raw``
    recomputes them from the simulator instead of trusting a local file, and
    no private seed is written into a cache key. A 2.0 episode is scored by
    the same functions on the same simulator (``score_components`` and
    ``breakdown_from_components`` on ``League.new(seed)``), so the per-seed
    difference is like for like. The
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
    reference, _ = run_many_cached_baselines(REFERENCE_AGENT, seeds, seasons, use_cache=False)
    floor, _ = run_many_cached_baselines(REFERENCE_FLOOR_AGENT, seeds, seasons, use_cache=False)
    paired = _paired_analysis(seeds, candidate, [reference])
    p_value = paired["sign_flip_p_value"]
    # Beyond 20 seeds the runner samples SIGN_FLIP_DRAWS flips; with no draw as extreme it
    # reports 0.0, which is below what the test can resolve. Publish the bound instead.
    bounded = p_value == 0.0 and paired["num_seeds"] > SIGN_FLIP_EXACT_MAX_SEEDS
    return {
        "agent": REFERENCE_AGENT,
        "mean_score": paired["best_baseline"]["mean_score"],
        "floor": {"agent": REFERENCE_FLOOR_AGENT, "mean_score": round(_precise_mean_score(floor), 3)},
        "seasons": seasons,
        "num_seeds": paired["num_seeds"],
        "paired_lift_mean": paired["paired_lift_mean"],
        "paired_lift_stddev": paired["paired_lift_stddev"],
        "paired_lift_ci95": paired["paired_lift_ci95"],
        "sign_flip_p_value": SIGN_FLIP_P_BOUND if bounded else p_value,
        **({"sign_flip_p_value_upper_bound": True} if bounded else {}),
        "significant_at_95": paired["significant_at_95"],
        "candidate_seed_win_rate": paired["candidate_seed_win_rate"],
        # Withheld, as in a redacted 1.0 row: per-seed lifts on private seeds
        # invert to per-seed scores.
        "per_seed": [],
    }


def recorded_isolation(raw: dict[str, Any]) -> str:
    """The isolation the driver recorded for a run: the run's, if every episode agrees, else ``same-user``.

    A run written before the driver recorded isolation, or one whose episodes
    disagree with it, counts as ``same-user``, the weakest level.
    """
    level = raw.get("isolation")
    episodes = raw.get("episodes") or []
    if level not in ISOLATION_LEVELS or not episodes:
        return "same-user"
    if any((episode.get("harness_run") or {}).get("isolation") != level for episode in episodes):
        return "same-user"
    return str(level)


def seed_groups(seeds: list[Any]) -> list[int]:
    """Number each seed by first appearance: ``[11, 12, 11]`` -> ``[0, 1, 0]``."""
    order: dict[Any, int] = {}
    return [order.setdefault(seed, len(order)) for seed in seeds]


def _by_index(validation: dict[str, Any], key: str) -> list[str]:
    entries = list(validation[f"run_{key}"])
    for index, report in enumerate(validation["per_episode"]):
        entries.extend(f"episode {index}: {item}" for item in report[key])
    return entries


def _publish_recount(episode: dict[str, Any], report: dict[str, Any]) -> None:
    """Replace a recorded tool-call mismatch that the validator's recount resolved.

    The recount from the ledger and the event stream is the evidence; the
    driver's recorded figure is kept beside it as ``recorded`` so the row
    shows it was corrected.
    """
    harness_run = episode["harness_run"]
    recorded = harness_run.get("tool_call_agreement")
    if not report.get("tool_calls_recounted") or not isinstance(recorded, dict) or recorded.get("agree"):
        return
    harness_run["tool_call_agreement"] = {
        "agree": True,
        "harness": report["harness_tool_calls"],
        "ledger": report["replayed_tool_calls"],
        "recorded": recorded,
    }


def _recost_claude_episode(episode: dict[str, Any], raw_episode: dict[str, Any], run_dir: Path) -> None:
    """Re-derive a Claude episode's API-equivalent cost from its retained event stream.

    The token counts must come out exactly as recorded, or the stream is not
    the one the run parsed and nothing is published. A cost that differs from
    the recorded one replaces it, with the recorded fields kept under
    ``api_equivalent_recomputed.recorded``.
    """
    harness_run = raw_episode.get("harness_run") or {}
    recorded_path = harness_run.get("events_path")
    events = Path(str(recorded_path)) if recorded_path else None
    if events is not None and not events.is_absolute():
        events = run_dir / events
    if events is None or not events.is_file():
        raise ValueError(f"episode {episode['index']}: the Claude event stream is missing; cannot re-derive its cost")
    telemetry = claude.parse_claude_events(events.read_text(encoding="utf-8").splitlines())
    usage = raw_episode.get("usage") or {}
    tokens = normalized_tokens(telemetry)
    for key in ("input_tokens", "output_tokens", "cached_input_tokens", "cache_write_input_tokens"):
        if key in usage and usage[key] != tokens[key]:
            raise ValueError(
                f"episode {episode['index']}: re-parsing the Claude event stream gives {key} {tokens[key]}, "
                f"the run recorded {usage[key]}; refusing to re-derive its cost"
            )
    fresh = claude.api_equivalent_fields(telemetry)
    harness = episode["usage"]["harness"]
    recorded = {key: harness.get(key) for key in _API_EQUIVALENT_KEYS}
    if fresh == recorded:
        return
    harness.update(fresh)
    harness["api_equivalent_recomputed"] = {
        "from": "retained claude-events.jsonl",
        "driver_digest": driver_digest(),
        "recorded": recorded,
    }


def _published_agentic_summary(summary: Any, episodes: list[dict[str, Any]]) -> Any:
    """The run's ``agentic_summary`` with its API-equivalent fields taken from the published episodes.

    They differ from the recorded ones when an episode's cost was re-derived,
    or when the recorded flag read ``False`` for episodes that could not tell
    (the driver's summary before 2026-09-28); the recorded fields are kept
    under ``api_equivalent_recorded``.
    """
    if not isinstance(summary, dict) or not any(key in summary for key in _API_SUMMARY_KEYS):
        return summary
    fresh = _api_equivalent_summary(episodes)
    recorded = {key: summary.get(key) for key in _API_SUMMARY_KEYS}
    if not fresh or fresh == recorded:
        return summary
    return {**summary, **fresh, "api_equivalent_recorded": recorded}


def effective_reasoning_effort(raw: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    """The reasoning effort the run asked for, and what the harness itself reported.

    ``requested`` is the ``--variant`` the driver passed (``None``: nothing was
    passed and the harness used its default for the model). ``reported`` is
    the distinct efforts the harness reported across episodes (Codex's session
    rollout, recorded by the driver as ``harness_run.reasoning_effort``;
    Claude Code's ``system``/``init`` events), or ``None`` when no episode's
    evidence says, with ``note`` saying why.
    """
    harness = raw.get("harness") or {}
    name = harness.get("name")
    requested = harness.get("variant")
    episodes = raw.get("episodes") or []
    reported: set[str] = set()
    recorded = [(episode.get("harness_run") or {}).get("reasoning_effort") for episode in episodes]
    for record in recorded:
        if isinstance(record, dict):
            reported.update(str(value) for value in record.get("reported") or [])
    if name == claude.HARNESS_NAME and not any(isinstance(record, dict) for record in recorded):
        for episode in episodes:
            path = (episode.get("harness_run") or {}).get("events_path")
            events = run_dir / str(path) if path and not Path(str(path)).is_absolute() else Path(str(path or ""))
            if path and events.is_file():
                reported.update(claude.reported_efforts(events.read_text(encoding="utf-8").splitlines()))
    notes = {
        "codex": "codex exec --json reports no effort; the driver reads turn_context.effort from the session "
        "rollouts, and runs recorded before it did (2026-09-28) kept none",
        "claude": "Claude Code's stream-json init and result events carry no effort level",
        "opencode": "OpenCode's event stream reports no effort; requested is the --variant passed to it",
    }
    return {
        "requested": requested,
        "reported": sorted(reported) or None,
        "note": None if reported else notes.get(str(name), "the harness reports no effort"),
    }


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
    compact["usage"]["harness"] = {key: harness_usage.get(key) for key in _HARNESS_USAGE_KEYS if key in harness_usage}
    compact["harness_run"] = {key: harness_run.get(key) for key in _HARNESS_RUN_KEYS if key in harness_run}
    compact["harness_run"]["nudges"] = [
        {key: nudge.get(key) for key in _NUDGE_KEYS if key in nudge} for nudge in harness_run.get("nudges") or []
    ]
    return compact


def token_shape_problems(episode: dict[str, Any]) -> list[str]:
    """Inconsistencies in an episode's tokens under the shared shape; none for a row recorded before it.

    A row without ``usage.token_shape`` predates the shape (its OpenCode input
    excluded cached tokens and its output excluded reasoning) and is accepted
    as it is: its numbers are the old convention, not wrong.
    """
    usage = episode.get("usage") or {}
    if "token_shape" not in usage:
        return []
    if usage["token_shape"] != TOKEN_SHAPE:
        return [f"usage.token_shape is {usage['token_shape']!r}, expected {TOKEN_SHAPE!r}"]
    keys = ("input_tokens", "uncached_input_tokens", "cached_input_tokens", "cache_write_input_tokens")
    values = [usage.get(key) for key in (*keys, "output_tokens", "reasoning_tokens")]
    if not all(_is_int(value) and value >= 0 for value in values):
        return ["usage token counts must be non-negative integers"]
    problems = []
    total, uncached, cached, write, output, reasoning = values
    if total != uncached + cached + write:
        problems.append("usage.input_tokens is not uncached + cached + cache-write input tokens")
    if reasoning > output:
        problems.append("usage.reasoning_tokens exceeds output_tokens, which includes reasoning")
    return problems


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
    checkout_driver_digest: str | None = None,
) -> dict[str, Any]:
    """Check a committed row: format, contract, grade rules, redaction, internal consistency.

    A ``panel`` row must carry a ``driver`` block showing the driver files
    matched a commit for the whole run. A ``smoke`` row may lack the block
    (rows recorded before it existed). A row whose ``driver_digest`` differs
    from this checkout's (``checkout_driver_digest``, default computed here)
    gets a warning, not an error: checkouts move on with driver fixes, and
    the row still names the commit that played it.

    A ``panel`` row must also carry the lane's frozen private panel: its
    ``panel.sha256`` must equal ``seed_panel.artifact_panel_sha256`` in
    ``lane`` (default: this checkout's ``config/bench_v2_lane.json``) and its
    distinct-seed count must equal ``seed_panel.count``. Without a lane config
    a panel row fails closed. ``smoke`` rows are exempt.

    A ``panel`` row must carry the ``reference`` block (the predeclared
    ``pick-trader`` contrast) with ``num_seeds`` equal to its distinct seed
    groups and ``per_seed`` empty; a ``smoke`` row must not carry one. When
    the lane records ``reference_scores`` for the row's seasons, the block's
    ``pick-trader`` and ``random`` means must equal them.

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
    driver_errors, driver_warnings = _driver_findings(artifact, grade, checkout_driver_digest)
    errors.extend(driver_errors)
    warnings.extend(driver_warnings)

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
        errors.extend(f"episode {episode.get('index')}: {problem}" for problem in token_shape_problems(episode))
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
        pin_errors, pin_warnings = _reference_pin_errors(
            artifact.get("reference"), artifact.get("seasons"), lane if lane is not None else load_lane_config()
        )
        errors.extend(pin_errors)
        warnings.extend(pin_warnings)

    errors.extend(_derived_field_errors(artifact, episodes))

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


def _derived_field_errors(artifact: dict[str, Any], episodes: list[dict[str, Any]]) -> list[str]:
    """Consistency of what redaction derived: re-derived costs, the cost summary, empty phases.

    All are optional (rows written before them carry none). Only ``--raw``
    can recompute them; here they must at least agree with each other.
    """
    errors: list[str] = []
    for episode in episodes:
        harness = ((episode.get("usage") or {}).get("harness")) or {}
        recomputed = harness.get("api_equivalent_recomputed")
        if recomputed is not None and not (
            isinstance(recomputed, dict)
            and isinstance(recomputed.get("recorded"), dict)
            and re.fullmatch(r"[0-9a-f]{16}", str(recomputed.get("driver_digest") or ""))
        ):
            errors.append(
                f"episode {episode.get('index')}: usage.harness.api_equivalent_recomputed needs the recorded "
                "figures and the driver_digest that re-derived them"
            )
        empty = episode.get("empty_phases")
        if empty is not None and not (_is_int(empty) and 0 <= empty <= int(episode.get("decisions") or 0)):
            errors.append(f"episode {episode.get('index')}: empty_phases must be between 0 and its decisions")
    summary = artifact.get("agentic_summary") or {}
    if "api_equivalent_recorded" in summary:
        fresh = _api_equivalent_summary(episodes)
        if any(summary.get(key) != value for key, value in fresh.items()):
            errors.append("agentic_summary API-equivalent fields do not match the published episodes")
    empty_block = artifact.get("empty_phases")
    if empty_block is not None:
        counts = [episode.get("empty_phases") for episode in episodes]
        expected = sum(counts) if all(_is_int(count) for count in counts) else None
        if not isinstance(empty_block, dict) or empty_block.get("count") != expected:
            errors.append("empty_phases.count is not the sum of the episodes' empty_phases")
        elif empty_block.get("phases") != sum(int(episode.get("decisions") or 0) for episode in episodes):
            errors.append("empty_phases.phases is not the row's phase count")
    return errors


def _driver_findings(artifact: dict[str, Any], grade: Any, checkout_digest: str | None) -> tuple[list[str], list[str]]:
    """Errors and warnings about the row's record of the driver code that played it."""
    if "driver" not in artifact:
        if grade == "panel":
            return ["panel grade needs the driver block: which driver code played the row, and its commit"], []
        return [], [
            "row records no driver provenance (recorded before runs did); the driver code that played it is unknown"
        ]
    driver = artifact["driver"]
    errors = provenance_problems(driver)
    if errors:
        return errors, []
    if grade == "panel" and not reproducible_driver(driver):
        errors.append(
            "panel grade needs a driver that matched a commit for the whole run "
            "(driver.git_head set, driver.git_driver_clean true, driver.changed_during_run false)"
        )
    warnings: list[str] = []
    if not reproducible_driver(driver):
        warnings.append(
            "the driver files did not match a commit for the whole run; this row cannot be replayed from git"
        )
    current = checkout_digest if checkout_digest is not None else driver_digest()
    if driver["driver_digest"] != current:
        warnings.append(
            f"driver.driver_digest {driver['driver_digest']} differs from this checkout's {current}: "
            f"the row was played by the driver at commit {driver.get('git_head')}"
        )
    return errors, warnings


def _reference_errors(reference: Any, distinct: int, seasons: Any, candidate_mean: float | None) -> list[str]:
    """Shape and internal consistency of a panel row's ``pick-trader`` contrast.

    The numbers can only be recomputed from the raw run (``raw_run``); here
    they are checked for being on this row's panel, seed-free, and coherent.
    """
    if not isinstance(reference, dict):
        return [f"panel grade needs the reference block: the predeclared {REFERENCE_AGENT} contrast on the same seeds"]
    errors: list[str] = []
    keys = set(reference)
    if not set(_REFERENCE_KEYS) <= keys <= set(_REFERENCE_KEYS) | set(_REFERENCE_OPTIONAL_KEYS):
        missing = sorted(set(_REFERENCE_KEYS) - keys)
        extra = sorted(keys - set(_REFERENCE_KEYS) - set(_REFERENCE_OPTIONAL_KEYS))
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
    if "sign_flip_p_value_upper_bound" in reference and not (
        reference["sign_flip_p_value_upper_bound"] is True
        and p_value == SIGN_FLIP_P_BOUND
        and _is_int(distinct)
        and distinct > SIGN_FLIP_EXACT_MAX_SEEDS
    ):
        errors.append(
            "reference.sign_flip_p_value_upper_bound marks the Monte Carlo bound: it must be true, with "
            f"sign_flip_p_value {SIGN_FLIP_P_BOUND} on more than {SIGN_FLIP_EXACT_MAX_SEEDS} seeds"
        )
    elif p_value == 0.0 and _is_int(distinct) and distinct > SIGN_FLIP_EXACT_MAX_SEEDS:
        errors.append(
            f"reference.sign_flip_p_value 0.0 is below what {SIGN_FLIP_DRAWS} sign-flip draws resolve; "
            f"publish the bound {SIGN_FLIP_P_BOUND} with sign_flip_p_value_upper_bound"
        )
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
    stddev = reference.get("paired_lift_stddev")
    if _is_finite_number(stddev) and stddev < 0:
        errors.append("reference.paired_lift_stddev must not be negative")
    if _is_finite_number(lift):
        errors.extend(_reference_coherence_errors(lift, ci if ci_ok else None, stddev, win_rate, distinct))
    return errors


def _reference_coherence_errors(lift: float, ci: list[float] | None, stddev: Any, win_rate: Any, n: int) -> list[str]:
    """Relations the runner's paired statistics always satisfy, up to the 3-place rounding.

    The p-value is deliberately not tied to the interval: the exact sign-flip
    test and the bootstrap interval can honestly disagree near the boundary.
    """
    errors: list[str] = []
    slack = 1e-3
    if ci is not None:
        # A percentile bootstrap of the mean brackets the sample mean.
        if not ci[0] - slack <= lift <= ci[1] + slack:
            errors.append(f"reference.paired_lift_ci95 {ci} does not contain reference.paired_lift_mean {lift}")
        # Every bootstrap mean lies between the smallest and largest lift, and
        # no lift is further than stddev * sqrt(n) from the mean. So a zero
        # spread means a point interval at the mean.
        if _is_finite_number(stddev) and stddev >= 0 and n >= 1:
            reach = (stddev + 5e-4) * math.sqrt(n) + 2 * slack
            if lift - ci[0] > reach or ci[1] - lift > reach:
                errors.append(
                    f"reference.paired_lift_ci95 {ci} is wider than reference.paired_lift_stddev {stddev} allows"
                )
    # The win rate counts seeds whose lift is strictly positive.
    if not _is_finite_number(win_rate):
        return errors
    if win_rate == 0 and (lift > 0 or (ci is not None and ci[1] > 0)):
        errors.append("reference.candidate_seed_win_rate is 0 but the lift or its interval is positive")
    if win_rate == 1 and (lift < 0 or (ci is not None and ci[0] < 0)):
        errors.append("reference.candidate_seed_win_rate is 1 but the lift or its interval is negative")
    return errors


def _reference_pin_errors(reference: Any, seasons: Any, lane: dict[str, Any] | None) -> tuple[list[str], list[str]]:
    """``pick-trader`` and ``random`` are deterministic, so on the one frozen panel their means are constants.

    ``reference_scores`` in the lane config records them once (from the first
    panel row that passed ``agentic-validate --raw``). A recorded value pins
    every panel row at those seasons; an unrecorded one is a warning, and the
    site build then requires all panel rows at a season count to agree.
    """
    if lane is None or not isinstance(reference, dict):
        return [], []
    pins = lane.get("reference_scores")
    if not isinstance(pins, dict):
        return [], [f"{LANE_CONFIG} has no reference_scores block; the reference means are not pinned"]
    floor = reference.get("floor") if isinstance(reference.get("floor"), dict) else {}
    errors: list[str] = []
    warnings: list[str] = []
    pinned_seasons = pins.get("seasons")
    means = pins.get("mean_scores") or {}
    if seasons != pinned_seasons:
        return [], [f"{LANE_CONFIG} reference_scores covers {pinned_seasons!r} seasons, not {seasons!r}; not pinned"]
    for agent, value in (
        (REFERENCE_AGENT, reference.get("mean_score")),
        (REFERENCE_FLOOR_AGENT, floor.get("mean_score")),
    ):
        pinned = means.get(agent)
        if pinned is None:
            warnings.append(f"{LANE_CONFIG} reference_scores has no recorded {agent} mean; not pinned")
        elif not _is_finite_number(pinned):
            errors.append(f"{LANE_CONFIG} reference_scores.mean_scores.{agent} must be a number or null")
        elif not (_is_finite_number(value) and abs(float(value) - float(pinned)) <= 1e-6):
            errors.append(
                f"reference {agent} mean {value!r} is not the frozen panel's {pinned!r} "
                f"({LANE_CONFIG} reference_scores); every panel row shares it"
            )
    return errors, warnings


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
    try:
        fresh = compact_agentic_run(
            raw_path,
            isolation=str(artifact.get("isolation")),
            public_seeds=(artifact.get("panel") or {}).get("seeds") != REDACTED_SEEDS,
            now=stamp,
        )
    except ValueError as exc:
        return [str(exc)]
    # A re-derived cost names the driver that re-derived it; a later driver that reproduces
    # the same figures from the same stream is a match, not a difference.
    for mine, theirs in zip(fresh.get("episodes") or [], artifact.get("episodes") or [], strict=False):
        fresh_block = ((mine.get("usage") or {}).get("harness") or {}).get("api_equivalent_recomputed")
        kept_block = ((theirs.get("usage") or {}).get("harness") or {}).get("api_equivalent_recomputed")
        if isinstance(fresh_block, dict) and isinstance(kept_block, dict):
            fresh_block["driver_digest"] = kept_block.get("driver_digest")
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
