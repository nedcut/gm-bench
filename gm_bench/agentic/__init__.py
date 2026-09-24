"""GM-Bench 2.0: the agentic lane.

The simulator is unchanged. What changes is who owns the loop: instead of the
runner prompting a model once per decision phase, the model's own harness
(OpenCode, Claude Code, Codex CLI, ...) drives one continuous session per
episode through a Model Context Protocol (MCP) tool server.

Modules:

- ``tools``     the frozen tool surface (names, descriptions, input schemas)
- ``brief``     the task brief handed to the agent at session start
- ``episode``   the episode engine: phases, moves, ledger, replay, scoring
- ``mcp_server`` the stdio JSON-RPC server a harness spawns
- ``harness``   the interface a harness driver implements
- ``opencode``  the first harness driver, and the episode loop every driver shares
- ``codex``     the Codex CLI driver
- ``claude``    the Claude Code driver (same-user isolation only)
- ``container`` the Docker launcher for container isolation
"""
