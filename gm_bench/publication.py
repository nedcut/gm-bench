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
from pathlib import Path
from typing import Any

PUBLICATION_FORMAT = "gm-bench-result-summary-v1"

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _repo_artifact_path(value: str) -> Path:
    path = Path(value)
    path = path.resolve() if path.is_absolute() else (_REPO_ROOT / path).resolve()
    try:
        path.relative_to(_REPO_ROOT.resolve())
    except ValueError as exc:
        raise ValueError("publication artifact path escapes the repository root") from exc
    return path


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
_ROUTE_IDENTITY_KEYS = (
    "provider",
    "model",
    "canonical_slug",
    "transport",
    "upstream_provider",
    "upstream_provider_slug",
    "endpoint_tag",
    "endpoint_name",
)
_PRIVACY_OPTION_MARKERS = ("DATA_COLLECTION", "PRIVACY", "RETENTION", "TRAINING", "ZDR")
_PRIVACY_ACCEPTANCE_FIELDS = (
    "data_collection_policy_accepted",
    "retention_policy_accepted",
    "training_use_policy_accepted",
)
PENDING_STRICT_SMOKE_CAP_VERIFICATION = {
    "status": "request-cap-pending-strict-smoke",
    "catalog_max_completion_tokens": None,
    "request_parameter": "max_tokens",
    "strict_smoke_required": True,
}


def is_pending_strict_smoke_cap(value: Any) -> bool:
    """Return whether *value* is the exact fail-closed cap deferral contract."""

    return isinstance(value, dict) and value == PENDING_STRICT_SMOKE_CAP_VERIFICATION


def _registered_route_options(registry: dict[str, Any], model: dict[str, Any]) -> tuple[dict[str, str], list[str]]:
    requested = {
        **{str(key): str(value) for key, value in (registry.get("shared_fixed_options") or {}).items()},
        **{str(key): str(value) for key, value in (model.get("fixed_options") or {}).items()},
        "OPENROUTER_PROVIDER_ONLY": str(model.get("upstream_provider_slug") or ""),
        "OPENROUTER_EXPECTED_UPSTREAM_PROVIDER": str(model.get("upstream_provider") or ""),
        "OPENROUTER_EXPECTED_ENDPOINT_NAME": str(model.get("endpoint_name") or ""),
    }
    absent = {
        str(value)
        for value in [*(registry.get("shared_absent_options") or []), *(model.get("absent_options") or [])]
        if str(value) not in requested
    }
    return requested, sorted(absent)


def v3_route_identity_sha256(registry: dict[str, Any], model: dict[str, Any]) -> str:
    """Bind route evidence to the exact route and execution/privacy policy."""

    requested, absent = _registered_route_options(registry, model)
    privacy_requested = {
        key: value for key, value in requested.items() if any(marker in key for marker in _PRIVACY_OPTION_MARKERS)
    }
    privacy_absent = [key for key in absent if any(marker in key for marker in _PRIVACY_OPTION_MARKERS)]
    return canonical_sha256(
        {
            "route": {key: model.get(key) for key in _ROUTE_IDENTITY_KEYS},
            "execution_policy": {
                "output_token_cap": registry.get("output_token_cap"),
                "reasoning_policy": model.get("reasoning_policy"),
                "reasoning_effort": model.get("reasoning_effort"),
                "output_cap_verification": model.get("output_cap_verification"),
                "supported_parameters": sorted(str(value) for value in model.get("catalog_supported_parameters") or []),
                "requested_options": requested,
                "absent_options": absent,
            },
            "privacy_controls": {
                "requested_options": privacy_requested,
                "absent_options": privacy_absent,
            },
        }
    )


def v3_route_acceptance_issues(registry: dict[str, Any], *, repo_root: Path | None = None) -> list[str]:
    """Require authenticated route and privacy evidence before provider spend."""

    models = [model for model in registry.get("models") or [] if isinstance(model, dict)]
    acceptance = registry.get("exact_route_acceptance")
    if not isinstance(acceptance, dict):
        return ["sota-v3 exact-route acceptance record is missing"]
    issues: list[str] = []
    if acceptance.get("status") != "accepted":
        issues.append("sota-v3 exact-route acceptance status is not accepted")
    privacy_standard = acceptance.get("privacy_standard")
    if not isinstance(privacy_standard, dict):
        issues.append("sota-v3 exact-route privacy standard is missing")
    else:
        if privacy_standard.get("data_classification") != "synthetic-benchmark-no-personal-or-confidential-data":
            issues.append("sota-v3 exact-route privacy data classification is not accepted")
        if privacy_standard.get("provider_data_collection") != "deny":
            issues.append("sota-v3 exact-route privacy standard must deny provider data collection")
        if privacy_standard.get("provider_training_use_allowed") is not False:
            issues.append("sota-v3 exact-route privacy standard must prohibit provider training use")
        if privacy_standard.get("zero_data_retention_required") is not False:
            issues.append("sota-v3 exact-route privacy standard must explicitly resolve the ZDR requirement")
    entries = acceptance.get("entries")
    entries = entries if isinstance(entries, dict) else {}
    evidence: dict[str, Any] | None = None
    evidence_artifact = acceptance.get("evidence_artifact")
    if not isinstance(evidence_artifact, str) or not evidence_artifact.strip():
        issues.append("sota-v3 exact-route evidence artifact is missing")
    else:
        try:
            root = _REPO_ROOT if repo_root is None else repo_root
            evidence_path = Path(evidence_artifact)
            evidence_path = evidence_path.resolve() if evidence_path.is_absolute() else (root / evidence_path).resolve()
            evidence_path.relative_to(root.resolve())
            loaded = json.loads(evidence_path.read_text())
            if not isinstance(loaded, dict):
                raise ValueError("evidence artifact must contain a JSON object")
            evidence = loaded
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            issues.append(f"sota-v3 exact-route evidence artifact cannot be read: {exc}")
    evidence_routes = evidence.get("routes") if evidence is not None else None
    expected_contract = registry.get("contract")
    expected_fingerprint = registry.get("contract_fingerprint")
    if evidence is not None:
        if evidence.get("format") != "gm-bench-route-acceptance-evidence-v1":
            issues.append("sota-v3 exact-route evidence artifact has the wrong format")
        if evidence.get("contract") != expected_contract:
            issues.append("sota-v3 exact-route evidence artifact is for a different contract")
        if evidence.get("contract_fingerprint") != expected_fingerprint:
            issues.append("sota-v3 exact-route evidence artifact is for a different contract fingerprint")
        if evidence.get("completion_calls") != 0:
            issues.append("sota-v3 exact-route evidence artifact must record zero completion calls")
    if evidence is not None and not isinstance(evidence_routes, dict):
        issues.append("sota-v3 exact-route evidence artifact routes are missing")
        evidence_routes = {}
    model_ids = {str(model.get("id") or "") for model in models}
    if set(entries) != model_ids:
        issues.append("sota-v3 exact-route acceptance entries must exactly match the registered model ids")
    for model in models:
        model_id = str(model.get("id") or "")
        prefix = f"sota-v3 exact-route acceptance entry {model_id!r}"
        entry = entries.get(model_id)
        if not isinstance(entry, dict):
            issues.append(f"{prefix} is missing")
            continue
        expected_identity = v3_route_identity_sha256(registry, model)
        if entry.get("route_identity_sha256") != expected_identity:
            issues.append(f"{prefix} does not bind to the registered route identity")
        if entry.get("authenticated") is not True:
            issues.append(f"{prefix} lacks authenticated route verification")
        if not isinstance(entry.get("verified_at_utc"), str) or not entry["verified_at_utc"].strip():
            issues.append(f"{prefix} authenticated verification timestamp is missing")
        evidence_sha = entry.get("route_evidence_sha256")
        if not isinstance(evidence_sha, str) or re.fullmatch(r"[0-9a-f]{64}", evidence_sha) is None:
            issues.append(f"{prefix} authenticated route evidence digest is missing")
        elif evidence is not None:
            route = evidence_routes.get(model_id) if isinstance(evidence_routes, dict) else None
            if not isinstance(route, dict) or evidence_sha != canonical_sha256(route):
                issues.append(f"{prefix} authenticated route evidence digest does not match its canonical payload")

        privacy = entry.get("privacy_acceptance")
        if not isinstance(privacy, dict) or privacy.get("status") != "accepted":
            issues.append(f"{prefix} privacy acceptance is unresolved")
            continue
        if privacy.get("route_identity_sha256") != expected_identity:
            issues.append(f"{prefix} privacy acceptance does not bind to the registered route identity")
        for field in _PRIVACY_ACCEPTANCE_FIELDS:
            if privacy.get(field) is not True:
                issues.append(f"{prefix} {field} is not accepted")
        zdr_endpoint = privacy.get("zero_data_retention_endpoint")
        if not isinstance(zdr_endpoint, bool):
            issues.append(f"{prefix} zero_data_retention_endpoint must be recorded as a boolean")
        if privacy.get("zero_data_retention_requirement_satisfied") is not True:
            issues.append(f"{prefix} zero_data_retention_requirement_satisfied is not accepted")
        if not isinstance(privacy.get("accepted_at_utc"), str) or not privacy["accepted_at_utc"].strip():
            issues.append(f"{prefix} privacy acceptance timestamp is missing")
        privacy_sha = privacy.get("evidence_sha256")
        if not isinstance(privacy_sha, str) or re.fullmatch(r"[0-9a-f]{64}", privacy_sha) is None:
            issues.append(f"{prefix} privacy evidence digest is missing")
        elif evidence is not None:
            route = evidence_routes.get(model_id) if isinstance(evidence_routes, dict) else None
            if not isinstance(route, dict):
                issues.append(f"{prefix} privacy evidence digest does not match its canonical payload")
            else:
                privacy_evidence = {
                    "route_identity_sha256": route.get("route_identity_sha256"),
                    "privacy_standard": evidence.get("privacy_standard"),
                    "zero_data_retention_endpoint": route.get("zero_data_retention_endpoint"),
                    "provider_policy": route.get("provider_policy"),
                    "official_policy_sources": evidence.get("official_policy_sources"),
                }
                if privacy_sha != canonical_sha256(privacy_evidence):
                    issues.append(f"{prefix} privacy evidence digest does not match its canonical payload")
    return issues


def _v4_labels(issues: list[str]) -> list[str]:
    """Retain the frozen v3 validator while reporting the current lane name."""

    return [issue.replace("sota-v3", "sota-v4") for issue in issues]


def v4_route_identity_sha256(registry: dict[str, Any], model: dict[str, Any]) -> str:
    """Bind v4 evidence to the same route-policy fields as frozen v3."""

    return v3_route_identity_sha256(registry, model)


def v4_route_acceptance_issues(registry: dict[str, Any], *, repo_root: Path | None = None) -> list[str]:
    """Require fresh v4 route evidence without changing frozen v3 behavior."""

    return _v4_labels(v3_route_acceptance_issues(registry, repo_root=repo_root))


def v5_route_identity_sha256(registry: dict[str, Any], model: dict[str, Any]) -> str:
    """Bind v5 route evidence to the frozen route-policy identity fields."""

    return v3_route_identity_sha256(registry, model)


def v5_route_acceptance_issues(registry: dict[str, Any], *, repo_root: Path | None = None) -> list[str]:
    """Validate v5 route evidence, including its explicit contract label."""

    return [issue.replace("sota-v3", "sota-v5") for issue in v3_route_acceptance_issues(registry, repo_root=repo_root)]


def v3_final_preflight_issues(
    lane: dict[str, Any],
    registry: dict[str, Any],
    protocol: dict[str, Any] | None,
    *,
    contract: str = "sota-v3",
    repo_root: Path | None = None,
) -> list[str]:
    """Validate the committed zero-call evidence required before paid smoke.

    A contract-fingerprint change invalidates the earlier authenticated route
    probe and Keychain-backed command rehearsal.  Keeping this as a committed,
    digested artifact makes that freshness requirement executable instead of a
    prose-only operator reminder.
    """

    def labels(values: list[str]) -> list[str]:
        return values if contract == "sota-v3" else [value.replace("sota-v3", contract) for value in values]

    def artifact_path(relative: str) -> Path:
        root = _REPO_ROOT if repo_root is None else repo_root
        path = Path(relative)
        path = path.resolve() if path.is_absolute() else (root / path).resolve()
        try:
            path.relative_to(root.resolve())
        except ValueError as exc:
            raise ValueError("publication artifact path escapes the repository root") from exc
        return path

    issues: list[str] = []
    declaration = lane.get("final_preflight_evidence")
    if not isinstance(declaration, dict) or declaration.get("status") != "accepted":
        return labels(["sota-v3 final-fingerprint preflight evidence is not accepted"])
    relative = declaration.get("artifact")
    if not isinstance(relative, str) or not relative.strip():
        return labels(["sota-v3 final-fingerprint preflight evidence path is missing"])
    try:
        path = artifact_path(relative)
        evidence = json.loads(path.read_text())
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return labels([f"sota-v3 final-fingerprint preflight evidence cannot be read: {exc}"])
    if not isinstance(evidence, dict) or evidence.get("format") != f"gm-bench-{contract}-final-preflight-v1":
        return labels(["sota-v3 final-fingerprint preflight evidence has the wrong format"])
    if evidence.get("contract") != contract:
        issues.append("sota-v3 final-fingerprint preflight evidence is for a different contract label")

    fingerprint = lane.get("contract_fingerprint")
    if evidence.get("contract_fingerprint") != fingerprint or registry.get("contract_fingerprint") != fingerprint:
        issues.append("sota-v3 final-fingerprint preflight evidence is for a different contract")
    from gm_bench.contract import scaffold_fingerprint
    from gm_bench.official import SOTA_V3_POLICY, SOTA_V4_POLICY, SOTA_V5_POLICY

    frozen_policies = {
        "sota-v3": SOTA_V3_POLICY,
        "sota-v4": SOTA_V4_POLICY,
        "sota-v5": SOTA_V5_POLICY,
    }
    expected_policy = frozen_policies.get(contract)
    expected_scaffold = (
        expected_policy.expected_scaffold_fingerprints["openrouter"]
        if expected_policy is not None
        else scaffold_fingerprint("openrouter")
    )
    if evidence.get("openrouter_scaffold_fingerprint") != expected_scaffold:
        issues.append("sota-v3 final-fingerprint preflight evidence is for a different OpenRouter scaffold")
    if evidence.get("completion_calls") != 0:
        issues.append("sota-v3 final-fingerprint preflight evidence must record zero provider completion calls")
    if evidence.get("canonical_openrouter_api_base") != "https://openrouter.ai/api/v1":
        issues.append("sota-v3 final-fingerprint preflight did not pin the canonical OpenRouter API base")

    route = evidence.get("route_preflight")
    acceptance = registry.get("exact_route_acceptance")
    if not isinstance(route, dict) or route.get("status") != "accepted":
        issues.append("sota-v3 final-fingerprint route preflight is not accepted")
    elif not isinstance(acceptance, dict):
        issues.append("sota-v3 exact-route acceptance record is missing")
    else:
        route_path = acceptance.get("evidence_artifact")
        if route.get("evidence_artifact") != route_path:
            issues.append("sota-v3 final preflight points at the wrong route evidence artifact")
        try:
            route_payload = json.loads(artifact_path(str(route_path)).read_text())
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            issues.append(f"sota-v3 final route evidence cannot be read: {exc}")
        else:
            if route_payload.get("contract_fingerprint") != fingerprint:
                issues.append("sota-v3 final route evidence is for a different contract")
            if route_payload.get("format") != "gm-bench-route-acceptance-evidence-v1":
                issues.append("sota-v3 final route evidence has the wrong format")
            if route_payload.get("contract") != contract:
                issues.append("sota-v3 final route evidence is for a different contract label")
            if route_payload.get("completion_calls") != 0:
                issues.append("sota-v3 final route evidence must record zero completion calls")
            if route.get("evidence_sha256") != canonical_sha256(route_payload):
                issues.append("sota-v3 final route evidence digest does not match")
            if route.get("verified_at_utc") != route_payload.get("generated_at_utc"):
                issues.append("sota-v3 final route evidence timestamp does not match")
            if acceptance.get("accepted_at_utc") != route_payload.get("generated_at_utc"):
                issues.append("sota-v3 exact-route acceptance is not from the final route evidence")

    dry_run_key = "smoke_command_dry_run" if contract == "sota-v5" else "keychain_dry_run"
    dry_run = evidence.get(dry_run_key)
    panel = lane.get("seed_panel")
    model_ids = [str(model.get("id") or "") for model in registry.get("models") or [] if isinstance(model, dict)]
    if not isinstance(dry_run, dict) or dry_run.get("status") != "passed":
        issues.append(
            "sota-v3 final smoke-command dry run is not accepted"
            if contract == "sota-v5"
            else "sota-v3 final Keychain-backed dry run is not accepted"
        )
    else:
        if dry_run.get("model_ids") != model_ids or dry_run.get("commands_constructed") != len(model_ids):
            issues.append("sota-v3 final dry run does not cover every registered model")
        if dry_run.get("private_seed_values_included") is not False:
            issues.append("sota-v3 final dry-run evidence must not include private seed values")
        if not isinstance(panel, dict) or dry_run.get("seed_panel_sha256") != panel.get("sha256"):
            issues.append("sota-v3 final dry run does not bind the frozen private seed panel")
        expected_seed_access = contract != "sota-v5"
        if dry_run.get("hiding_commitment_verified") is not expected_seed_access:
            issues.append("sota-v3 final dry run has the wrong private-panel commitment verification state")
        if contract == "sota-v5" and dry_run.get("private_seed_accessed") is not False:
            issues.append("sota-v3 final dry run has the wrong private-seed access state")
        ceiling = declaration.get("operator_ceiling_usd")
        protocol_ceiling = (
            protocol.get("budget_policy", {}).get("operator_ceiling_usd") if isinstance(protocol, dict) else None
        )
        if (
            not isinstance(ceiling, int | float)
            or isinstance(ceiling, bool)
            or not math.isfinite(float(ceiling))
            or float(ceiling) <= 0
            or dry_run.get("operator_ceiling_usd") != ceiling
            or ceiling != protocol_ceiling
        ):
            issues.append("sota-v3 final dry run does not bind the frozen protocol operator ceiling")

    live_preflight = evidence.get("authenticated_route_and_price_preflight")
    if not isinstance(live_preflight, dict) or live_preflight.get("status") != "passed":
        issues.append("sota-v3 final authenticated route and price preflight is not accepted")
    else:
        if live_preflight.get("model_ids") != model_ids or live_preflight.get("commands_executed") != len(model_ids):
            issues.append("sota-v3 final authenticated preflight does not cover every registered model")
        if live_preflight.get("completion_calls") != 0:
            issues.append("sota-v3 final authenticated preflight must record zero completion calls")
        if live_preflight.get("canonical_openrouter_api_base") != "https://openrouter.ai/api/v1":
            issues.append("sota-v3 final authenticated preflight did not pin the canonical OpenRouter API base")
        if live_preflight.get("pricing_checked") is not True:
            issues.append("sota-v3 final authenticated preflight did not verify live route pricing")

    if declaration.get("sha256") != canonical_sha256(evidence):
        issues.append("sota-v3 final-fingerprint preflight evidence digest does not match")
    return list(dict.fromkeys(labels(issues)))


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


def v3_preregistration_coherence_issues(
    lane: dict[str, Any],
    registry: dict[str, Any],
    protocol: dict[str, Any] | None,
    pricing: dict[str, Any] | None,
    manifest: dict[str, Any] | None,
) -> list[str]:
    """Return contradictions among the committed v3 preregistration records.

    Authorization blockers are intentionally not coherence errors. A
    provisional lane should fail closed while still agreeing on the experiment
    it would run after authorization.
    """

    issues = _v3_identity_issues(lane, registry, protocol, pricing, manifest)
    design = lane.get("statistical_panel_design")
    selected = design.get("selected_allocation") if isinstance(design, dict) else None
    plan = protocol.get("statistical_analysis_plan") if isinstance(protocol, dict) else None
    panel = lane.get("seed_panel")
    output_policy = protocol.get("output_policy") if isinstance(protocol, dict) else None
    assumptions = pricing.get("planning_assumptions") if isinstance(pricing, dict) else None

    if lane.get("panel_design_status") != "frozen":
        issues.append("sota-v3 lane panel design must be frozen")
    if not isinstance(design, dict) or design.get("status") != "frozen":
        issues.append("sota-v3 lane statistical panel design must be frozen")
    if not isinstance(plan, dict) or plan.get("status") != "frozen":
        issues.append("sota-v3 protocol statistical analysis plan must be frozen")
    if isinstance(selected, dict):
        if selected.get("repeats") != lane.get("repeats"):
            issues.append("sota-v3 selected allocation repeats must match the lane")
        if not isinstance(panel, dict) or selected.get("seed_count") != panel.get("count"):
            issues.append("sota-v3 selected allocation seed count must match the seed panel")
        selected_seeds = selected.get("seed_count")
        selected_repeats = selected.get("repeats")
        if (
            not isinstance(selected_seeds, int)
            or isinstance(selected_seeds, bool)
            or not isinstance(selected_repeats, int)
            or isinstance(selected_repeats, bool)
            or selected.get("episodes_per_model") != selected_seeds * selected_repeats
        ):
            issues.append("sota-v3 selected allocation episodes_per_model is inconsistent")
    else:
        issues.append("sota-v3 selected allocation is missing")

    models = [model for model in registry.get("models") or [] if isinstance(model, dict)]
    family_size = design.get("holm_family_size") if isinstance(design, dict) else None
    if family_size != len(models):
        issues.append("sota-v3 lane Holm family size must match the registered model count")
    if isinstance(plan, dict):
        if plan.get("holm_family_size") != family_size:
            issues.append("sota-v3 protocol Holm family size must match the lane design")
        if isinstance(design, dict) and plan.get("target_effect_score_points") != design.get(
            "target_effect_score_points"
        ):
            issues.append("sota-v3 protocol target effect must match the lane design")

    cap = lane.get("output_token_cap")
    threshold = lane.get("cap_pressure_threshold_tokens")
    fallback = lane.get("fallback_output_token_cap")
    cap_valid = isinstance(cap, int) and not isinstance(cap, bool) and cap >= 1
    if not cap_valid:
        issues.append("sota-v3 provisional output_token_cap must be a positive integer")
    if not cap_valid or not isinstance(threshold, int) or isinstance(threshold, bool) or not 0 < threshold < cap:
        issues.append("sota-v3 cap-pressure threshold must be between zero and the provisional cap")
    if not cap_valid or not isinstance(fallback, int) or isinstance(fallback, bool) or fallback <= cap:
        issues.append("sota-v3 fallback output cap must exceed the provisional cap")
    if not isinstance(output_policy, dict):
        issues.append("sota-v3 protocol output policy is missing")
    else:
        for key, expected in (
            ("output_token_cap", cap),
            ("cap_pressure_threshold_tokens", threshold),
            ("fallback_output_token_cap", fallback),
        ):
            if output_policy.get(key) != expected:
                issues.append(f"sota-v3 protocol {key} must match the lane")
    if not isinstance(assumptions, dict):
        issues.append("sota-v3 pricing planning assumptions are missing")
    else:
        if assumptions.get("expected_output_tokens_per_decision") != cap:
            issues.append("sota-v3 pricing output-token assumption must match the provisional cap")
        contingency = assumptions.get("cost_contingency_multiplier")
        if not isinstance(contingency, int | float) or isinstance(contingency, bool) or contingency < 1:
            issues.append("sota-v3 pricing cost contingency must be at least one")
    return list(dict.fromkeys(issues))


def v4_preregistration_coherence_issues(
    lane: dict[str, Any],
    registry: dict[str, Any],
    protocol: dict[str, Any] | None,
    pricing: dict[str, Any] | None,
    manifest: dict[str, Any] | None,
) -> list[str]:
    """Apply the frozen v3 structural rules to the new v4 preregistration."""

    return _v4_labels(v3_preregistration_coherence_issues(lane, registry, protocol, pricing, manifest))


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
    if seed_panel.get("name") == "private-env":
        hiding_commitment = seed_panel.get("hiding_commitment_sha256")
        if not isinstance(hiding_commitment, str) or re.fullmatch(r"[0-9a-f]{64}", hiding_commitment) is None:
            issues.append("sota-v3 private seed panel requires a frozen salted hiding commitment")
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
    # Must track the analyzer's own bound in scripts/analyze_publication_panel.py.
    # Raised from 20 with the v6 29-seed panel: the analyzer enumerates by
    # meet-in-the-middle, so 29 seeds cost 2**15 sorted subset sums rather than
    # 2**29 sign assignments, and the test stays exhaustive either way.
    if seed_count > 30:
        issues.append("sota-v3 exact-enumeration-sign-flip requires at most 30 seeds")
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


def v4_statistical_plan_issues(
    lane: dict[str, Any],
    registry: dict[str, Any],
    protocol: dict[str, Any] | None,
) -> list[str]:
    """Validate v4 with v3's frozen statistical method and v4 identity."""

    issues: list[str] = []
    for label, payload in (("lane", lane), ("model registry", registry), ("publication protocol", protocol)):
        if not isinstance(payload, dict) or payload.get("contract") != "sota-v4":
            issues.append(f"sota-v4 {label} must declare contract 'sota-v4'")
    if issues:
        return issues

    lane_copy = dict(lane)
    registry_copy = dict(registry)
    protocol_copy = dict(protocol) if isinstance(protocol, dict) else protocol
    lane_copy["contract"] = "sota-v3"
    registry_copy["contract"] = "sota-v3"
    if isinstance(protocol_copy, dict):
        protocol_copy["contract"] = "sota-v3"
    return _v4_labels(v3_statistical_plan_issues(lane_copy, registry_copy, protocol_copy))


def v5_preregistration_coherence_issues(
    lane: dict[str, Any],
    registry: dict[str, Any],
    protocol: dict[str, Any] | None,
    pricing: dict[str, Any] | None,
    manifest: dict[str, Any] | None,
) -> list[str]:
    """Apply the strict publication design rules to the current v5 lane."""

    return [
        issue.replace("sota-v3", "sota-v5")
        for issue in v3_preregistration_coherence_issues(lane, registry, protocol, pricing, manifest)
    ]


def v5_statistical_plan_issues(
    lane: dict[str, Any],
    registry: dict[str, Any],
    protocol: dict[str, Any] | None,
) -> list[str]:
    """Validate v5 statistical inputs while preserving exact contract identity."""

    issues: list[str] = []
    for label, payload in (("lane", lane), ("model registry", registry), ("publication protocol", protocol)):
        if not isinstance(payload, dict) or payload.get("contract") != "sota-v5":
            issues.append(f"sota-v5 {label} must declare contract 'sota-v5'")
    if issues:
        return issues
    lane_copy = dict(lane)
    registry_copy = dict(registry)
    protocol_copy = dict(protocol) if isinstance(protocol, dict) else protocol
    lane_copy["contract"] = "sota-v3"
    registry_copy["contract"] = "sota-v3"
    if isinstance(protocol_copy, dict):
        protocol_copy["contract"] = "sota-v3"
    return [
        issue.replace("sota-v3", "sota-v5")
        for issue in v3_statistical_plan_issues(lane_copy, registry_copy, protocol_copy)
    ]


def publication_execution_issues(
    lane: dict[str, Any],
    registry: dict[str, Any],
    manifest: dict[str, Any] | None,
    *,
    phase: str,
    protocol: dict[str, Any] | None = None,
    pricing: dict[str, Any] | None = None,
    repo_root: Path | None = None,
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
    if contract in {"sota-v3", "sota-v4", "sota-v5"}:
        coherence_issues = {
            "sota-v3": v3_preregistration_coherence_issues,
            "sota-v4": v4_preregistration_coherence_issues,
            "sota-v5": v5_preregistration_coherence_issues,
        }[contract]
        route_issues = {
            "sota-v3": v3_route_acceptance_issues,
            "sota-v4": v4_route_acceptance_issues,
            "sota-v5": v5_route_acceptance_issues,
        }[contract]
        statistical_issues = {
            "sota-v3": v3_statistical_plan_issues,
            "sota-v4": v4_statistical_plan_issues,
            "sota-v5": v5_statistical_plan_issues,
        }[contract]
        if phase != "route-preflight":
            issues.extend(coherence_issues(lane, registry, protocol, pricing, manifest))
            issues.extend(route_issues(registry, repo_root=repo_root))
            if phase == "smoke":
                issues.extend(
                    v3_final_preflight_issues(
                        lane,
                        registry,
                        protocol,
                        contract=contract,
                        repo_root=repo_root,
                    )
                )
            if (
                not isinstance(protocol, dict)
                or protocol.get("contract") != contract
                or protocol.get("status") != "frozen"
            ):
                issues.append(f"{contract} publication protocol is not frozen")
            if (
                not isinstance(pricing, dict)
                or pricing.get("contract") != contract
                or pricing.get("status") != "frozen"
            ):
                issues.append(f"{contract} pricing snapshot is not frozen")
            issues.extend(statistical_issues(lane, registry, protocol))
        else:
            identity_issues = _v3_identity_issues(lane, registry, protocol, pricing, manifest)
            issues.extend(
                identity_issues
                if contract == "sota-v3"
                else [value.replace("sota-v3", contract) for value in identity_issues]
            )
            if lane.get("route_preflight_authorized") is not True:
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
    if contract in {"sota-v3", "sota-v4", "sota-v5"}:
        budget_policy = protocol.get("budget_policy") if isinstance(protocol, dict) else None
        if not isinstance(budget_policy, dict) or budget_policy.get("spend_authorized") is not True:
            issues.append("provider execution is locked by the publication protocol budget policy")
        if not isinstance(pricing, dict) or pricing.get("spend_authorized") is not True:
            issues.append("provider execution is locked by the pricing snapshot")
    authorization_flag = "smoke_execution_authorized" if phase == "smoke" else "panel_execution_authorized"
    if lane.get(authorization_flag) is not True:
        issues.append(f"provider execution is locked while {authorization_flag} is false")

    if phase == "panel":
        seed_panel = lane.get("seed_panel")
        if contract == "sota-v5" and (
            not isinstance(seed_panel, dict)
            or seed_panel.get("owner_attestation_required") is not True
            or seed_panel.get("owner_attestation_status") != "attested-before-seed-access"
        ):
            issues.append("sota-v5 panel execution requires owner attestation before private seed access")
        if registry.get("panel_execution_authorized") is not True:
            issues.append("panel execution is locked by the model registry")
        if not isinstance(manifest, dict) or manifest.get("accepted_for_panel") is not True:
            issues.append(f"{contract} smoke manifest is not accepted for panel execution")
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
