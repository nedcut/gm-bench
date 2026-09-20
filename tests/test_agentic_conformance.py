"""The hand-written server against the official MCP Python SDK client.

This is the guard the spec asks for: the package ships no MCP dependency, so
the SDK lives in the dev extras only and is used here purely as a client. If
the protocol drifts under us, this test is what notices.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

from gm_bench.agentic.mcp_server import EPISODE_ENV
from gm_bench.agentic.tools import TOOLS

mcp = pytest.importorskip("mcp")
from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_official_sdk_client_completes_a_season(tmp_path: Path) -> None:
    episode_file = tmp_path / "episode.json"
    episode_file.write_text(
        json.dumps({"seed": 11, "seasons": 1, "user_team_id": 0, "ledger_path": str(tmp_path / "ledger.jsonl")})
    )
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "gm_bench.agentic.mcp_server"],
        env={**os.environ, EPISODE_ENV: str(episode_file), "PYTHONPATH": str(REPO_ROOT)},
    )

    async def drive() -> dict:
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            init = await session.initialize()
            listing = await session.list_tools()
            names = [tool.name for tool in listing.tools]
            status = await session.call_tool("get_status", {})
            bad = await session.call_tool("draft", {"prospect_id": 1})
            closes = []
            for _ in range(4):
                closes.append(await session.call_tool("end_phase", {}))
            after = await session.call_tool("get_status", {})
            server_info = getattr(init, "server_info", None) or getattr(init, "serverInfo")
            return {
                "server": server_info.name,
                "instructions": init.instructions,
                "names": names,
                "status": status,
                "bad": bad,
                "last": closes[-1],
                "after": after,
            }

    outcome = asyncio.run(drive())
    assert outcome["server"] == "gm-bench"
    assert "get_status" in outcome["instructions"]
    assert outcome["names"] == [tool["name"] for tool in TOOLS]
    assert _is_error(outcome["status"]) is False
    assert _structured(outcome["status"])["data"]["phase"] == "preseason"
    assert _is_error(outcome["bad"]) is True
    assert _structured(outcome["last"])["episode_complete"] is True
    assert _is_error(outcome["after"]) is True


def _is_error(result: object) -> bool:
    # SDK v1 exposes camelCase wire names, v2 snake_case; accept either.
    value = getattr(result, "is_error", None)
    return bool(getattr(result, "isError") if value is None else value)


def _structured(result: object) -> dict:
    value = getattr(result, "structured_content", None)
    return getattr(result, "structuredContent") if value is None else value
