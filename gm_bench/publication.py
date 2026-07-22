"""Publication-safe result artifacts.

Raw model runs are durable local evidence, but their observation and transaction
traces are too large (and sometimes sensitive) for git.  Published artifacts
retain the aggregates, per-seed outcomes, usage, and a hash of the raw input.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any

PUBLICATION_FORMAT = "gm-bench-result-summary-v1"


def canonical_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def compact_result(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a validator-compatible artifact without verbose episode traces."""
    if payload.get("publication"):
        raise ValueError("input already has publication metadata; compact the original raw artifact")
    result = copy.deepcopy(payload)
    baseline_cache = result.get("baseline_cache")
    if isinstance(baseline_cache, dict):
        # The raw artifact may record an absolute local cache path for operator
        # diagnostics. It is machine-specific and adds no publication evidence.
        baseline_cache.pop("path", None)
    for label in ("candidate", "baselines"):
        blocks = [result.get(label)] if label == "candidate" else result.get(label, [])
        for block in blocks:
            if not isinstance(block, dict):
                continue
            block["episodes"] = [_compact_episode(ep) for ep in block.get("episodes", [])]
    result["publication"] = {
        "format": PUBLICATION_FORMAT,
        "raw_artifact_sha256": canonical_sha256(payload),
        "traces_included": False,
        "mechanic_breakdown": mechanic_breakdown((payload.get("candidate") or {}).get("episodes", [])),
    }
    return result


def _compact_episode(episode: Any) -> dict[str, Any]:
    if not isinstance(episode, dict):
        return {}
    keep = (
        "seed",
        "repeat",
        "seasons",
        "final_score",
        "strategy_score",
        "protocol_penalty",
        "wins",
        "championships",
        "illegal_actions",
        "decisions",
        "failed_decisions",
        "failed_queries",
        "query_declines",
        "memo_writes",
        "rejected_offers",
    )
    compact = {key: episode[key] for key in keep if key in episode}
    usage = copy.deepcopy(episode.get("usage") or {})
    usage.pop("per_decision", None)
    if usage:
        compact["usage"] = usage
    return compact


SMOKE_MANIFEST_FORMAT = "gm-bench-smoke-manifest-v1"
# OpenAI-style finish reasons that mean the response hit the output ceiling.
TRUNCATION_FINISH_REASONS = frozenset({"length", "max_tokens", "max_output_tokens"})


def smoke_manifest_issues(
    manifest: dict[str, Any] | None,
    registry: dict[str, Any],
    lane: dict[str, Any],
) -> list[str]:
    """Machine-check the pre-panel smoke evidence against the frozen lane.

    The full panel (and any published ranking) must not be unlockable by
    editing a status string: every registered model needs an accepted smoke
    manifest entry recorded from a real artifact, at the frozen cap, under the
    current scaffold and contract, with complete finish-reason telemetry and
    no cap-pressure or truncation trigger.
    """
    from gm_bench.benchmark_config import PRESETS
    from gm_bench.contract import contract_fingerprint, scaffold_fingerprint
    from gm_bench.protocol import PHASES

    issues: list[str] = []
    if not isinstance(manifest, dict) or not manifest:
        return ["smoke manifest is missing; record every registered-model smoke before the panel"]
    if manifest.get("format") != SMOKE_MANIFEST_FORMAT:
        issues.append(f"smoke manifest format must be {SMOKE_MANIFEST_FORMAT!r}")
    if manifest.get("schema_version") != 1:
        issues.append("smoke manifest schema_version must be 1")
    entries = manifest.get("entries")
    entries = entries if isinstance(entries, dict) else {}
    frozen_cap = lane.get("output_token_cap")
    threshold = lane.get("cap_pressure_threshold_tokens")
    smoke = PRESETS["smoke"]
    expected_decisions = len(smoke["seeds"]) * int(smoke["seasons"]) * len(PHASES)
    models = [model for model in registry.get("models") or [] if isinstance(model, dict)]
    registered_ids = {str(model.get("id")) for model in models}
    for stale in sorted(set(entries) - registered_ids):
        issues.append(f"smoke manifest entry {stale!r} is not in the current model registry")
    for model in models:
        model_id = str(model.get("id"))
        entry = entries.get(model_id)
        if not isinstance(entry, dict):
            issues.append(f"registered model {model_id!r} has no smoke manifest entry")
            continue
        prefix = f"smoke manifest entry {model_id!r}"
        if entry.get("accepted") is not True:
            issues.append(f"{prefix} is not accepted")
        if entry.get("decision_failure_rate") != 0:
            issues.append(f"{prefix} decision_failure_rate must be zero")
        for key in (
            "provider",
            "model",
            "upstream_provider",
            "upstream_provider_slug",
            "endpoint_tag",
            "endpoint_name",
            "reasoning_policy",
            "reasoning_effort",
        ):
            if entry.get(key) != model.get(key):
                issues.append(f"{prefix} {key} does not match the registered route")
        if entry.get("output_token_cap") != frozen_cap:
            issues.append(f"{prefix} was recorded at cap {entry.get('output_token_cap')!r}, not frozen {frozen_cap!r}")
        repair_attempts = entry.get("protocol_repair_attempts", 0)
        repair_successes = entry.get("protocol_repairs_succeeded", 0)
        if not isinstance(repair_attempts, int) or isinstance(repair_attempts, bool) or repair_attempts < 0:
            issues.append(f"{prefix} protocol_repair_attempts must be a non-negative integer")
            repair_attempts = 0
        if repair_successes != repair_attempts:
            issues.append(f"{prefix} successful protocol repairs must match repair attempts")
        api_calls = int(entry.get("api_calls") or 0)
        minimum_api_calls = expected_decisions + repair_attempts
        if api_calls < minimum_api_calls:
            issues.append(f"{prefix} must record at least {minimum_api_calls} API calls for its decisions and repairs")
        if int(entry.get("calls_with_finish_reason") or 0) != api_calls:
            issues.append(f"{prefix} finish-reason telemetry does not cover every API call")
        if entry.get("decisions_with_usage") != expected_decisions:
            issues.append(f"{prefix} usage must cover all {expected_decisions} smoke decision points")
        if entry.get("cost_decisions") != expected_decisions:
            issues.append(f"{prefix} cost telemetry must cover all {expected_decisions} smoke decision points")
        if int(entry.get("truncated_calls") or 0):
            issues.append(f"{prefix} shows cap-induced truncation; apply the cap-pressure rule before the panel")
        max_output = entry.get("max_output_tokens_per_call")
        if not isinstance(max_output, int):
            issues.append(f"{prefix} is missing max_output_tokens_per_call")
        elif isinstance(threshold, int) and max_output >= threshold:
            issues.append(
                f"{prefix} peaked at {max_output} output tokens, at or above the "
                f"{threshold}-token cap-pressure threshold; apply the cap-pressure rule before the panel"
            )
        reasoning_tokens = entry.get("reasoning_tokens")
        if model.get("reasoning_policy") == "disabled" and int(reasoning_tokens or 0):
            issues.append(f"{prefix} recorded reasoning tokens for a reasoning-disabled model")
        if model.get("reasoning_policy") == "mandatory-minimum" and (
            not isinstance(reasoning_tokens, int) or isinstance(reasoning_tokens, bool) or reasoning_tokens < 0
        ):
            issues.append(f"{prefix} is missing reasoning-token telemetry for a mandatory-reasoning model")
        if entry.get("contract_fingerprint") != contract_fingerprint():
            issues.append(f"{prefix} was recorded under a different benchmark contract")
        expected_scaffold = scaffold_fingerprint(str(model.get("provider") or ""))
        if expected_scaffold is not None and entry.get("scaffold_fingerprint") != expected_scaffold:
            issues.append(f"{prefix} was recorded under a different prompt scaffold")
        artifact_sha = entry.get("artifact_sha256")
        if not isinstance(artifact_sha, str) or re.fullmatch(r"[0-9a-f]{64}", artifact_sha) is None:
            issues.append(f"{prefix} must record the raw artifact sha256")
    return issues


def mechanic_breakdown(episodes: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    categories = {
        "draft": {"draft", "scout"},
        "trades": {"trade", "accept_trade_offer", "reject_trade_offer", "counter_trade_offer"},
        "cap_free_agency": {"sign_free_agent", "release", "claim_waiver"},
        "lineup": {"set_lineup"},
        "information_memory": {"inspect_team", "inspect_player", "list_free_agents", "memo"},
    }
    output = {name: {"accepted": 0, "rejected": 0} for name in categories}
    for episode in episodes:
        for transaction in episode.get("transactions", []):
            action_type = (transaction.get("action") or {}).get("type")
            category = next((name for name, values in categories.items() if action_type in values), None)
            if category:
                output[category]["accepted" if transaction.get("accepted") else "rejected"] += 1
    return output
