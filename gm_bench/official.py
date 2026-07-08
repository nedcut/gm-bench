"""Official-result validation for GM-Bench leaderboard payloads."""

from __future__ import annotations

import copy
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
from gm_bench.contract import expected_contract

PUBLIC_LEADERBOARD_POLICY_NAME = "public-leaderboard"
SOTA_V1_POLICY_NAME = "sota-v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ResultPolicy:
    name: str
    min_repeats: int
    min_seed_count: int
    max_decision_failure_rate: float
    require_full_usage: bool = True
    require_contract_provenance: bool = False
    require_seed_panel_provenance: bool = False


PUBLIC_LEADERBOARD_POLICY = ResultPolicy(
    name=PUBLIC_LEADERBOARD_POLICY_NAME,
    min_repeats=1,
    min_seed_count=1,
    max_decision_failure_rate=0.20,
)
SOTA_V1_POLICY = ResultPolicy(
    name=SOTA_V1_POLICY_NAME,
    min_repeats=3,
    min_seed_count=len(PRESETS["leaderboard"]["seeds"]),
    max_decision_failure_rate=0.02,
    require_contract_provenance=True,
    require_seed_panel_provenance=True,
)
POLICIES = {
    PUBLIC_LEADERBOARD_POLICY.name: PUBLIC_LEADERBOARD_POLICY,
    SOTA_V1_POLICY.name: SOTA_V1_POLICY,
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
        _validate_contract_provenance(errors, warnings, run_info, require=policy.require_contract_provenance)
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
    _expect_equal(errors, "baselines", baseline_names, expected_baselines)

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
            _validate_episode_panel(errors, "candidate", candidate, expected_seeds, expected_seasons, repeats=repeats)
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
        usage = _dict(summary.get("usage"))
        if policy.require_full_usage and decisions:
            if int(usage.get("decisions_with_usage", 0) or 0) != decisions:
                errors.append("candidate usage must cover every decision point")
            if usage.get("cost_usd", "missing") == "missing":
                errors.append("candidate usage.cost_usd is required, use null only when pricing is unknown")

    for baseline in baselines:
        name = baseline.get("agent", "unknown")
        if redacted_private:
            _expect_redacted_run_block(errors, f"baseline[{name}]", baseline)
        elif expected_seeds is not None:
            _validate_episode_panel(errors, f"baseline[{name}]", baseline, expected_seeds, expected_seasons, repeats=1)

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
        elif best.get("agent") != "shrewd":
            warnings.append(f"strongest baseline is {best.get('agent')!r}, expected shrewd for v1 calibration")
        if paired.get("significant_at_95") is False:
            warnings.append("candidate lift is not significant at 95% against the baseline panel")
        if best and float(best.get("paired_lift_mean", 0.0) or 0.0) <= 0.0:
            warnings.append("candidate does not beat the strongest scripted baseline")

    return ValidationReport(policy=policy.name, errors=errors, warnings=warnings)


def redact_leaderboard_payload(
    payload: dict[str, Any],
    *,
    policy: ResultPolicy = SOTA_V1_POLICY,
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
) -> None:
    contract = _dict(run_info.get("benchmark_contract"))
    expected = expected_contract()
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


def _validate_episode_panel(
    errors: list[str],
    label: str,
    result: dict[str, Any],
    expected_seeds: list[int],
    expected_seasons: int,
    *,
    repeats: int,
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
    missing = {seed: sorted(set(range(1, repeats + 1)) - repeats_seen) for seed, repeats_seen in seen.items()}
    missing = {seed: values for seed, values in missing.items() if values}
    if missing:
        errors.append(f"{label}.episodes missing seed/repeat pairs: {missing}")


def _expect_equal(errors: list[str], name: str, actual: Any, expected: Any) -> None:
    if actual != expected:
        errors.append(f"{name} must be {expected!r}, got {actual!r}")


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
