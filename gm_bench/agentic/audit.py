"""Post-hoc audit of an agentic ledger.

The sandbox keeps hidden state out of the agent's reach; this audit is the
detection layer behind it (docs/bench_v2_spec.md, "Sandbox"). The only
legitimate way for an agent to learn a player, prospect, team or offer id is
a tool reply, and every reply's ids are recorded in the ledger. A move that
names an id no earlier reply exposed is therefore either a guess or a leak.

Both are reported, never silently dropped: an *accepted* move on an unseen id
is a ``violation`` (it changed the league on information the tools did not
provide), a *rejected* one is ``suspicious`` (a guess that missed). Publication
decides what to do with each; the audit only states the facts.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from gm_bench.agentic.tools import TOOLS_BY_NAME

# Argument keys that name entities, per move tool.
_ENTITY_ARGUMENTS = {
    "player_id": "player",
    "prospect_id": "prospect",
    "team_id": "team",
    "partner_team_id": "team",
    "offer_id": "offer",
    "give_player_ids": "player",
    "receive_player_ids": "player",
    "player_ids": "player",
}


def load_ledger(source: str | Path | list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(source, list):
        return source
    text = Path(source).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def audit_ledger(source: str | Path | list[dict[str, Any]]) -> dict[str, Any]:
    """Check every move against the ids exposed before it."""
    records = load_ledger(source)
    calls = [record for record in records if record.get("event") == "tool_call"]
    if calls and not any("ids_exposed" in record for record in calls):
        # A ledger written before replies recorded their ids cannot separate
        # fetched ids from guessed ones; say so instead of calling every move a leak.
        return {
            "auditable": False,
            "moves": 0,
            "ids_exposed": 0,
            "violations": [],
            "suspicious": [],
            "clean": False,
            "note": "ledger has no ids_exposed records; audit not possible",
        }
    seen: set[int | str] = set()
    violations: list[dict[str, Any]] = []
    suspicious: list[dict[str, Any]] = []
    moves = 0
    for record in records:
        if record.get("event") != "tool_call" or not record.get("executed", True):
            continue
        tool = record.get("tool")
        spec = TOOLS_BY_NAME.get(tool)
        if spec is None:
            continue
        if spec["kind"] in {"move", "query"} and tool != "write_memo":
            referenced = _referenced_ids(record.get("arguments") or {})
            unseen = sorted((value for value in referenced if value not in seen), key=str)
            if spec["kind"] == "move":
                moves += 1
            if unseen:
                finding = {
                    "seq": record.get("seq"),
                    "season": record.get("season"),
                    "phase": record.get("phase"),
                    "tool": tool,
                    "unseen_ids": unseen,
                    "accepted": bool(record.get("ok")),
                }
                # A rejected query on a bad id is ordinary exploration; a
                # move on an unseen id is what the audit exists for.
                if spec["kind"] == "move" and record.get("ok"):
                    violations.append(finding)
                elif spec["kind"] == "move":
                    suspicious.append(finding)
        seen.update(record.get("ids_exposed") or [])
    return {
        "auditable": True,
        "moves": moves,
        "ids_exposed": len(seen),
        "violations": violations,
        "suspicious": suspicious,
        "clean": not violations,
    }


def _referenced_ids(arguments: dict[str, Any]) -> set[int | str]:
    referenced: set[int | str] = set()
    for key, value in arguments.items():
        if key not in _ENTITY_ARGUMENTS:
            continue
        if isinstance(value, list):
            referenced.update(v for v in value if isinstance(v, (int, str)) and not isinstance(v, bool))
        elif isinstance(value, (int, str)) and not isinstance(value, bool):
            referenced.add(value)
    return referenced
