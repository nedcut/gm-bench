"""Stateless providers for the experimental context-policy protocol; never used by 2.0."""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any


def scripted(request: dict[str, Any], model: dict[str, Any], controls: dict[str, Any]) -> dict[str, Any]:
    """A deliberately simple fixture: remember reviewing rules, then end each phase."""
    journal = request["journal"]
    if not request["history"]:
        tool = "get_status"
    elif "rules reviewed" not in journal["facts"]:
        tool = "get_rules"
    else:
        tool = "end_phase"
    if tool == "get_rules":
        journal = {"facts": ["rules reviewed"], "plan": ["finish phase"], "decisions": []}
    return {
        "content": json.dumps({"tool": tool, "arguments": {}, "journal": journal}),
        "model": model["requested"],
        "system_fingerprint": "scripted-rules-v1",
        "usage": {"prompt_tokens": 0, "completion_tokens": 0},
    }


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward the authorization header to a redirect target.
        return None


def openai_chat(request: dict[str, Any], model: dict[str, Any], controls: dict[str, Any]) -> dict[str, Any]:
    """One request, no retry or conversation/session state. Caller gates spending."""
    payload = {
        "model": model["requested"],
        "messages": [
            {"role": "system", "content": request["instructions"]},
            {"role": "user", "content": json.dumps({k: v for k, v in request.items() if k != "instructions"})},
        ],
        "temperature": 0,
        "max_completion_tokens": controls["max_output_tokens"],
        "response_format": {"type": "json_object"},
        "store": False,
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + os.environ["OPENAI_API_KEY"], "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.build_opener(NoRedirect()).open(req, timeout=controls["socket_timeout_seconds"]) as response:
        body = json.load(response)
    return {
        "content": body["choices"][0]["message"]["content"],
        "model": body.get("model"),
        "system_fingerprint": body.get("system_fingerprint"),
        "usage": body.get("usage"),
        "request_id": body.get("id"),
    }


def anthropic_messages(request: dict[str, Any], model: dict[str, Any], controls: dict[str, Any]) -> dict[str, Any]:
    """One Messages API request, no retry or conversation state. Caller gates spending.

    No sampling parameters are sent: current Claude models reject them. Adaptive
    thinking and the registered effort are explicit so model defaults cannot drift
    between cells. Thinking tokens count against max_tokens and output usage.
    """
    payload = {
        "model": model["requested"],
        "max_tokens": controls["max_output_tokens"],
        "system": request["instructions"],
        "messages": [
            {"role": "user", "content": json.dumps({k: v for k, v in request.items() if k != "instructions"})}
        ],
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": model["effort"]},
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(payload).encode(),
        headers={
            "x-api-key": os.environ["ANTHROPIC_API_KEY"],
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.build_opener(NoRedirect()).open(req, timeout=controls["socket_timeout_seconds"]) as response:
        body = json.load(response)
    raw = body.get("usage") or {}
    # Billed input is uncached plus cache writes and reads; a missing input count stays unavailable.
    parts = [raw.get("input_tokens"), raw.get("cache_creation_input_tokens", 0), raw.get("cache_read_input_tokens", 0)]
    return {
        # Only text blocks are the action; thinking blocks are not part of the protocol.
        "content": "".join(block.get("text", "") for block in body.get("content") or [] if block.get("type") == "text"),
        "model": body.get("model"),
        "system_fingerprint": None,
        "usage": {
            "prompt_tokens": sum(parts) if all(type(v) is int for v in parts) else None,
            "completion_tokens": raw.get("output_tokens"),
        },
        "stop_reason": body.get("stop_reason"),
        "request_id": body.get("id"),
    }
