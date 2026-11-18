"""The 2.2 agentic episode: the frozen engine bound to the 2.2 tool surface.

Contract source for 2.2 (fingerprinted by ``gm_bench.v22.contract``).
``AgenticEpisode`` is a 2.0 contract source and stays byte for byte. It reads
the 2.0 tool list as a module global, so the two methods that do
(``_execute`` and ``_legal_tools``) are restated here against
``gm_bench.v22.tools``; everything else is inherited.

Phase 0 of the 2.2 build: the league and the score are still 2.1's
(``league_class`` and ``scoring`` below), so a 2.1 ledger replayed through
this engine ends in the same league with the same score.
"""

from __future__ import annotations

from typing import Any

from gm_bench.agentic.episode import ENDED_BY_AGENT, AgenticEpisode
from gm_bench.scoring import breakdown_from_components
from gm_bench.v21 import scoring as score_v2
from gm_bench.v21.rules import League21
from gm_bench.v22.contract import BENCHMARK_VERSION
from gm_bench.v22.tools import (
    ACTION_TYPE_FOR_TOOL,
    TOOL_SURFACE_VERSION,
    TOOLS,
    TOOLS_BY_NAME,
    validate_arguments,
)


class AgenticEpisode22(AgenticEpisode):
    league_class = League21
    scoring = score_v2

    def _open_phase(self) -> None:
        # The 2.0 constructor builds a ``League`` and opens the first phase
        # straight away. Nothing has been played then and ``League.new`` is a
        # pure function of the seed, so swapping the league here starts the
        # same league under this contract's rules (as 2.1 does).
        if not isinstance(self.league, self.league_class):
            self.league = self.league_class.new(seed=self.seed, user_team_id=self.user_team_id)
        super()._open_phase()

    def _write(self, record: dict[str, Any]) -> None:
        # The ledger header names its contract, so a replay picks this engine.
        if record.get("event") == "episode":
            record = {**record, "benchmark_version": BENCHMARK_VERSION, "tool_surface": TOOL_SURFACE_VERSION}
        super()._write(record)

    def _execute(self, name: str, arguments: Any) -> dict[str, Any]:
        spec = TOOLS_BY_NAME.get(name)
        if spec is None:
            return self._reply(False, f"unknown tool {name!r}")
        error = validate_arguments(name, arguments)
        if error:
            # Structurally bad calls never reach the simulator, so they are not
            # protocol violations; they are reported as rejected tool calls.
            return self._reply(False, f"invalid arguments: {error}")
        arguments = arguments or {}
        self._phase_tool_calls += 1
        if name == "end_phase":
            self._phase_tool_calls -= 1  # the closing call is not counted against the phase
            return self._close_phase(ENDED_BY_AGENT)
        if spec["kind"] == "read":
            return self._read(name)
        action = {"type": ACTION_TYPE_FOR_TOOL[name], **arguments}
        return self._apply(action, is_move=spec["kind"] == "move")

    def _legal_tools(self, available_actions: list[str]) -> list[str]:
        reads = [
            spec["name"]
            for spec in TOOLS
            if spec["kind"] == "read" and self._READ_PHASE.get(spec["name"], self.phase) == self.phase
        ]
        reverse = {action: tool for tool, action in ACTION_TYPE_FOR_TOOL.items()}
        tools = [reverse[action] for action in available_actions if action in reverse]
        return reads + tools + ["end_phase"]

    def result(self, agent_name: str = "agentic") -> dict[str, Any]:
        payload = super().result(agent_name)
        components = self.scoring.score_components(self.league, self.user_team_id)
        breakdown = breakdown_from_components(components)
        payload.update(
            final_score=round(breakdown["final_score"], 3),
            strategy_score=round(breakdown["strategy_score"], 3),
            protocol_penalty=round(breakdown["protocol_penalty"], 3),
            score_components=self.scoring.persisted_score_components(components),
            scoring_version=self.scoring.SCORING_VERSION,
            benchmark_version=BENCHMARK_VERSION,
        )
        payload["agentic"]["tool_surface"] = TOOL_SURFACE_VERSION
        return payload
