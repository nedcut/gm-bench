"""The 2.2 agentic episode: the frozen engine bound to the 2.2 tool surface.

Contract source for 2.2 (fingerprinted by ``gm_bench.v22.contract``).
``AgenticEpisode`` is a 2.0 contract source and stays byte for byte. It reads
the 2.0 tool list as a module global, so the two methods that do
(``_execute`` and ``_legal_tools``) are restated here against
``gm_bench.v22.tools``; everything else is inherited.

What this engine does differently from 2.1's (``docs/bench_v2_1_queue.md``
item numbers):

- It plays ``League22`` and scores with score-v3.
- ``list_draft_class`` answers in every phase (item 2), so a prospect can be
  scouted before the draft without guessing an id.
- The ``end_phase`` reply lists every call the phase refused (item 22), and the
  reply that opens the draft says when the season is played (item 19).
- A call whose arguments are not an object is logged as not executed
  (item 4). Live it is refused; logged as executed with ``{}`` it could run
  on replay.
"""

from __future__ import annotations

from typing import Any

from gm_bench.agentic.episode import ENDED_BY_AGENT, AgenticEpisode
from gm_bench.scoring import breakdown_from_components
from gm_bench.v22 import scoring as score_v3
from gm_bench.v22.contract import BENCHMARK_VERSION
from gm_bench.v22.rules import League22
from gm_bench.v22.tools import (
    ACTION_TYPE_FOR_TOOL,
    TOOL_SURFACE_VERSION,
    TOOLS,
    TOOLS_BY_NAME,
    validate_arguments,
)


class AgenticEpisode22(AgenticEpisode):
    league_class = League22
    scoring = score_v3
    # Reads that answer in one phase only; ``list_draft_class`` answers in all of them.
    _READ_PHASE = {"list_waiver_wire": "midseason"}

    def _open_phase(self) -> None:
        # The 2.0 constructor builds a ``League`` and opens the first phase
        # straight away. Nothing has been played then and ``League.new`` is a
        # pure function of the seed, so swapping the league here starts the
        # same league under this contract's rules (as 2.1 does).
        if not isinstance(self.league, self.league_class):
            self.league = self.league_class.new(seed=self.seed, user_team_id=self.user_team_id)
        # Calls rejected in the phase that is opening, reported when it closes.
        self._phase_rejections: list[dict[str, Any]] = []
        super()._open_phase()

    def _close_phase(self, ended_by: str) -> dict[str, Any]:
        rejections = self._phase_rejections
        response = super()._close_phase(ended_by)
        response["closed"]["rejected_calls"] = rejections
        response["closed"]["penalized_calls"] = sum(1 for call in rejections if call["penalized"])
        if not self.done and self.phase == "draft":
            response["message"] = (
                f"Season {self.season_index}, draft is open. The rest of the regular season and the "
                "playoffs are played when you end this phase, with the roster and lineup you have then. "
                "Call get_status."
            )
        return response

    def _log_call(
        self, name: str, arguments: Any, result: dict[str, Any], *, elapsed_ms: float, executed: bool
    ) -> None:
        # Not an object: refused before the engine acted, and the ledger cannot
        # hold the raw value as arguments, so replay must skip the call.
        if arguments is not None and not isinstance(arguments, dict):
            executed = False
        super()._log_call(name, arguments, result, elapsed_ms=elapsed_ms, executed=executed)

    def _write(self, record: dict[str, Any]) -> None:
        # The ledger header names its contract, so a replay picks this engine.
        if record.get("event") == "episode":
            record = {**record, "benchmark_version": BENCHMARK_VERSION, "tool_surface": TOOL_SURFACE_VERSION}
        super()._write(record)

    def _execute(self, name: str, arguments: Any) -> dict[str, Any]:
        rejections = self._phase_rejections
        reply = self._run(name, arguments)
        # Every refused call of the phase, whatever refused it. A close that succeeds is not
        # one, and ``rejections`` is the closing phase's list even once the next has opened.
        if not reply["ok"]:
            rejections.append({"tool": name, "message": reply["message"], "penalized": bool(reply.get("penalized"))})
        return reply

    def _run(self, name: str, arguments: Any) -> dict[str, Any]:
        # ``AgenticEpisode._execute``, against the 2.2 tools.
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

    def _read(self, name: str) -> dict[str, Any]:
        if name == "list_draft_class":
            observation = self.league.observation(self.phase, tier="full")
            return {"ok": True, "message": "draft class", "data": {"prospects": observation["draft_class"]}}
        return super()._read(name)

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
