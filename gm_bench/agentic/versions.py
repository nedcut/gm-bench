"""Which agentic contract a run is played and checked under.

2.0 (``gm-bench-2.0``) is frozen and stays the default. 2.1
(``gm-bench-2.1``, ``gm_bench/v21``) plays the same engine and tools on the
2.1 league and score-v2. A run records its contract block in ``run.json`` and
each ledger header names its version (2.0 ledgers predate the field), so the
validator replays and checks every run under its own contract rather than
under whatever this checkout plays by default.

2.2 (``gm_bench/v22``, a draft) forks what the agent is told, so a contract
also names the brief and the socket server a driver must use with its engine.
"""

from __future__ import annotations

from pathlib import Path
from types import ModuleType
from typing import Any, Callable

from gm_bench.agentic import brief as agentic_brief
from gm_bench.agentic.contract import AGENTIC_BENCHMARK_VERSION, agentic_contract
from gm_bench.agentic.episode import AgenticEpisode
from gm_bench.agentic.mcp_server import SocketMcpServer
from gm_bench.v21 import contract as v21_contract
from gm_bench.v21.episode import AgenticEpisode21, ledger_benchmark_version
from gm_bench.v22 import brief as v22_brief
from gm_bench.v22 import contract as v22_contract
from gm_bench.v22.episode import AgenticEpisode22
from gm_bench.v22.mcp_server import SocketMcpServer22

DEFAULT_VERSION = AGENTIC_BENCHMARK_VERSION
_CONTRACTS: dict[str, tuple[Callable[[], dict[str, Any]], type[AgenticEpisode]]] = {
    AGENTIC_BENCHMARK_VERSION: (agentic_contract, AgenticEpisode),
    v21_contract.BENCHMARK_VERSION: (v21_contract.contract, AgenticEpisode21),
    v22_contract.BENCHMARK_VERSION: (v22_contract.contract, AgenticEpisode22),
}
# What the agent is served, for the contracts that fork it; the rest use 2.0's.
_SURFACES: dict[str, tuple[ModuleType, type[SocketMcpServer]]] = {
    v22_contract.BENCHMARK_VERSION: (v22_brief, SocketMcpServer22),
}
#: Short names accepted on the command line.
ALIASES = {
    "2.0": AGENTIC_BENCHMARK_VERSION,
    "2.1": v21_contract.BENCHMARK_VERSION,
    "2.2-draft": v22_contract.BENCHMARK_VERSION,
}
VERSIONS = tuple(_CONTRACTS)


def resolve(version: str | None) -> str:
    name = ALIASES.get(version or DEFAULT_VERSION, version or DEFAULT_VERSION)
    if name not in _CONTRACTS:
        raise ValueError(f"unknown agentic contract {version!r}; known: {', '.join(VERSIONS)}")
    return name


def contract_block(version: str | None = None) -> dict[str, Any]:
    return _CONTRACTS[resolve(version)][0]()


def episode_class(version: str | None = None) -> type[AgenticEpisode]:
    return _CONTRACTS[resolve(version)][1]


def brief_module(version: str | None = None) -> ModuleType:
    """The module holding ``task_brief`` and ``nudge_message`` for a contract."""
    return _SURFACES.get(resolve(version), (agentic_brief, SocketMcpServer))[0]


def socket_server_class(version: str | None = None) -> type[SocketMcpServer]:
    """The socket server that serves a contract's tool surface and instructions."""
    return _SURFACES.get(resolve(version), (agentic_brief, SocketMcpServer))[1]


def replay_ledger(ledger_path: str | Path, *, reopen: bool = True) -> AgenticEpisode:
    """Rebuild an episode from its ledger with the engine of the contract it names."""
    return episode_class(ledger_benchmark_version(ledger_path)).from_ledger(ledger_path, reopen=reopen)
