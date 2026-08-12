"""Official-result validation for GM-Bench leaderboard payloads."""

from __future__ import annotations

import copy
import math
import os
import re
from dataclasses import dataclass
from typing import Any

from gm_bench.benchmark_config import (
    CUSTOM_SEED_PANEL_NAME,
    PRESETS,
    PRIVATE_LEADERBOARD_PANEL_NAME,
    PRIVATE_SEEDS_ENV,
    PUBLIC_LEADERBOARD_PANEL_NAME,
    _parse_seeds,
    seed_panel_hash,
)
from gm_bench.contract import SOTA_V2_CONTRACT, SOTA_V3_CONTRACT, expected_contract, scaffold_fingerprint
from gm_bench.scoring import SCORE_COMPONENT_KEYS, SCORE_COMPONENT_METRICS, contribution_from_metric

PUBLIC_LEADERBOARD_POLICY_NAME = "public-leaderboard"
SOTA_V2_POLICY_NAME = "sota-v2"
SOTA_V3_POLICY_NAME = "sota-v3"
SOTA_V4_POLICY_NAME = "sota-v4"
OUTPUT_BUDGET_SWEEP_POLICY_NAME = "output-budget-sweep"
SOTA_V1_POLICY_NAME = "sota-v1"
ARCHIVE_V1_POLICY_NAME = "archive-v1"
STRICT_SOTA_POLICY_NAMES = {
    SOTA_V2_POLICY_NAME,
    SOTA_V3_POLICY_NAME,
    SOTA_V4_POLICY_NAME,
    OUTPUT_BUDGET_SWEEP_POLICY_NAME,
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
# Episode scalars are stored at 3 decimals and components at 6, so recombining
# the components can differ from the stored strategy score by half a milli-point.
_COMPONENT_TOLERANCE = 1e-3

SOTA_V1_CONTRACT = {
    "benchmark_version": "sota-v1",
    "action_protocol_version": "actions-v1",
    "scoring_version": "score-v1",
    "scoring_scale_fingerprint": "05a60ff4f691e734",
    "simulator_version": "sim-v1",
    "observation_version": "observation-v1",
    "contract_fingerprint": "cf2607e59dba0c7f",
}


@dataclass(frozen=True)
class ResultPolicy:
    name: str
    min_repeats: int
    min_seed_count: int
    max_decision_failure_rate: float
    require_full_usage: bool = True
    require_contract_provenance: bool = False
    require_seed_panel_provenance: bool = False
    require_scaffold_provenance: bool = False
    # Per-episode score components landed with sota-v3. Frozen v1/v2 evidence
    # predates the field and must keep validating without it, so the
    # requirement is opt-in per policy rather than a blanket episode rule.
    require_score_components: bool = False
    # Strict failure handling became the publication default with sota-v3. The
    # frozen v1/v2 rows were measured under the soft fallback and keep their
    # historical semantics, so this is opt-in per policy.
    require_strict_fallback: bool = False
    expected_contract: dict[str, Any] | None = None
    validate_current_scaffold: bool = True
    expected_scaffold_fingerprints: dict[str, str] | None = None
    # Failed queries (misfired scout/inspect lookups) carry no protocol penalty,
    # so a model can silently burn its decision budget on them -- the v1 scout
    # contract break did exactly that. Warn early, and let strict policies refuse
    # a row whose lookups fail more often than it makes decisions.
    warn_failed_query_rate: float = 0.25
    max_failed_query_rate: float | None = None


PUBLIC_LEADERBOARD_POLICY = ResultPolicy(
    name=PUBLIC_LEADERBOARD_POLICY_NAME,
    min_repeats=1,
    min_seed_count=1,
    max_decision_failure_rate=0.20,
)
SOTA_V2_POLICY = ResultPolicy(
    name=SOTA_V2_POLICY_NAME,
    min_repeats=3,
    min_seed_count=len(PRESETS["leaderboard"]["seeds"]),
    max_decision_failure_rate=0.02,
    require_contract_provenance=True,
    require_seed_panel_provenance=True,
    require_scaffold_provenance=True,
    expected_contract=SOTA_V2_CONTRACT,
    validate_current_scaffold=False,
    max_failed_query_rate=1.0,
)
SOTA_V3_POLICY = ResultPolicy(
    name=SOTA_V3_POLICY_NAME,
    # The frozen v3 estimand is one stochastic model trajectory on each of 15
    # independent private seeds. Model-sampling noise is part of the seed-level
    # outcome; the preregistered power model explicitly carries the historical
    # within-seed noise term instead of buying repeated trajectories per seed.
    min_repeats=1,
    # Generic v3 artifact validation retains the eight-seed floor; the
    # publication lane separately binds headline evidence to its frozen
    # 15-seed private panel identity.
    min_seed_count=len(PRESETS["leaderboard"]["seeds"]),
    max_decision_failure_rate=0.02,
    require_contract_provenance=True,
    require_seed_panel_provenance=True,
    require_scaffold_provenance=True,
    require_score_components=True,
    require_strict_fallback=True,
    expected_contract=SOTA_V3_CONTRACT,
    validate_current_scaffold=False,
    expected_scaffold_fingerprints={
        "anthropic": "0afbbdcaecfcb1d0",
        "claude": "4a92675327e27a4d",
        "codex": "f6b1c953c198f6bc",
        "cursor": "3bb877c241996ed7",
        "gemini": "5e700d3151254ed3",
        "ollama": "5a3778bf70bd341e",
        "openai": "8275269195e00191",
        "opencode": "815df462b40d1274",
        "openrouter": "2462b25854c1298b",
    },
    max_failed_query_rate=1.0,
)
SOTA_V4_POLICY = ResultPolicy(
    name=SOTA_V4_POLICY_NAME,
    min_repeats=1,
    min_seed_count=len(PRESETS["leaderboard"]["seeds"]),
    max_decision_failure_rate=0.02,
    require_contract_provenance=True,
    require_seed_panel_provenance=True,
    require_scaffold_provenance=True,
    require_score_components=True,
    require_strict_fallback=True,
    expected_contract=expected_contract(),
    max_failed_query_rate=1.0,
)
OUTPUT_BUDGET_SWEEP_POLICY = ResultPolicy(
    name=OUTPUT_BUDGET_SWEEP_POLICY_NAME,
    min_repeats=3,
    min_seed_count=len(PRESETS["leaderboard"]["seeds"]),
    # Failure rate is an outcome of deliberately constrained output cells. A
    # low cap that prevents a model from emitting usable JSON must remain in
    # the sweep rather than disappearing as an invalid or missing cell.
    max_decision_failure_rate=1.0,
    require_contract_provenance=True,
    require_seed_panel_provenance=True,
    require_scaffold_provenance=True,
    expected_contract=SOTA_V2_CONTRACT,
    validate_current_scaffold=False,
    max_failed_query_rate=1.0,
)
SOTA_V1_POLICY = ResultPolicy(
    name=SOTA_V1_POLICY_NAME,
    min_repeats=3,
    min_seed_count=len(PRESETS["leaderboard"]["seeds"]),
    max_decision_failure_rate=0.02,
    require_contract_provenance=True,
    require_seed_panel_provenance=True,
    expected_contract=SOTA_V1_CONTRACT,
    # Historical adapter scaffolds are no longer present in the source tree.
    validate_current_scaffold=False,
)
# Verifiability, not eligibility. `archive-v1` answers "is this a genuine v1
# artifact, produced under the frozen v1 contract on the declared seed panel?"
# -- deliberately not "was it good enough to rank?", which is what `sota-v1`
# answers. Conflating the two would force a choice between deleting real
# evidence and letting the archive drift off its contract: two archived rows
# (ollama-gemma4-e4b, ollama-qwen3-5-latest) shipped under the looser public
# bar and never cleared sota-v1's failure-rate gate. They are still authentic
# v1 artifacts, and the archive exists to preserve them, not to endorse them.
ARCHIVE_V1_POLICY = ResultPolicy(
    name=ARCHIVE_V1_POLICY_NAME,
    min_repeats=1,
    min_seed_count=1,
    max_decision_failure_rate=PUBLIC_LEADERBOARD_POLICY.max_decision_failure_rate,
    require_contract_provenance=True,
    require_seed_panel_provenance=True,
    expected_contract=SOTA_V1_CONTRACT,
    validate_current_scaffold=False,
)
POLICIES = {
    PUBLIC_LEADERBOARD_POLICY.name: PUBLIC_LEADERBOARD_POLICY,
    OUTPUT_BUDGET_SWEEP_POLICY.name: OUTPUT_BUDGET_SWEEP_POLICY,
    SOTA_V1_POLICY.name: SOTA_V1_POLICY,
    SOTA_V2_POLICY.name: SOTA_V2_POLICY,
    SOTA_V3_POLICY.name: SOTA_V3_POLICY,
    SOTA_V4_POLICY.name: SOTA_V4_POLICY,
    ARCHIVE_V1_POLICY.name: ARCHIVE_V1_POLICY,
}
REDACTED_SEEDS_SENTINEL = "<redacted>"


@dataclass(frozen=True)
class ValidationReport:
    policy: str
    errors: list[str]
    warnings: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy": self.policy,
            "ok": self.ok,
            "errors": self.errors,
            "warnings": self.warnings,
        }


def validate_leaderboard_payload(
    payload: dict[str, Any],
    *,
    policy: ResultPolicy = PUBLIC_LEADERBOARD_POLICY,
) -> ValidationReport:
    """Validate a saved ``gm-bench model --preset leaderboard --json`` payload.

    Errors mean the result should not be treated as satisfying the selected
    policy. Warnings are quality signals that should travel with the score but
    do not invalidate the result by themselves.

    Redacted private-panel artifacts are validated from the fields that survive
    redaction (contract, seed-panel commitment, repeats, usage, failure rate,
    baseline names, paired aggregates). Episode/seed lists are not required, and
    stored ``validation_reports`` are never trusted as proof of eligibility.
    """

    errors: list[str] = []
    warnings: list[str] = []
    leaderboard = PRESETS["leaderboard"]
    expected_baselines = list(leaderboard["baselines"])
    expected_seasons = int(leaderboard["seasons"])
    redacted_private = _redacted_private_artifact(payload)
    _validate_redaction_shape(errors, payload, redacted_private=redacted_private)

    expected_seeds: list[int] | None = list(leaderboard["seeds"])
    expected_seed_count = len(expected_seeds)

    run_info = _dict(payload.get("run_info"))
    if not run_info:
        errors.append("missing run_info provenance block")
    else:
        _expect_equal(errors, "run_info.command", run_info.get("command"), "model")
        _expect_equal(errors, "run_info.preset", run_info.get("preset"), "leaderboard")
        _expect_equal(errors, "run_info.profile", run_info.get("profile"), "compact")
        version = run_info.get("gm_bench_version")
        if not version or str(version).endswith("+unknown"):
            errors.append("run_info.gm_bench_version must be a resolved package version")
        if not run_info.get("provider"):
            errors.append("run_info.provider is required for official model results")
        if not run_info.get("model"):
            errors.append("run_info.model is required for official model results")
        _validate_contract_provenance(
            errors,
            warnings,
            run_info,
            require=policy.require_contract_provenance,
            expected=policy.expected_contract,
        )
        if policy.expected_scaffold_fingerprints is not None:
            _validate_scaffold_provenance(
                errors,
                warnings,
                run_info,
                require=policy.require_scaffold_provenance,
                policy_name=policy.name,
                expected_fingerprints=policy.expected_scaffold_fingerprints,
            )
        elif policy.validate_current_scaffold:
            _validate_scaffold_provenance(
                errors,
                warnings,
                run_info,
                require=policy.require_scaffold_provenance,
                policy_name=policy.name,
            )
        elif run_info.get("scaffold_fingerprint"):
            warnings.append("historical scaffold fingerprint retained but cannot be re-derived from current source")
        strict_sota_lane = policy.name in STRICT_SOTA_POLICY_NAMES
        if run_info.get("session"):
            if strict_sota_lane:
                errors.append(
                    f"{policy.name} rows must be fresh-spawn (memo-only memory); "
                    "session-condition rows are a separate lane and not comparable"
                )
            else:
                warnings.append(
                    "session-condition row: model retains full trajectory in context; "
                    "not comparable with fresh-spawn rows"
                )
        if strict_sota_lane:
            repair_attempts = run_info.get("protocol_repair_attempts")
            option_repair = (run_info.get("provider_options") or {}).get("GM_BENCH_PROTOCOL_REPAIR_ATTEMPTS")
            parsed_repairs: dict[str, int] = {}
            for label, raw in (("protocol_repair_attempts", repair_attempts), ("provider_options", option_repair)):
                if raw in (None, ""):
                    errors.append(f"run_info.{label} repair attempts are required for {policy.name}")
                    continue
                try:
                    parsed = int(raw)
                except (TypeError, ValueError):
                    errors.append(f"run_info.{label} repair attempts must be an integer")
                    continue
                if not 0 <= parsed <= 1:
                    errors.append(
                        f"{policy.name} repair attempts must be between zero and one; got {parsed} via {label}"
                    )
                    continue
                parsed_repairs[label] = parsed
            if len(parsed_repairs) == 2 and len(set(parsed_repairs.values())) != 1:
                errors.append("run_info protocol-repair provenance values must match")
        if policy.require_strict_fallback:
            _validate_strict_fallback(errors, run_info, policy_name=policy.name)
        expected_seeds, expected_seed_count = _resolve_expected_seeds(
            errors,
            warnings,
            run_info,
            payload_seeds=payload.get("seeds"),
            require=policy.require_seed_panel_provenance,
            redacted_private=redacted_private,
        )

    if redacted_private:
        if expected_seed_count < policy.min_seed_count:
            errors.append(
                f"run_info.seed_panel.count must be >= {policy.min_seed_count} for {policy.name}, "
                f"got {expected_seed_count}"
            )
    else:
        _expect_equal(errors, "seeds", payload.get("seeds"), expected_seeds)
        if len(_list(payload.get("seeds"))) < policy.min_seed_count:
            errors.append(f"seeds must contain at least {policy.min_seed_count} seed(s) for {policy.name}")
    _expect_equal(errors, "seasons", payload.get("seasons"), expected_seasons)

    baselines = [_dict(result) for result in _list(payload.get("baselines"))]
    baseline_names = [result.get("agent") for result in baselines]
    if policy.name in STRICT_SOTA_POLICY_NAMES:
        _expect_equal(errors, "baselines", baseline_names, expected_baselines)
    else:
        if not baseline_names:
            errors.append("baselines must contain at least one scripted reference")
        elif len(set(baseline_names)) != len(baseline_names):
            errors.append("baselines must not contain duplicate agent names")
        elif any(name not in expected_baselines for name in baseline_names):
            errors.append(f"baselines contain unknown agents; expected a subset of {expected_baselines!r}")
        elif baseline_names != expected_baselines:
            warnings.append("historical baseline panel differs from the current official panel")

    candidate = _dict(payload.get("candidate"))
    if not candidate:
        errors.append("missing candidate result block")
    else:
        repeats = int(candidate.get("repeats", 1) or 1)
        if repeats < policy.min_repeats:
            errors.append(f"candidate.repeats must be >= {policy.min_repeats} for {policy.name}")
        if redacted_private:
            _expect_redacted_run_block(errors, "candidate", candidate)
        elif expected_seeds is not None:
            _validate_episode_panel(
                errors,
                "candidate",
                candidate,
                expected_seeds,
                expected_seasons,
                repeats=repeats,
                require_score_components=policy.require_score_components,
            )
        summary = _dict(candidate.get("summary"))
        decisions = int(summary.get("decisions", 0) or 0)
        failure_rate = float(summary.get("decision_failure_rate", 0.0) or 0.0)
        if failure_rate > policy.max_decision_failure_rate:
            errors.append(
                "candidate decision_failure_rate "
                f"{failure_rate:.3f} exceeds {policy.max_decision_failure_rate:.3f} for {policy.name}"
            )
        if int(summary.get("illegal_actions", 0) or 0):
            warnings.append("candidate has illegal actions; score includes protocol penalties")
        if int(summary.get("failed_decisions", 0) or 0):
            warnings.append("candidate used adapter fallback/error output on at least one decision")
        failed_queries = int(summary.get("failed_queries", 0) or 0)
        if decisions:
            failed_query_rate = failed_queries / decisions
            detail = (
                f"candidate has {failed_queries} failed queries across {decisions} decisions "
                f"({failed_query_rate:.2f} per decision)"
            )
            if policy.max_failed_query_rate is not None and failed_query_rate > policy.max_failed_query_rate:
                errors.append(
                    f"{detail}, exceeding {policy.max_failed_query_rate:.2f} for {policy.name}; "
                    "the candidate is spending its decision budget on lookups that never resolve"
                )
            elif failed_query_rate > policy.warn_failed_query_rate:
                warnings.append(
                    f"{detail}; misfired scout/inspect lookups may indicate the model is not reading query errors"
                )
        usage = _dict(summary.get("usage"))
        if policy.require_full_usage and decisions:
            if int(usage.get("decisions_with_usage", 0) or 0) != decisions:
                errors.append("candidate usage must cover every decision point")
            if usage.get("cost_usd", "missing") == "missing":
                errors.append("candidate usage.cost_usd is required, use null only when pricing is unknown")
        if run_info.get("provider") == "openrouter":
            _validate_openrouter_route(
                errors,
                warnings,
                run_info,
                usage,
                strict=policy.name in STRICT_SOTA_POLICY_NAMES,
            )

    for baseline in baselines:
        name = baseline.get("agent", "unknown")
        if redacted_private:
            _expect_redacted_run_block(errors, f"baseline[{name}]", baseline)
        elif expected_seeds is not None:
            _validate_episode_panel(
                errors,
                f"baseline[{name}]",
                baseline,
                expected_seeds,
                expected_seasons,
                repeats=1,
                require_score_components=policy.require_score_components,
            )

    if isinstance(payload.get("publication"), dict) and not redacted_private:
        benchmark_version = _dict(run_info.get("benchmark_contract")).get("benchmark_version")
        _validate_compact_integrity(
            errors,
            payload,
            candidate,
            baselines,
            expected_seeds or [],
            allow_legacy_sign_flip_rounding=benchmark_version in {"sota-v1", "sota-v2"},
        )

    normalized = _dict(payload.get("normalized"))
    paired = _dict(payload.get("paired"))
    if not normalized:
        errors.append("missing normalized score block")
    else:
        for key in ("candidate_mean_score", "baseline_panel_mean_score", "score_lift"):
            if key not in normalized:
                errors.append(f"normalized.{key} is required")
    if not paired:
        errors.append("missing paired analysis block")
    else:
        if paired.get("num_seeds") != expected_seed_count:
            errors.append(f"paired.num_seeds must be {expected_seed_count}")
        if redacted_private and _list(paired.get("per_seed")):
            errors.append("redacted private artifacts must not include paired.per_seed rows")
        if "sign_flip_p_value" not in paired:
            errors.append("paired.sign_flip_p_value is required")
        best = _dict(paired.get("best_baseline"))
        if not best:
            errors.append("paired.best_baseline is required")
        elif best.get("agent") != "pick-trader":
            warnings.append(f"strongest baseline is {best.get('agent')!r}, expected pick-trader for v1 calibration")
        if paired.get("significant_at_95") is False:
            warnings.append("candidate lift is not significant at 95% against the baseline panel")
        if best and float(best.get("paired_lift_mean", 0.0) or 0.0) <= 0.0:
            warnings.append("candidate does not beat the strongest scripted baseline")

    return ValidationReport(policy=policy.name, errors=errors, warnings=warnings)


def _validate_openrouter_route(
    errors: list[str],
    warnings: list[str],
    run_info: dict[str, Any],
    usage: dict[str, Any],
    *,
    strict: bool,
) -> None:
    """Keep flexible gateway rows visible without treating them as canonical."""
    options = _dict(run_info.get("provider_options"))
    only = str(options.get("OPENROUTER_PROVIDER_ONLY", "")).strip()
    expected_upstream = str(options.get("OPENROUTER_EXPECTED_UPSTREAM_PROVIDER") or only).strip()
    expected_endpoint = str(options.get("OPENROUTER_EXPECTED_ENDPOINT_NAME", "")).strip()
    fallbacks = str(options.get("OPENROUTER_ALLOW_FALLBACKS", "")).lower()
    upstreams = [str(value) for value in _list(usage.get("upstream_providers")) if value]
    issues: list[str] = []
    if not only:
        issues.append("run_info.provider_options.OPENROUTER_PROVIDER_ONLY must pin an upstream provider")
    if not expected_endpoint:
        issues.append("run_info.provider_options.OPENROUTER_EXPECTED_ENDPOINT_NAME must pin an exact endpoint")
    if fallbacks not in {"false", "0", "no", "off"}:
        issues.append("run_info.provider_options.OPENROUTER_ALLOW_FALLBACKS must be false")
    if len(set(upstreams)) != 1:
        issues.append("candidate usage must report exactly one OpenRouter upstream provider")
    elif expected_upstream and upstreams[0].casefold() != expected_upstream.casefold():
        issues.append(
            "candidate usage upstream provider does not match "
            f"the registered route: requested {expected_upstream!r}, observed {upstreams[0]!r}"
        )
    if strict:
        errors.extend(issues)
    else:
        warnings.extend(f"price-routed OpenRouter diagnostic: {issue}" for issue in issues)


def redact_leaderboard_payload(
    payload: dict[str, Any],
    *,
    policy: ResultPolicy = SOTA_V4_POLICY,
) -> tuple[dict[str, Any], ValidationReport]:
    """Return a public-safe copy of a leaderboard payload.

    Private leaderboard results carry the exact seed list in the raw JSON so
    they can be locally reproduced and validated. This redacted artifact keeps
    aggregate scores, usage, provenance, and the seed-panel hash, but removes
    per-seed traces and episode/transaction detail that would reveal the held
    out panel. The seed-panel hash is an integrity commitment for operators who
    already know the panel; it is not a secrecy mechanism against brute force.
    """

    report = validate_leaderboard_payload(payload, policy=policy)
    redacted = copy.deepcopy(payload)
    run_info = _dict(redacted.get("run_info"))
    seed_panel = _dict(run_info.get("seed_panel"))
    is_private = seed_panel.get("name") == PRIVATE_LEADERBOARD_PANEL_NAME

    redacted.setdefault("validation_reports", {})[policy.name] = report.to_dict()
    redacted["redaction"] = {
        "applied": is_private,
        "seed_panel": seed_panel.get("name"),
        "removed": [],
    }
    if not is_private:
        return redacted, report

    _redact_seed_fields(redacted, redacted["redaction"]["removed"])
    for result_key in ("candidate",):
        _redact_run_block(_dict(redacted.get(result_key)), redacted["redaction"]["removed"])
    for baseline in _list(redacted.get("baselines")):
        _redact_run_block(_dict(baseline), redacted["redaction"]["removed"])
    paired = _dict(redacted.get("paired"))
    if "per_seed" in paired:
        paired["per_seed"] = []
        redacted["redaction"]["removed"].append("paired.per_seed")
    return redacted, report


def _redacted_private_artifact(payload: dict[str, Any]) -> bool:
    redaction = _dict(payload.get("redaction"))
    seed_panel = _dict(_dict(payload.get("run_info")).get("seed_panel"))
    return (
        redaction.get("applied") is True
        and seed_panel.get("name") == PRIVATE_LEADERBOARD_PANEL_NAME
        and payload.get("seeds") == REDACTED_SEEDS_SENTINEL
    )


def _validate_redaction_shape(errors: list[str], payload: dict[str, Any], *, redacted_private: bool) -> None:
    redaction = _dict(payload.get("redaction"))
    if not redaction:
        if payload.get("seeds") == REDACTED_SEEDS_SENTINEL:
            errors.append("redacted seeds require a redaction block with applied=true")
        return
    applied = redaction.get("applied")
    if applied is True and not redacted_private:
        errors.append("redaction.applied requires seed_panel.name='private-env' and top-level seeds='<redacted>'")
    if applied is False and payload.get("seeds") == REDACTED_SEEDS_SENTINEL:
        errors.append("seeds='<redacted>' is invalid when redaction.applied is false")


def _redact_seed_fields(payload: dict[str, Any], removed: list[str]) -> None:
    if "seeds" in payload:
        payload["seeds"] = REDACTED_SEEDS_SENTINEL
        removed.append("seeds")


def _redact_run_block(block: dict[str, Any], removed: list[str]) -> None:
    if not block:
        return
    if "seeds" in block:
        block["seeds"] = REDACTED_SEEDS_SENTINEL
        removed.append(f"{block.get('agent', 'result')}.seeds")
    if "episodes" in block:
        block["episodes"] = []
        removed.append(f"{block.get('agent', 'result')}.episodes")


def _expect_redacted_run_block(errors: list[str], label: str, block: dict[str, Any]) -> None:
    if block.get("seeds") not in (None, REDACTED_SEEDS_SENTINEL):
        errors.append(f"{label}.seeds must be redacted in private artifacts")
    if _list(block.get("episodes")):
        errors.append(f"{label}.episodes must be empty in redacted private artifacts")


def _resolve_expected_seeds(
    errors: list[str],
    warnings: list[str],
    run_info: dict[str, Any],
    *,
    payload_seeds: Any,
    require: bool,
    redacted_private: bool,
) -> tuple[list[int] | None, int]:
    public_seeds = list(PRESETS["leaderboard"]["seeds"])
    panel = _dict(run_info.get("seed_panel"))
    actual_seeds = _list(payload_seeds) if payload_seeds != REDACTED_SEEDS_SENTINEL else []
    parsed_seeds: list[int] = []
    if actual_seeds and all(isinstance(seed, int) or str(seed).lstrip("-").isdigit() for seed in actual_seeds):
        parsed_seeds = [int(seed) for seed in actual_seeds]

    if not panel:
        message = "run_info.seed_panel is required for official seed-panel validation"
        if require:
            errors.append(message)
        else:
            warnings.append(message)
        return public_seeds, len(public_seeds)

    name = panel.get("name")
    if name == PUBLIC_LEADERBOARD_PANEL_NAME:
        expected_seeds: list[int] | None = public_seeds
        expected_count = len(public_seeds)
    elif name == PRIVATE_LEADERBOARD_PANEL_NAME:
        if redacted_private:
            expected_seeds = None
            try:
                expected_count = int(panel.get("count"))
            except (TypeError, ValueError):
                expected_count = 0
                errors.append("run_info.seed_panel.count must be an integer for redacted private panels")
            sha = panel.get("sha256")
            if not isinstance(sha, str) or not _SHA256_RE.fullmatch(sha):
                errors.append("run_info.seed_panel.sha256 must be a 64-char lowercase hex digest")
        elif not os.environ.get(PRIVATE_SEEDS_ENV):
            errors.append(f"{PRIVATE_SEEDS_ENV} is required to validate a private leaderboard seed panel")
            expected_seeds = parsed_seeds or public_seeds
            expected_count = len(expected_seeds)
        else:
            expected_seeds = _parse_seeds(os.environ[PRIVATE_SEEDS_ENV])
            expected_count = len(expected_seeds)
    elif name == CUSTOM_SEED_PANEL_NAME:
        errors.append("custom seed panels are not official leaderboard results")
        expected_seeds = parsed_seeds or public_seeds
        expected_count = len(expected_seeds)
    else:
        errors.append(f"unknown seed panel name {name!r}")
        expected_seeds = parsed_seeds or public_seeds
        expected_count = len(expected_seeds)

    if panel.get("preset") != "leaderboard":
        errors.append(f"run_info.seed_panel.preset must be 'leaderboard', got {panel.get('preset')!r}")
    if parsed_seeds:
        expected_hash = seed_panel_hash(parsed_seeds)
        if panel.get("sha256") != expected_hash:
            errors.append(f"run_info.seed_panel.sha256 must be {expected_hash!r}, got {panel.get('sha256')!r}")
        if panel.get("count") != len(parsed_seeds):
            errors.append(f"run_info.seed_panel.count must be {len(parsed_seeds)}, got {panel.get('count')!r}")
    elif redacted_private and panel.get("count") != expected_count and expected_count:
        # count already parsed above; keep consistency if both present
        pass
    return expected_seeds, expected_count


def _validate_contract_provenance(
    errors: list[str],
    warnings: list[str],
    run_info: dict[str, Any],
    *,
    require: bool,
    expected: dict[str, Any] | None,
) -> None:
    contract = _dict(run_info.get("benchmark_contract"))
    expected = expected or expected_contract()
    if not contract:
        message = "run_info.benchmark_contract is required for current-contract validation"
        if require:
            errors.append(message)
        else:
            warnings.append(message)
        return
    for key, expected_value in expected.items():
        actual = contract.get(key)
        if actual != expected_value:
            errors.append(f"run_info.benchmark_contract.{key} must be {expected_value!r}, got {actual!r}")


def _validate_scaffold_provenance(
    errors: list[str],
    warnings: list[str],
    run_info: dict[str, Any],
    *,
    require: bool = False,
    policy_name: str = "",
    expected_fingerprints: dict[str, str] | None = None,
) -> None:
    """Check the row's prompt scaffold matches the current source.

    Rows produced before scaffold provenance existed carry no fingerprint and
    get a warning, not an error, so already-published artifacts stay eligible
    while remaining visibly unattested at the prompt layer.
    """
    recorded = run_info.get("scaffold_fingerprint")
    provider = str(run_info.get("provider") or "")
    expected = (
        expected_fingerprints.get(provider) if expected_fingerprints is not None else scaffold_fingerprint(provider)
    )
    if recorded is None:
        if require:
            errors.append(
                f"run_info.scaffold_fingerprint is required for {policy_name} rows; "
                "the prompt scaffold must be attested"
            )
        else:
            warnings.append(
                "run_info.scaffold_fingerprint missing: prompt scaffold unverified (pre-provenance artifact)"
            )
        return
    if expected is None:
        message = f"run_info.provider {provider!r} is not a built-in provider; scaffold fingerprint cannot be checked"
        if require:
            errors.append(message)
        else:
            warnings.append(message)
        return
    if recorded != expected:
        errors.append(
            f"run_info.scaffold_fingerprint {recorded!r} does not match current scaffold {expected!r} "
            f"for provider {provider!r}"
        )


def _validate_strict_fallback(errors: list[str], run_info: dict[str, Any], *, policy_name: str) -> None:
    """Require a row to have been measured under strict failure handling.

    Read from both the resolved provenance flag and the adapter environment
    recorded alongside it: a row that disagrees with itself about how failed
    decisions were handled is not attributable to either policy.
    """
    declared = run_info.get("strict_fallback")
    option = (run_info.get("provider_options") or {}).get("GM_AGENT_STRICT")
    if declared is None:
        errors.append(
            f"run_info.strict_fallback is required for {policy_name} rows; the failure-handling policy must be attested"
        )
    elif declared is not True:
        errors.append(
            f"{policy_name} rows must run with strict failure handling; "
            "soft-fallback rows credit host-supplied roster moves to the model"
        )
    if option in (None, ""):
        errors.append(f"run_info.provider_options.GM_AGENT_STRICT is required for {policy_name} rows")
    elif str(option) != "1":
        errors.append(f"{policy_name} rows must record GM_AGENT_STRICT=1; got {option!r}")
    elif declared is False:
        errors.append("run_info strict-fallback provenance values must match")


def _validate_episode_panel(
    errors: list[str],
    label: str,
    result: dict[str, Any],
    expected_seeds: list[int],
    expected_seasons: int,
    *,
    repeats: int,
    require_score_components: bool = False,
) -> None:
    episodes = _list(result.get("episodes"))
    expected_count = len(expected_seeds) * repeats
    if len(episodes) != expected_count:
        errors.append(f"{label}.episodes must contain {expected_count} episode(s)")
        return
    seen: dict[int, set[int]] = {seed: set() for seed in expected_seeds}
    for episode in episodes:
        block = _dict(episode)
        seed = block.get("seed")
        repeat = int(block.get("repeat", 1) or 1)
        if seed not in seen:
            errors.append(f"{label}.episodes contains unexpected seed {seed!r}")
            continue
        if not 1 <= repeat <= repeats:
            errors.append(f"{label}.episodes seed {seed} has unexpected repeat {repeat}")
            continue
        if repeat in seen[seed]:
            errors.append(f"{label}.episodes has duplicate seed/repeat {seed}/{repeat}")
        seen[seed].add(repeat)
        if block.get("seasons") != expected_seasons:
            errors.append(f"{label}.episodes seed {seed} repeat {repeat} has seasons={block.get('seasons')!r}")
        if require_score_components:
            _validate_score_components(errors, f"{label}.episodes seed {seed} repeat {repeat}", block)
    missing = {seed: sorted(set(range(1, repeats + 1)) - repeats_seen) for seed, repeats_seen in seen.items()}
    missing = {seed: values for seed, values in missing.items() if values}
    if missing:
        errors.append(f"{label}.episodes missing seed/repeat pairs: {missing}")


def _validate_score_components(errors: list[str], label: str, block: dict[str, Any]) -> None:
    """Check the persisted components are complete, finite, and self-consistent.

    The components exist so a score can be reweighted from the artifact alone.
    That only holds if every term is present, each raw metric still rebuilds its
    contribution under the published scale, and the contributions still add up
    to the strategy score the row was ranked on — so all three are checked here
    rather than trusting the field because it exists.

    Two limits worth stating, because neither is visible from the error text.

    The rebuild uses ``ACTIVE_SCORE_SCALE``, not the scale the row declares in
    ``run_info.benchmark_contract.scoring_version``. That is safe only while
    ``scoring.SCORE_SCALES`` has exactly one entry and ``sota-v3`` pins its
    fingerprint, which is the case today. The moment a ``score-v2`` is added,
    this must take the row's declared version and look the scale up — otherwise
    it silently re-weights archived rows against the new weights, in exactly the
    cross-version reweighting this block was persisted to enable.

    And these checks establish *self-consistency*, not authenticity. A tampered
    row whose raws, contributions, ``strategy_score`` and ``final_score`` were
    all scaled together passes every one of them. Nothing short of a re-run can
    do better here; the binding to real evidence is ``raw_artifact_sha256``.
    """
    components = block.get("score_components")
    if not isinstance(components, dict):
        errors.append(f"{label} is missing score_components")
        return
    missing = [name for name in SCORE_COMPONENT_KEYS if name not in components]
    if missing:
        errors.append(f"{label}.score_components is missing {missing}")
        return
    values: dict[str, float] = {}
    for name in SCORE_COMPONENT_KEYS:
        value = components[name]
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
            errors.append(f"{label}.score_components.{name} must be a finite number")
            return
        values[name] = float(value)
    for name in SCORE_COMPONENT_METRICS:
        expected = contribution_from_metric(name, values[name])
        actual = values[f"{name}_contribution"]
        if abs(expected - actual) > _COMPONENT_TOLERANCE:
            errors.append(
                f"{label}.score_components.{name}_contribution does not match the published scale applied to {name}"
            )
            return
    strategy_score = block.get("strategy_score")
    if isinstance(strategy_score, (int, float)):
        rebuilt = sum(value for name, value in values.items() if name.endswith("_contribution"))
        if abs(rebuilt - float(strategy_score)) > _COMPONENT_TOLERANCE:
            errors.append(f"{label}.score_components contributions do not sum to strategy_score {strategy_score!r}")
    protocol_penalty = block.get("protocol_penalty")
    if isinstance(protocol_penalty, (int, float)):
        if abs(values["protocol_penalty"] - float(protocol_penalty)) > _COMPONENT_TOLERANCE:
            errors.append(f"{label}.score_components.protocol_penalty disagrees with the episode row")
    final_score = block.get("final_score")
    if (
        isinstance(final_score, (int, float))
        and isinstance(strategy_score, (int, float))
        and isinstance(protocol_penalty, (int, float))
    ):
        expected_final = float(strategy_score) - float(protocol_penalty)
        if abs(float(final_score) - expected_final) > _COMPONENT_TOLERANCE:
            errors.append(f"{label}.final_score does not equal strategy_score - protocol_penalty")


def _validate_compact_integrity(
    errors: list[str],
    payload: dict[str, Any],
    candidate: dict[str, Any],
    baselines: list[dict[str, Any]],
    seeds: list[int],
    *,
    allow_legacy_sign_flip_rounding: bool,
) -> None:
    """Treat compact summaries as derived views, never independent evidence."""
    _validate_finite_numbers(errors, payload)
    if not candidate or not baselines or not seeds:
        return
    from gm_bench.runner import _paired_analysis, _precise_mean_score, summarize_episodes

    rebuilt_candidate = {**candidate, "summary": summarize_episodes(candidate.get("episodes") or [])}
    rebuilt_baselines = [
        {**baseline, "summary": summarize_episodes(baseline.get("episodes") or [])} for baseline in baselines
    ]
    _compare_present_values(
        errors,
        "candidate.summary",
        candidate.get("summary"),
        rebuilt_candidate["summary"],
        allow_legacy_sign_flip_rounding=allow_legacy_sign_flip_rounding,
    )
    for original, rebuilt in zip(baselines, rebuilt_baselines, strict=True):
        _compare_present_values(
            errors,
            f"baseline[{original.get('agent', 'unknown')}].summary",
            original.get("summary"),
            rebuilt["summary"],
            allow_legacy_sign_flip_rounding=allow_legacy_sign_flip_rounding,
        )
    baseline_mean = sum(_precise_mean_score(block) for block in rebuilt_baselines) / len(rebuilt_baselines)
    candidate_mean = _precise_mean_score(rebuilt_candidate)
    expected_normalized = {
        "candidate_mean_score": round(candidate_mean, 3),
        "baseline_panel_mean_score": round(baseline_mean, 3),
        "score_lift": round(candidate_mean - baseline_mean, 3),
        "score_lift_pct": round(((candidate_mean / baseline_mean) - 1.0) * 100.0, 2) if baseline_mean else 0.0,
        "candidate_illegal_actions": rebuilt_candidate["summary"]["illegal_actions"],
        "baseline_illegal_actions": sum(block["summary"]["illegal_actions"] for block in rebuilt_baselines),
    }
    _compare_present_values(
        errors,
        "normalized",
        payload.get("normalized"),
        expected_normalized,
        allow_legacy_sign_flip_rounding=allow_legacy_sign_flip_rounding,
    )
    _compare_present_values(
        errors,
        "paired",
        payload.get("paired"),
        _paired_analysis(seeds, rebuilt_candidate, rebuilt_baselines),
        allow_legacy_sign_flip_rounding=allow_legacy_sign_flip_rounding,
    )


def _validate_finite_numbers(errors: list[str], value: Any, path: str = "payload") -> None:
    if isinstance(value, float) and not math.isfinite(value):
        errors.append(f"{path} must not contain a non-finite number")
    elif isinstance(value, dict):
        for key, child in value.items():
            _validate_finite_numbers(errors, child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _validate_finite_numbers(errors, child, f"{path}[{index}]")


def _compare_present_values(
    errors: list[str],
    path: str,
    actual: Any,
    expected: Any,
    *,
    allow_legacy_sign_flip_rounding: bool,
) -> None:
    if not isinstance(actual, dict) or not isinstance(expected, dict):
        return
    for key, value in actual.items():
        if key not in expected:
            continue
        expected_value = expected[key]
        child_path = f"{path}.{key}"
        if isinstance(value, dict) and isinstance(expected_value, dict):
            _compare_present_values(
                errors,
                child_path,
                value,
                expected_value,
                allow_legacy_sign_flip_rounding=allow_legacy_sign_flip_rounding,
            )
        elif (
            allow_legacy_sign_flip_rounding
            and child_path.endswith(".sign_flip_p_value")
            and isinstance(value, int | float)
            and not isinstance(value, bool)
            and isinstance(expected_value, int | float)
            and not isinstance(expected_value, bool)
            and value == round(expected_value, 4)
        ):
            # Published v1/v2 artifacts rounded this derived value to four
            # decimals. Accept that frozen representation while new artifacts
            # retain the exact result.
            continue
        elif value != expected_value:
            errors.append(f"{child_path} does not match episode-derived value")


def _expect_equal(errors: list[str], name: str, actual: Any, expected: Any) -> None:
    if actual != expected:
        errors.append(f"{name} must be {expected!r}, got {actual!r}")


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
