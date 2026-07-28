"""Publication-safe result artifacts.

Raw model runs are durable local evidence, but their observation and transaction
traces are too large (and sometimes sensitive) for git.  Published artifacts
retain the aggregates, per-seed outcomes, usage, and a hash of the raw input.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from typing import Any

PUBLICATION_FORMAT = "gm-bench-result-summary-v1"


def canonical_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def raw_artifact_link_issues(
    compact: dict[str, Any],
    raw_payloads: list[dict[str, Any]],
) -> list[str]:
    """Verify that compact publication metadata names supplied raw evidence."""
    publication = compact.get("publication")
    declared = publication.get("raw_artifact_sha256") if isinstance(publication, dict) else None
    if not isinstance(declared, str) or re.fullmatch(r"[0-9a-f]{64}", declared) is None:
        return ["publication.raw_artifact_sha256 must be a 64-character lowercase hex digest"]
    if raw_payloads and declared not in {canonical_sha256(raw) for raw in raw_payloads}:
        return ["publication.raw_artifact_sha256 does not match any supplied raw artifact"]
    return []


FROZEN_OUTPUT_POLICY_BASES = frozenset(
    {
        "fixed-safety-ceiling",
        "common-safety-ceiling-with-native-minimum-reasoning",
    }
)


def exact_sign_flip_feasibility(
    seed_count: int,
    family_size: int,
    *,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Return whether an exact two-sided sign-flip test can clear Holm step one.

    Repeats do not improve this resolution because the publication unit of
    inference is the seed.  The smallest attainable two-sided p-value is
    ``2 / 2**seed_count`` and the strictest Holm threshold is
    ``alpha / family_size``.
    """
    if not isinstance(seed_count, int) or isinstance(seed_count, bool) or seed_count < 2:
        raise ValueError("seed_count must be an integer >= 2")
    if not isinstance(family_size, int) or isinstance(family_size, bool) or family_size < 1:
        raise ValueError("family_size must be a positive integer")
    if not isinstance(alpha, int | float) or isinstance(alpha, bool) or not 0.0 < float(alpha) < 1.0:
        raise ValueError("alpha must be between zero and one")
    minimum_p_value = math.ldexp(1.0, 1 - seed_count)
    first_step_threshold = float(alpha) / family_size
    return {
        "seed_count": seed_count,
        "family_size": family_size,
        "alpha": float(alpha),
        "minimum_two_sided_p_value": minimum_p_value,
        "holm_first_step_threshold": first_step_threshold,
        "feasible": minimum_p_value <= first_step_threshold,
    }


def _v3_identity_issues(
    lane: dict[str, Any],
    registry: dict[str, Any],
    protocol: dict[str, Any] | None,
    pricing: dict[str, Any] | None,
    manifest: dict[str, Any] | None,
) -> list[str]:
    issues: list[str] = []
    contract = str(lane.get("contract") or "")
    contract_fingerprint = lane.get("contract_fingerprint")
    if not isinstance(contract_fingerprint, str) or not contract_fingerprint:
        issues.append("sota-v3 lane contract_fingerprint is missing")
    provenance_payloads = (
        ("model registry", registry),
        ("smoke manifest", manifest),
        ("publication protocol", protocol),
        ("pricing snapshot", pricing),
    )
    for label, payload in provenance_payloads:
        if not isinstance(payload, dict) or payload.get("contract") != contract:
            issues.append(f"sota-v3 {label} contract does not match the lane")
        if not isinstance(payload, dict) or payload.get("contract_fingerprint") != contract_fingerprint:
            issues.append(f"sota-v3 {label} contract_fingerprint does not match the lane")
    if lane.get("execution_profile_authority") != "lane":
        issues.append("sota-v3 execution_profile_authority must be 'lane'")
    coherence_fields = (
        ("headline_lane", "lane"),
        ("provider", "provider"),
        ("observation_profile", "profile"),
        ("preset", "preset"),
        ("session", "session"),
        ("repeats", "repeats"),
        ("output_token_cap", "output_token_cap"),
    )
    for lane_key, registry_key in coherence_fields:
        if lane.get(lane_key) != registry.get(registry_key):
            issues.append(f"sota-v3 model registry {registry_key} does not match lane-authoritative {lane_key}")
    return issues


def v3_statistical_plan_issues(
    lane: dict[str, Any],
    registry: dict[str, Any],
    protocol: dict[str, Any] | None,
) -> list[str]:
    issues: list[str] = []
    if lane.get("contract") != "sota-v3" or registry.get("contract") != "sota-v3":
        issues.append("sota-v3 statistical inputs must declare contract 'sota-v3'")
    contract_fingerprint = lane.get("contract_fingerprint")
    if (
        not isinstance(contract_fingerprint, str)
        or not contract_fingerprint
        or registry.get("contract_fingerprint") != contract_fingerprint
        or not isinstance(protocol, dict)
        or protocol.get("contract_fingerprint") != contract_fingerprint
    ):
        issues.append("sota-v3 statistical inputs must share one contract_fingerprint")
    plan = protocol.get("statistical_analysis_plan") if isinstance(protocol, dict) else None
    if not isinstance(plan, dict) or plan.get("status") != "frozen":
        return ["sota-v3 statistical analysis plan is not frozen"]
    expected_reference = lane.get("reference_agent")
    if expected_reference != "pick-trader":
        issues.append("sota-v3 lane reference_agent must be 'pick-trader'")
    if plan.get("unit_of_inference") != "seed":
        issues.append("sota-v3 unit_of_inference must be 'seed'")
    if plan.get("primary_contrast") != "paired lift versus pick-trader":
        issues.append("sota-v3 primary_contrast must be 'paired lift versus pick-trader'")
    if plan.get("reference_agent") != expected_reference:
        issues.append("sota-v3 statistical reference_agent must match the lane reference_agent")
    if plan.get("multiplicity_method") != "holm-bonferroni":
        issues.append("sota-v3 multiplicity_method must be 'holm-bonferroni'")
    alpha = plan.get("alpha")
    if not isinstance(alpha, int | float) or isinstance(alpha, bool) or float(alpha) != 0.05:
        issues.append("sota-v3 statistical alpha must be 0.05")
    models = [model for model in registry.get("models") or [] if isinstance(model, dict)]
    family_size = plan.get("holm_family_size")
    if family_size != len(models):
        issues.append("sota-v3 Holm family size must equal the frozen registered model count")
    seed_panel = lane.get("seed_panel")
    if not isinstance(seed_panel, dict) or seed_panel.get("status") != "frozen":
        issues.append("sota-v3 seed panel identity is not frozen")
        return issues
    seed_count = seed_panel.get("count")
    if (
        not isinstance(seed_count, int)
        or isinstance(seed_count, bool)
        or seed_count < 2
        or not isinstance(family_size, int)
        or isinstance(family_size, bool)
        or family_size < 1
    ):
        issues.append("sota-v3 seed count and Holm family size must be positive frozen integers")
        return issues
    inference_method = plan.get("inference_method")
    if inference_method != "exact-enumeration-sign-flip":
        issues.append("sota-v3 inference_method is not implemented; currently supported: 'exact-enumeration-sign-flip'")
        return issues
    if seed_count > 20:
        issues.append("sota-v3 exact-enumeration-sign-flip requires at most 20 seeds")
        return issues
    try:
        feasibility = exact_sign_flip_feasibility(seed_count, family_size)
    except ValueError as exc:
        issues.append(f"sota-v3 exact sign-flip feasibility is invalid: {exc}")
    else:
        if not feasibility["feasible"]:
            issues.append(
                "sota-v3 exact sign-flip test cannot clear Holm step one with the frozen "
                f"{seed_count}-seed/{family_size}-model design"
            )
    if plan.get("analysis_mode") != "reference-only":
        issues.append("sota-v3 statistical analysis mode must be 'reference-only'")
    return issues


def publication_execution_issues(
    lane: dict[str, Any],
    registry: dict[str, Any],
    manifest: dict[str, Any] | None,
    *,
    phase: str,
    protocol: dict[str, Any] | None = None,
    pricing: dict[str, Any] | None = None,
) -> list[str]:
    """Return every blocker before a provider-backed smoke or panel run.

    This is the single authorization gate shared by the real publication
    runner and the zero-spend rehearsal. Historical ``sota-v2`` files predate
    these fields and are guarded separately by the runner's current-contract
    check; a current ``sota-v3`` lane must carry the complete fail-closed state.
    """
    if phase not in {"route-preflight", "smoke", "panel"}:
        return [f"unsupported publication phase {phase!r}"]
    contract = str(lane.get("contract") or "")
    if contract != str(registry.get("contract") or ""):
        return ["publication lane and model registry contracts do not match"]
    if contract == "sota-v2" and lane.get("preregistration_status") is None:
        return []

    issues: list[str] = []
    if contract == "sota-v3":
        issues.extend(_v3_identity_issues(lane, registry, protocol, pricing, manifest))
        if phase != "route-preflight":
            if (
                not isinstance(protocol, dict)
                or protocol.get("contract") != contract
                or protocol.get("status") != "frozen"
            ):
                issues.append("sota-v3 publication protocol is not frozen")
            if (
                not isinstance(pricing, dict)
                or pricing.get("contract") != contract
                or pricing.get("status") != "frozen"
            ):
                issues.append("sota-v3 pricing snapshot is not frozen")
            issues.extend(v3_statistical_plan_issues(lane, registry, protocol))
        elif lane.get("route_preflight_authorized") is not True:
            issues.append("zero-call route preflight is locked while route_preflight_authorized is false")
        if phase == "route-preflight":
            if registry.get("selection_status") not in {"route-preflight-ready", "frozen"}:
                issues.append("model registry is not ready for zero-call route preflight")
            if not registry.get("models"):
                issues.append("publication model registry contains no models")
            return list(dict.fromkeys(issues))
    status = str(lane.get("preregistration_status") or "")
    if status != "frozen":
        issues.append(f"{contract or 'publication'} lane is {status or 'missing-status'}; provider execution is locked")
    if lane.get("panel_design_status") != "frozen":
        issues.append("publication panel design is not frozen")
    if registry.get("selection_status") != "frozen":
        issues.append("provider execution is locked until the model registry is frozen")

    models = [model for model in registry.get("models") or [] if isinstance(model, dict)]
    model_ids = {str(model.get("id") or "") for model in models if model.get("id")}
    required_smokes = registry.get("required_smokes")
    required_smoke_ids = {str(model_id) for model_id in required_smokes} if isinstance(required_smokes, list) else set()
    if not models:
        issues.append("publication model registry contains no models")
    minimum_headline_models = lane.get("minimum_headline_models")
    if (
        not isinstance(minimum_headline_models, int)
        or isinstance(minimum_headline_models, bool)
        or minimum_headline_models <= 0
    ):
        issues.append("publication minimum_headline_models must be a positive frozen integer")
    elif len(model_ids) < minimum_headline_models:
        issues.append(
            f"publication model registry has {len(model_ids)} models; "
            f"minimum_headline_models requires {minimum_headline_models}"
        )
    if not required_smoke_ids or required_smoke_ids != model_ids:
        issues.append("required_smokes must exactly match the registered model ids")

    lane_cap = lane.get("output_token_cap")
    registry_cap = registry.get("output_token_cap")
    if not isinstance(lane_cap, int) or isinstance(lane_cap, bool) or lane_cap <= 0:
        issues.append("publication output_token_cap must be a positive frozen integer")
    if registry_cap != lane_cap:
        issues.append("publication lane and model registry output_token_cap must match")
    if lane.get("output_policy_basis") not in FROZEN_OUTPUT_POLICY_BASES:
        issues.append("publication output policy basis is not frozen")

    if lane.get("spend_authorized") is not True or registry.get("spend_authorized") is not True:
        issues.append("provider execution is locked until spend is explicitly authorized")
    if contract == "sota-v3":
        budget_policy = protocol.get("budget_policy") if isinstance(protocol, dict) else None
        if not isinstance(budget_policy, dict) or budget_policy.get("spend_authorized") is not True:
            issues.append("provider execution is locked by the publication protocol budget policy")
        if not isinstance(pricing, dict) or pricing.get("spend_authorized") is not True:
            issues.append("provider execution is locked by the pricing snapshot")
    authorization_flag = "smoke_execution_authorized" if phase == "smoke" else "panel_execution_authorized"
    if lane.get(authorization_flag) is not True:
        issues.append(f"provider execution is locked while {authorization_flag} is false")

    if phase == "panel":
        if registry.get("panel_execution_authorized") is not True:
            issues.append("panel execution is locked by the model registry")
        if not isinstance(manifest, dict) or manifest.get("accepted_for_panel") is not True:
            issues.append("v3 smoke manifest is not accepted for panel execution")
        issues.extend(
            smoke_manifest_issues(
                manifest,
                registry,
                lane,
                require_strict_fallback=True,
            )
        )
    return issues


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
        "score_components",
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
    *,
    expected_contract_fingerprint: str | None = None,
    validate_current_scaffold: bool = True,
    require_strict_fallback: bool = False,
) -> list[str]:
    """Machine-check the pre-panel smoke evidence against the frozen lane.

    The full panel (and any published ranking) must not be unlockable by
    editing a status string: every registered model needs an accepted smoke
    manifest entry recorded from a real artifact, at the frozen cap, under the
    selected scaffold and contract, with complete finish-reason telemetry and
    no cap-pressure or truncation trigger. Historical release builders may pass
    their frozen contract fingerprint and disable current-scaffold comparison;
    new publication runners retain the current-source defaults, and require the
    smoke to have been recorded under strict failure handling.
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
        if require_strict_fallback and entry.get("strict_fallback") is not True:
            issues.append(f"{prefix} was not recorded under strict failure handling")
        expected_contract = expected_contract_fingerprint or contract_fingerprint()
        if entry.get("contract_fingerprint") != expected_contract:
            issues.append(f"{prefix} was recorded under a different benchmark contract")
        if validate_current_scaffold:
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
