"""Protocol-perfect scripted adapter for harness conformance checks.

This agent never calls a model. Every decision it emits a legal query plus a
memo, then closes the window with end_turn on the follow-up round, always with
a usage envelope. Run through the real external-process path (one-shot and
session), a conformant harness must record zero failed decisions, zero illegal
actions, zero protocol penalty, and usage on every decision point — so any
nonzero count isolates a harness/adapter-layer bug from model behavior.

    python -m gm_bench run --agent-cmd "python examples/conformance_agent.py"
"""

from __future__ import annotations

from typing import Any

try:
    from gm_agent_common import make_usage, run_agent_main
except ModuleNotFoundError:
    from examples.gm_agent_common import make_usage, run_agent_main


def _usage() -> dict[str, Any] | None:
    return make_usage(
        provider="conformance",
        model="scripted-perfect",
        api_calls=1,
        input_tokens=1,
        output_tokens=1,
        api_latency_ms=0.0,
    )


def choose_actions(observation: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    follow_up = (
        observation.get("phase") == "action_results"
        or observation.get("action_results")
        or observation.get("interaction_round", 0) > 0
    )
    if follow_up:
        return [{"type": "end_turn"}], _usage()
    return (
        [
            {"type": "list_free_agents"},
            {"type": "memo", "text": "conformance probe"},
        ],
        _usage(),
    )


if __name__ == "__main__":
    run_agent_main(choose_actions)
