"""Usage, latency, and cost telemetry for model-backed runs.

Adapters report per-decision usage through the stdout envelope
(``{"actions": [...], "usage": {...}}``). This module normalizes those
untrusted payloads, prices them against a per-model table, and aggregates
them into the per-episode block the runner attaches to results.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

_PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_PRICING_PATH = _PACKAGE_DIR / "pricing.json"

_COUNT_KEYS = (
    "api_calls",
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "total_tokens",
    "protocol_repair_attempts",
    "protocol_repairs_succeeded",
)
_FLOAT_KEYS = ("api_latency_ms", "cost_usd")
_TEXT_KEYS = ("provider", "model", "upstream_provider", "generation_id")


def normalize_usage(raw: Any) -> dict[str, Any] | None:
    """Coerce an adapter-reported usage block into the canonical shape.

    Adapters are external processes, so usage is untrusted input: unknown keys
    are dropped and a malformed value discards that field, never the decision.
    Returns None when nothing usable was reported.
    """
    if not isinstance(raw, dict):
        return None
    usage: dict[str, Any] = {}
    for key in _COUNT_KEYS:
        value = raw.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
            usage[key] = int(value)
    for key in _FLOAT_KEYS:
        value = raw.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
            usage[key] = round(float(value), 6)
    for key in _TEXT_KEYS:
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            usage[key] = value.strip()[:200]
    if "total_tokens" not in usage and ("input_tokens" in usage or "output_tokens" in usage):
        usage["total_tokens"] = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
    return usage or None


def _load_pricing_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


@lru_cache(maxsize=1)
def pricing_table() -> dict[str, Any]:
    """Model pricing in USD per million tokens, with GM_BENCH_PRICING overrides.

    The override file uses the same shape as pricing.json and wins key-by-key,
    so users can correct or extend prices without editing the package.
    """
    table = _load_pricing_file(DEFAULT_PRICING_PATH)
    override_path = os.environ.get("GM_BENCH_PRICING")
    if override_path:
        override = _load_pricing_file(Path(override_path))
        merged_models = {**table.get("models", {}), **override.get("models", {})}
        merged_providers = {**table.get("providers", {}), **override.get("providers", {})}
        table = {"models": merged_models, "providers": merged_providers}
    table.setdefault("models", {})
    table.setdefault("providers", {})
    return table


def price_for(model: str | None, provider: str | None = None) -> dict[str, float] | None:
    """Resolve a price entry: exact model id, longest model prefix, then provider default."""
    table = pricing_table()
    models = table["models"]
    if model:
        key = model.lower()
        if key in models:
            return models[key]
        prefix_matches = [candidate for candidate in models if key.startswith(candidate)]
        if prefix_matches:
            return models[max(prefix_matches, key=len)]
    if provider and provider.lower() in table["providers"]:
        return table["providers"][provider.lower()]
    return None


def estimate_cost_usd(usage: dict[str, Any]) -> float | None:
    """Cost for one decision's usage. Adapter-reported cost is authoritative.

    Returns None when the model is unpriced or token counts are missing —
    an unknown cost must never silently read as free on a cost leaderboard.
    """
    if "cost_usd" in usage:
        return usage["cost_usd"]
    price = price_for(usage.get("model"), usage.get("provider"))
    if price is None:
        return None
    if "input_tokens" not in usage and "output_tokens" not in usage:
        return None
    input_cost = usage.get("input_tokens", 0) / 1e6 * price.get("input_per_mtok", 0.0)
    output_cost = usage.get("output_tokens", 0) / 1e6 * price.get("output_per_mtok", 0.0)
    return round(input_cost + output_cost, 6)


def aggregate_usage(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Fold per-decision usage records into one episode-level block."""
    totals = {key: sum(int(record.get(key, 0)) for record in records) for key in _COUNT_KEYS}
    priced_records = [(record, estimate_cost_usd(record)) for record in records]
    costs = [cost for _record, cost in priced_records if cost is not None]
    models = Counter(record["model"] for record in records if record.get("model"))
    providers = Counter(record["provider"] for record in records if record.get("provider"))
    upstream_providers = Counter(record["upstream_provider"] for record in records if record.get("upstream_provider"))
    observed_upstreams = {
        str(upstream) for record in records for upstream in (record.get("upstream_providers") or []) if upstream
    }
    observed_upstreams.update(str(record["upstream_provider"]) for record in records if record.get("upstream_provider"))
    # A multi-round decision window emits one usage record per round; coverage
    # must count decision points, not rounds, or extra rounds on one decision
    # would mask missing usage on another (and pass the sota-v2 coverage gate).
    decision_keys = {
        (record["season"], record["phase"])
        for record in records
        if record.get("season") is not None and record.get("phase")
    }
    costs_by_decision: dict[tuple[Any, Any], list[float | None]] = {}
    for record, cost in priced_records:
        if record.get("season") is not None and record.get("phase"):
            costs_by_decision.setdefault((record["season"], record["phase"]), []).append(cost)
    cost_decision_keys = {
        key for key, decision_costs in costs_by_decision.items() if all(c is not None for c in decision_costs)
    }
    return {
        "decisions_with_usage": len(decision_keys) if decision_keys else len(records),
        **totals,
        "api_latency_ms": round(sum(float(record.get("api_latency_ms", 0.0)) for record in records), 1),
        "cost_usd": round(sum(costs), 6) if costs else None,
        "cost_decisions": len(cost_decision_keys) if decision_keys else len(costs),
        "model": models.most_common(1)[0][0] if models else None,
        "provider": providers.most_common(1)[0][0] if providers else None,
        "upstream_provider": upstream_providers.most_common(1)[0][0] if upstream_providers else None,
        "upstream_providers": sorted(observed_upstreams),
    }


def summarize_usage(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    """Fold per-episode usage blocks into the run-level summary block.

    Tolerates episodes with no usage key (old cache entries, scripted agents).
    """
    blocks = [episode.get("usage") or {} for episode in episodes]
    totals = {key: sum(int(block.get(key, 0)) for block in blocks) for key in _COUNT_KEYS}
    costs = [block["cost_usd"] for block in blocks if block.get("cost_usd") is not None]
    decisions_with_usage = sum(int(block.get("decisions_with_usage", 0)) for block in blocks)
    cost_decisions = sum(int(block.get("cost_decisions", 0)) for block in blocks)
    harness_ms = sum(float(block.get("harness_latency_ms", 0.0)) for block in blocks)
    models = Counter(block["model"] for block in blocks if block.get("model"))
    providers = Counter(block["provider"] for block in blocks if block.get("provider"))
    upstream_providers = Counter(block["upstream_provider"] for block in blocks if block.get("upstream_provider"))
    observed_upstreams = {
        str(upstream) for block in blocks for upstream in (block.get("upstream_providers") or []) if upstream
    }
    observed_upstreams.update(upstream_providers)
    return {
        "decisions_with_usage": decisions_with_usage,
        "cost_decisions": cost_decisions,
        **totals,
        "api_latency_ms": round(sum(float(block.get("api_latency_ms", 0.0)) for block in blocks), 1),
        "harness_latency_ms": round(harness_ms, 1),
        "cost_usd": round(sum(costs), 6) if costs else None,
        "mean_tokens_per_decision": round(totals["total_tokens"] / decisions_with_usage, 1)
        if decisions_with_usage
        else 0.0,
        "mean_input_tokens_per_decision": round(totals["input_tokens"] / decisions_with_usage, 1)
        if decisions_with_usage
        else 0.0,
        "mean_output_tokens_per_decision": round(totals["output_tokens"] / decisions_with_usage, 1)
        if decisions_with_usage
        else 0.0,
        "model": models.most_common(1)[0][0] if models else None,
        "provider": providers.most_common(1)[0][0] if providers else None,
        "upstream_provider": upstream_providers.most_common(1)[0][0] if upstream_providers else None,
        "upstream_providers": sorted(observed_upstreams),
    }
