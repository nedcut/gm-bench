"""GM-Bench 2.2 (draft): a fork of the agent-facing surface on top of 2.1.

Nothing here edits a 1.0, 2.0 or 2.1 contract source. 2.1 could reuse the 2.0
tools and brief unchanged; 2.2 changes what the agent is told, and the frozen
engine and server bind the 2.0 tool list and brief at import time, so 2.2
carries its own copies of those two and subclasses the rest:

- ``tools``       the tool surface (forked from ``gm_bench/agentic/tools.py``)
- ``brief``       the task brief (forked from ``gm_bench/agentic/brief.py``)
- ``episode``     ``AgenticEpisode22``: the frozen engine bound to the 2.2 tools
- ``mcp_server``  the frozen server bound to the 2.2 tools and brief
- ``contract``    the 2.2 contract block and fingerprint over these files

Draft: no fingerprint is pinned and no row may be published under it. Plan and
status: ``docs/bench_v2_2_spec.md``.
"""
