#!/usr/bin/env python3
"""Collect authenticated, zero-completion route and privacy evidence for SOTA-v3.

The collector reads only OpenRouter metadata endpoints. It never sends a model
prompt, never creates a completion, and never records the account balance or API
key. With ``--apply-registry`` it freezes exact-route acceptance against the
generated evidence artifact after every registered route passes.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gm_bench.environment import load_environment_files  # noqa: E402
from gm_bench.publication import (  # noqa: E402
    canonical_sha256,
    is_pending_strict_smoke_cap,
    v3_route_identity_sha256,
)

PRIVACY_STANDARD = {
    "data_classification": "synthetic-benchmark-no-personal-or-confidential-data",
    "provider_data_collection": "deny",
    "provider_training_use_allowed": False,
    "provider_retention_terms": "reviewed-and-accepted-for-synthetic-benchmark",
    "zero_data_retention_required": False,
    "zero_data_retention_preferred": True,
}
POLICY_SOURCES = [
    "https://openrouter.ai/docs/guides/features/zdr",
    "https://openrouter.ai/docs/guides/privacy/provider-logging/",
    "https://openrouter.ai/docs/guides/routing/provider-selection",
    "https://openrouter.ai/docs/api/api-reference/endpoints/list-endpoints-zdr",
]


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _get_json(path: str, headers: dict[str, str]) -> dict[str, Any]:
    parsed = urllib.parse.urlsplit(path)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith("/api/v1/") or parsed.path != path:
        raise ValueError(f"refusing non-OpenRouter metadata path: {path!r}")
    # The TLS host is a literal and the request path is constrained to /api/v1/ above.
    connection = http.client.HTTPSConnection(  # nosemgrep: python.lang.security.audit.httpsconnection-detected.httpsconnection-detected
        "openrouter.ai", timeout=30
    )
    try:
        connection.request("GET", path, headers=headers)
        response = connection.getresponse()
        if response.status < 200 or response.status >= 300:
            raise RuntimeError(f"OpenRouter metadata request failed with HTTP {response.status}")
        payload = json.load(response)
    finally:
        connection.close()
    if not isinstance(payload, dict):
        raise ValueError(f"{path} did not return a JSON object")
    return payload


def _exact_endpoint(model: dict[str, Any], endpoints: list[dict[str, Any]]) -> dict[str, Any]:
    matches = [
        endpoint
        for endpoint in endpoints
        if endpoint.get("provider_name") == model.get("upstream_provider")
        and endpoint.get("tag") == model.get("endpoint_tag")
        and endpoint.get("name") == model.get("endpoint_name")
        and endpoint.get("status") == 0
    ]
    if len(matches) != 1:
        raise ValueError(f"{model.get('id')}: expected one healthy exact endpoint, found {len(matches)}")
    return matches[0]


def _public_endpoint_record(endpoint: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider_name": endpoint.get("provider_name"),
        "tag": endpoint.get("tag"),
        "name": endpoint.get("name"),
        "status": endpoint.get("status"),
        "max_completion_tokens": endpoint.get("max_completion_tokens"),
        "supported_parameters": sorted(str(value) for value in endpoint.get("supported_parameters") or []),
        "uptime_last_30m": endpoint.get("uptime_last_30m"),
        "uptime_last_1d": endpoint.get("uptime_last_1d"),
    }


def collect(registry: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    # A successful authenticated credits read proves the bearer token is valid;
    # no balance or usage value is retained in the evidence artifact.
    _get_json("/api/v1/credits", headers)
    zdr_rows = _get_json("/api/v1/endpoints/zdr", headers).get("data") or []
    providers = _get_json("/api/v1/providers", headers).get("data") or []
    provider_by_slug = {str(row.get("slug")): row for row in providers if isinstance(row, dict)}
    zdr_identities = {
        (row.get("model_id"), row.get("provider_name"), row.get("tag"), row.get("name"))
        for row in zdr_rows
        if isinstance(row, dict)
    }
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    routes: dict[str, Any] = {}
    cap = registry.get("output_token_cap")
    for model in registry.get("models") or []:
        model_id = str(model["id"])
        model_path = urllib.parse.quote(str(model["model"]), safe="/")
        endpoint_payload = _get_json(f"/api/v1/models/{model_path}/endpoints", headers)
        endpoint = _exact_endpoint(model, list((endpoint_payload.get("data") or {}).get("endpoints") or []))
        supported = set(endpoint.get("supported_parameters") or [])
        required = {"max_tokens", "reasoning", "response_format"}
        if not required <= supported:
            raise ValueError(f"{model_id}: exact endpoint is missing {sorted(required - supported)}")
        maximum = endpoint.get("max_completion_tokens")
        if isinstance(maximum, int) and not isinstance(maximum, bool) and isinstance(cap, int) and maximum >= cap:
            cap_status = "endpoint-metadata-verified"
        elif maximum is None and is_pending_strict_smoke_cap(model.get("output_cap_verification")):
            cap_status = "request-cap-pending-strict-smoke"
        else:
            raise ValueError(f"{model_id}: exact endpoint does not establish the registered {cap}-token cap")
        slug = str(model["upstream_provider_slug"]).split("/", 1)[0]
        provider = provider_by_slug.get(slug)
        if not isinstance(provider, dict):
            raise ValueError(f"{model_id}: OpenRouter provider policy record {slug!r} is missing")
        identity = (
            model.get("model"),
            model.get("upstream_provider"),
            model.get("endpoint_tag"),
            model.get("endpoint_name"),
        )
        route_identity = v3_route_identity_sha256(registry, model)
        routes[model_id] = {
            "route_identity_sha256": route_identity,
            "endpoint": _public_endpoint_record(endpoint),
            "authenticated_metadata_read": True,
            "output_cap_verification_status": cap_status,
            "zero_data_retention_endpoint": identity in zdr_identities,
            "provider_policy": {
                "provider_slug": slug,
                "privacy_policy_url": provider.get("privacy_policy_url"),
                "terms_of_service_url": provider.get("terms_of_service_url"),
            },
        }
    return {
        "format": "gm-bench-route-acceptance-evidence-v1",
        "schema_version": 1,
        "contract": registry.get("contract"),
        "contract_fingerprint": registry.get("contract_fingerprint"),
        "generated_at_utc": generated_at,
        "completion_calls": 0,
        "account_authentication": {
            "status": "authenticated",
            "method": "OpenRouter credits metadata endpoint returned success",
            "sensitive_values_included": False,
        },
        "official_policy_sources": POLICY_SOURCES,
        "privacy_standard": PRIVACY_STANDARD,
        "routes": routes,
    }


def apply_registry(registry: dict[str, Any], evidence: dict[str, Any], evidence_path: Path) -> dict[str, Any]:
    accepted_at = str(evidence["generated_at_utc"])
    entries: dict[str, Any] = {}
    for model in registry.get("models") or []:
        model_id = str(model["id"])
        route = evidence["routes"][model_id]
        privacy_evidence = {
            "route_identity_sha256": route["route_identity_sha256"],
            "privacy_standard": evidence["privacy_standard"],
            "zero_data_retention_endpoint": route["zero_data_retention_endpoint"],
            "provider_policy": route["provider_policy"],
            "official_policy_sources": evidence["official_policy_sources"],
        }
        entries[model_id] = {
            "route_identity_sha256": route["route_identity_sha256"],
            "authenticated": True,
            "verified_at_utc": accepted_at,
            "route_evidence_sha256": canonical_sha256(route),
            "privacy_acceptance": {
                "status": "accepted",
                "route_identity_sha256": route["route_identity_sha256"],
                "data_collection_policy_accepted": True,
                "retention_policy_accepted": True,
                "training_use_policy_accepted": True,
                "zero_data_retention_endpoint": route["zero_data_retention_endpoint"],
                "zero_data_retention_requirement_satisfied": True,
                "accepted_at_utc": accepted_at,
                "evidence_sha256": canonical_sha256(privacy_evidence),
            },
        }
    registry["selection_status"] = "frozen"
    registry["selection_frozen_at_utc"] = accepted_at
    registry["exact_route_acceptance"] = {
        "schema_version": 2,
        "status": "accepted",
        "accepted_at_utc": accepted_at,
        "evidence_artifact": str(evidence_path.relative_to(ROOT)),
        "privacy_standard": evidence["privacy_standard"],
        "entries": entries,
    }
    return registry


def _write_json(path: Path, payload: dict[str, Any], *, sort_keys: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=sort_keys, allow_nan=False) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=ROOT / "config" / "sota_v3_models.json")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "results" / "analysis" / "sota-v3-route-acceptance-evidence.json",
    )
    parser.add_argument("--apply-registry", action="store_true")
    args = parser.parse_args(argv)
    root = ROOT.resolve()
    output = args.output.resolve()
    registry_path = args.registry.resolve()
    for label, path in (("evidence output", output), ("registry", registry_path)):
        if not path.is_relative_to(root):
            parser.error(f"{label} must be inside the repository")
    load_environment_files(ROOT)
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        parser.error("OPENROUTER_API_KEY is required")
    headers = {
        "Authorization": f"Bearer {key}",
        "User-Agent": "gm-bench-route-evidence/1",
    }
    registry = _read_json(registry_path)
    evidence = collect(registry, headers)
    _write_json(output, evidence)
    if args.apply_registry:
        _write_json(registry_path, apply_registry(registry, evidence, output), sort_keys=False)
    print(
        json.dumps(
            {
                "status": "accepted" if args.apply_registry else "collected",
                "completion_calls": 0,
                "routes": len(evidence["routes"]),
                "zdr_routes": sum(route["zero_data_retention_endpoint"] for route in evidence["routes"].values()),
                "output": str(output.relative_to(ROOT)),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
