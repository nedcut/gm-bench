"""Publication-safe result artifacts.

Raw model runs are durable local evidence, but their observation and transaction
traces are too large (and sometimes sensitive) for git.  Published artifacts
retain the aggregates, per-seed outcomes, usage, and a hash of the raw input.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

PUBLICATION_FORMAT = "gm-bench-result-summary-v1"


def canonical_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def compact_result(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a validator-compatible artifact without verbose episode traces."""
    if payload.get("publication"):
        raise ValueError("input already has publication metadata; compact the original raw artifact")
    result = copy.deepcopy(payload)
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
        "memo_writes",
        "rejected_offers",
    )
    compact = {key: episode[key] for key in keep if key in episode}
    usage = copy.deepcopy(episode.get("usage") or {})
    usage.pop("per_decision", None)
    if usage:
        compact["usage"] = usage
    return compact


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
