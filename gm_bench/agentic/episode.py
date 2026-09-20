"""The 2.0 episode engine.

One ``AgenticEpisode`` owns one league for one seed. The harness's tool calls
arrive one at a time through ``call_tool``; the engine maps them onto the
unchanged simulator, keeps the phase calendar, and appends every call to a
line-delimited JSON ledger.

The ledger is the durable truth for an episode. It is replayable: the engine
can be rebuilt from it after the server process dies (a harness that
restarts its MCP servers, a crash, a driver finalizing an abandoned run),
because the simulator is deterministic for a given seed and action sequence.
Nothing hidden is ever written to it beyond the seed in the header, and the
header lives outside the agent's workspace.

Phase mechanics are the same calls ``gm_bench.runner.run_episode`` makes, in
the same order, so a 2.0 episode and a 1.0 episode on the same seed see the
same league.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any

from gm_bench.agentic.tools import ACTION_TYPE_FOR_TOOL, TOOL_SURFACE_VERSION, TOOLS_BY_NAME, validate_arguments
from gm_bench.protocol import PHASES
from gm_bench.scoring import breakdown_from_components, persisted_score_components, score_components
from gm_bench.simulator import SCOUT_POINTS_PER_SEASON, League
from gm_bench.telemetry import aggregate_usage

DEFAULT_PHASE_GUARD_SECONDS = 20 * 60.0
LEDGER_VERSION = "gm-bench-agentic-ledger-v1"

# How a phase was closed. Only ``agent`` is a successful decision.
ENDED_BY_AGENT = "agent"
ENDED_BY_GUARD = "guard"
ENDED_BY_HARNESS_EXIT = "harness_exit"


class EpisodeComplete(Exception):
    """Raised for a tool call after the final phase has been closed."""


# Keys whose values name an entity the agent can later act on.
_ID_KEYS = frozenset({"id", "player_id", "prospect_id", "team_id", "offer_id", "partner_id", "champion_team_id"})
_ID_LIST_KEYS = frozenset({"lineup", "top_player_ids", "roster", "you_receive", "they_receive"})
_MAX_IDS_PER_CALL = 4000


def exposed_ids(data: Any) -> list[int | str]:
    """Every player, prospect, team and offer id a tool reply made visible."""
    found: set[int | str] = set()
    _collect_ids(data, found, key=None)
    return sorted(found, key=lambda value: (isinstance(value, str), value))[:_MAX_IDS_PER_CALL]


def _collect_ids(node: Any, found: set[int | str], *, key: str | None) -> None:
    if isinstance(node, dict):
        for child_key, value in node.items():
            if not isinstance(child_key, str):
                # Season-keyed tables (draft picks, dead cap) carry no entity ids.
                _collect_ids(value, found, key=None)
                continue
            if child_key in _ID_KEYS and isinstance(value, (int, str)) and not isinstance(value, bool):
                found.add(value)
            elif child_key in _ID_LIST_KEYS and isinstance(value, list):
                found.update(v for v in value if isinstance(v, int) and not isinstance(v, bool))
                _collect_ids(value, found, key=child_key)
            elif child_key.endswith("_ids") and isinstance(value, list):
                found.update(v for v in value if isinstance(v, int) and not isinstance(v, bool))
            else:
                _collect_ids(value, found, key=child_key)
    elif isinstance(node, list):
        for item in node:
            _collect_ids(item, found, key=key)


class AgenticEpisode:
    def __init__(
        self,
        seed: int,
        seasons: int = 5,
        user_team_id: int = 0,
        *,
        ledger_path: str | Path | None = None,
        phase_guard_seconds: float = DEFAULT_PHASE_GUARD_SECONDS,
        write_header: bool = True,
    ) -> None:
        self.seed = seed
        self.seasons = seasons
        self.user_team_id = user_team_id
        self.phase_guard_seconds = phase_guard_seconds
        self.league = League.new(seed=seed, user_team_id=user_team_id)
        self.ledger_path = Path(ledger_path) if ledger_path is not None else None
        self._ledger_file = None
        if self.ledger_path is not None:
            self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
            self._ledger_file = self.ledger_path.open("a", encoding="utf-8")
        self._replaying = False
        self.seq = 0
        self.season_index = 0  # 1-based once the first phase opens
        self.phase_index = 0
        self.phase_open = False
        self.done = False
        self._phase_started_monotonic = 0.0
        self._phase_started_wall = 0.0
        self._phase_tool_calls = 0
        self.phase_log: list[dict[str, Any]] = []
        self.tool_counts: Counter[str] = Counter()
        self.moves_accepted = 0
        self.moves_rejected = 0
        self.harness_usage: dict[str, Any] | None = None
        if write_header:
            self._write(
                {
                    "event": "episode",
                    "ledger_version": LEDGER_VERSION,
                    "tool_surface": TOOL_SURFACE_VERSION,
                    "seed": seed,
                    "seasons": seasons,
                    "user_team_id": user_team_id,
                    "phase_guard_seconds": phase_guard_seconds,
                }
            )
        self._open_phase()

    # -- calendar -------------------------------------------------------------

    @property
    def phase(self) -> str:
        return PHASES[self.phase_index]

    @property
    def season(self) -> int:
        return self.season_index

    def _open_phase(self) -> None:
        if self.done:
            return
        if self.season_index == 0:
            self.season_index = 1
        league = self.league
        phase = self.phase
        if phase == "midseason":
            league.prepare_midseason()
        if phase == "trade_deadline":
            league.prepare_trade_deadline()
        if phase == "draft":
            league.run_opponent_draft(before_user=True)
        league.begin_decision_window()
        self.phase_open = True
        self._phase_started_monotonic = time.monotonic()
        self._phase_started_wall = time.time()
        self._phase_tool_calls = 0
        self._write({"event": "phase_open", "season": self.season_index, "phase": phase})

    def _close_phase(self, ended_by: str) -> dict[str, Any]:
        """Run the post-phase hooks and advance. Returns what the agent is told."""
        league = self.league
        phase = self.phase
        if phase == "draft":
            league.run_opponent_draft(before_user=False)
        league.run_autopilot_opponents(phase)
        elapsed = time.monotonic() - self._phase_started_monotonic
        record = {
            "season": self.season_index,
            "phase": phase,
            "ended_by": ended_by,
            "tool_calls": self._phase_tool_calls,
            "seconds": round(elapsed, 3),
        }
        self.phase_log.append(record)
        self._write({"event": "phase_end", **record})
        self.phase_open = False
        response: dict[str, Any] = {"ok": True, "closed": {"season": self.season_index, "phase": phase}}
        if self.phase_index == len(PHASES) - 1:
            summary = league.simulate_season()
            response["season_result"] = {
                "season": summary.season,
                "wins": summary.wins,
                "losses": summary.losses,
                "playoff_rounds": summary.playoff_rounds,
                "champion_team_id": summary.champion_team_id,
                "you_won_the_title": summary.champion_team_id == self.user_team_id,
            }
            if self.season_index >= self.seasons:
                self.done = True
                self._write({"event": "episode_end", "seasons_played": self.season_index})
                response["episode_complete"] = True
                response["message"] = "All seasons are complete. The episode is over; stop here."
                return response
            self.season_index += 1
            self.phase_index = 0
        else:
            self.phase_index += 1
        self._open_phase()
        response["now"] = {"season": self.season_index, "phase": self.phase}
        response["message"] = f"Season {self.season_index}, {self.phase} is open. Call get_status."
        return response

    def phase_expired(self) -> bool:
        return (
            self.phase_open
            and not self._replaying
            and self.phase_guard_seconds > 0
            and (time.monotonic() - self._phase_started_monotonic) > self.phase_guard_seconds
        )

    def abandon(self) -> None:
        """Close every remaining phase as a harness exit. Used by the driver."""
        while not self.done:
            self._close_phase(ENDED_BY_HARNESS_EXIT)

    # -- tools ----------------------------------------------------------------

    def call_tool(self, name: str, arguments: Any) -> dict[str, Any]:
        """Execute one tool call, log it, and return the agent-facing result."""
        if self.done:
            # Logged so the ledger matches the harness's own tool-event count;
            # never executed, so replay skips it.
            message = "the episode is complete; no further tool calls are accepted"
            self._log_call(name, arguments, {"ok": False, "message": message}, elapsed_ms=0.0, executed=False)
            raise EpisodeComplete(message)
        notice = None
        if self.phase_expired():
            expired = {"season": self.season_index, "phase": self.phase, "seconds": self.phase_guard_seconds}
            self._close_phase(ENDED_BY_GUARD)
            notice = (
                f"Season {expired['season']} {expired['phase']} exceeded the {expired['seconds']:.0f}s phase "
                f"guard and was closed without you. This call was NOT executed. "
                + (
                    "The episode is complete."
                    if self.done
                    else f"You are now in season {self.season_index}, {self.phase}."
                )
            )
            result = {"ok": False, "message": notice, "season": self.season_index, "phase": self.phase}
            self._log_call(name, arguments, result, elapsed_ms=0.0, executed=False)
            return result
        started = time.perf_counter()
        result = self._execute(name, arguments)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        self._log_call(name, arguments, result, elapsed_ms=elapsed_ms, executed=True)
        return result

    def _log_call(
        self, name: str, arguments: Any, result: dict[str, Any], *, elapsed_ms: float, executed: bool
    ) -> None:
        self.seq += 1
        self.tool_counts[name] += 1
        self._write(
            {
                "event": "tool_call",
                "seq": self.seq,
                "season": result.get("season", self.season_index),
                "phase": result.get("phase", self.phase),
                "tool": name,
                "arguments": arguments if isinstance(arguments, dict) else {},
                "executed": executed,
                "ok": bool(result.get("ok")),
                "message": str(result.get("message", ""))[:300],
                "penalized": bool(result.get("penalized", False)),
                "elapsed_ms": round(elapsed_ms, 2),
                # Every entity id this reply exposed, so the audit can tell a
                # move on a fetched id from a move on an id the agent could
                # only know by reaching around the tools.
                "ids_exposed": exposed_ids(result.get("data")),
            }
        )

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

    def _apply(self, action: dict[str, Any], *, is_move: bool) -> dict[str, Any]:
        league = self.league
        before_illegal = league.illegal_actions
        before_declines = league.rejected_offers + league.query_declines
        results = league.apply_actions([action], self.phase)
        if not results:
            return self._reply(False, "the simulator produced no result")
        outcome = results[-1]
        penalized = league.illegal_actions > before_illegal
        declined = (league.rejected_offers + league.query_declines) > before_declines
        if is_move:
            if outcome.accepted:
                self.moves_accepted += 1
            else:
                self.moves_rejected += 1
        reply = self._reply(outcome.accepted, outcome.message)
        if outcome.data is not None:
            reply["data"] = outcome.data
        if penalized:
            reply["penalized"] = True
            reply["penalty_note"] = "protocol violation: this rejection costs score"
        elif declined:
            reply["declined"] = True
        return reply

    def _read(self, name: str) -> dict[str, Any]:
        league = self.league
        if name == "get_status":
            observation = league.observation(self.phase, tier="summary")
            team = observation["team"]
            payload = {
                "season": self.season_index,
                "seasons_total": self.seasons,
                "phase": self.phase,
                "phase_tool_calls_so_far": self._phase_tool_calls - 1,
                "team": team,
                "standings": observation["standings"],
                "draft_order": observation["draft_order"],
                "draft_lottery": observation["draft_lottery"],
                "history": observation["history"],
                "incoming_offers_count": len(observation["incoming_offers"]),
                "free_agents_count": observation["free_agents_summary"]["count"],
                "draft_class_count": observation["draft_class_summary"]["count"],
                "waiver_wire_count": observation["waiver_wire_summary"]["count"],
                "trade_market_count": observation["trade_market_summary"]["count"],
                "scouting_points_remaining": SCOUT_POINTS_PER_SEASON - league.scout_points_used,
                "scout_reports": observation["scout_reports"],
                "memo": observation["memo"],
                "legal_tools": self._legal_tools(observation["available_actions"]),
            }
            return {"ok": True, "message": f"season {self.season_index} {self.phase}", "data": payload}
        observation = league.observation(self.phase, tier="full")
        if name == "get_rules":
            return {"ok": True, "message": "league rules", "data": observation["rules"]}
        if name == "get_team":
            return {"ok": True, "message": "your team", "data": observation["team"]}
        if name == "list_draft_class":
            if self.phase != "draft":
                return self._reply(False, "the draft class is only visible in the draft phase")
            return {"ok": True, "message": "draft class", "data": {"prospects": observation["draft_class"]}}
        if name == "list_waiver_wire":
            if self.phase != "midseason":
                return self._reply(False, "the waiver wire only exists at midseason")
            return {"ok": True, "message": "waiver wire", "data": {"players": observation["waiver_wire"]}}
        if name == "list_offers":
            return {"ok": True, "message": "incoming offers", "data": {"offers": observation["incoming_offers"]}}
        if name == "list_trade_market":
            return {"ok": True, "message": "trade market", "data": {"players": observation["trade_market"]}}
        if name == "list_transactions":
            return {
                "ok": True,
                "message": "recent transactions",
                "data": {"transactions": observation["recent_transactions"]},
            }
        return self._reply(False, f"unhandled read tool {name!r}")

    @staticmethod
    def _legal_tools(available_actions: list[str]) -> list[str]:
        reverse = {action: tool for tool, action in ACTION_TYPE_FOR_TOOL.items()}
        tools = [reverse[action] for action in available_actions if action in reverse]
        return tools + ["end_phase"]

    def _reply(self, ok: bool, message: str) -> dict[str, Any]:
        return {"ok": ok, "message": message, "season": self.season_index, "phase": self.phase}

    # -- ledger ---------------------------------------------------------------

    def _write(self, record: dict[str, Any]) -> None:
        if self._replaying or self._ledger_file is None:
            return
        record = {"ts": round(time.time(), 3), **record}
        self._ledger_file.write(json.dumps(record, sort_keys=True) + "\n")
        self._ledger_file.flush()

    def close(self) -> None:
        if self._ledger_file is not None:
            self._ledger_file.close()
            self._ledger_file = None

    @classmethod
    def from_ledger(cls, path: str | Path, *, reopen: bool = True) -> AgenticEpisode:
        """Rebuild an episode by replaying its ledger.

        With ``reopen`` the returned engine appends to the same file, so a
        restarted server carries on where the previous process stopped.
        """
        path = Path(path)
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not records or records[0].get("event") != "episode":
            raise ValueError(f"{path} is not an agentic ledger")
        header = records[0]
        # Build without a ledger so construction and replay write nothing;
        # the file is attached afterwards if the caller wants to carry on.
        episode = cls(
            int(header["seed"]),
            int(header["seasons"]),
            int(header.get("user_team_id", 0)),
            ledger_path=None,
            phase_guard_seconds=float(header.get("phase_guard_seconds", DEFAULT_PHASE_GUARD_SECONDS)),
            write_header=False,
        )
        episode._replaying = True
        try:
            for record in records[1:]:
                event = record.get("event")
                if event == "tool_call":
                    if not record.get("executed", True):
                        continue
                    episode.seq += 1
                    episode.tool_counts[record["tool"]] += 1
                    episode._execute(record["tool"], record.get("arguments") or {})
                elif event == "phase_end" and record.get("ended_by") != ENDED_BY_AGENT:
                    episode._close_phase(record["ended_by"])
        finally:
            episode._replaying = False
        if reopen:
            episode.ledger_path = path
            episode._ledger_file = path.open("a", encoding="utf-8")
        # Replayed phase durations are meaningless; restore the recorded ones.
        recorded = [r for r in records if r.get("event") == "phase_end"]
        for entry, source in zip(episode.phase_log, recorded, strict=False):
            entry["seconds"] = source.get("seconds", entry["seconds"])
            entry["tool_calls"] = source.get("tool_calls", entry["tool_calls"])
        return episode

    # -- result ---------------------------------------------------------------

    def result(self, agent_name: str = "agentic") -> dict[str, Any]:
        """The episode payload, shaped like ``BenchmarkResult`` plus an ``agentic`` block."""
        if not self.done:
            raise RuntimeError("episode is not finished; call abandon() to close it first")
        league = self.league
        components = score_components(league, self.user_team_id)
        breakdown = breakdown_from_components(components)
        decisions = self.seasons * len(PHASES)
        failed = sum(1 for entry in self.phase_log if entry["ended_by"] != ENDED_BY_AGENT)
        seconds = [entry["seconds"] for entry in self.phase_log]
        memo_writes = sum(
            1
            for transaction in league.transactions
            if transaction.team_id == self.user_team_id
            and transaction.accepted
            and transaction.action.get("type") == "memo"
        )
        usage = self.harness_usage or aggregate_usage([])
        usage.setdefault("per_decision", [])
        return {
            "agent": agent_name,
            "seed": self.seed,
            "seasons": self.seasons,
            "final_score": round(breakdown["final_score"], 3),
            "strategy_score": round(breakdown["strategy_score"], 3),
            "protocol_penalty": round(breakdown["protocol_penalty"], 3),
            "score_components": persisted_score_components(components),
            "wins": sum(summary.wins for summary in league.summaries),
            "championships": league.user_team.championships,
            "illegal_actions": league.illegal_actions,
            "decisions": decisions,
            "failed_decisions": failed,
            "malformed_decisions": 0,
            "unrecoverable_decisions": 0,
            "memo_writes": memo_writes,
            "mean_decision_seconds": round(mean(seconds), 4) if seconds else 0.0,
            "max_decision_seconds": round(max(seconds), 4) if seconds else 0.0,
            "rejected_offers": league.rejected_offers,
            "failed_queries": league.failed_queries,
            "query_declines": league.query_declines,
            "usage": usage,
            "season_summaries": [summary.__dict__ for summary in league.summaries],
            "transactions": [transaction.__dict__ for transaction in league.transactions],
            "agentic": {
                "tool_surface": TOOL_SURFACE_VERSION,
                "tool_calls": sum(self.tool_counts.values()),
                "tool_calls_by_tool": dict(sorted(self.tool_counts.items())),
                "moves_accepted": self.moves_accepted,
                "moves_rejected": self.moves_rejected,
                "scout_points_used": sum(1 for _ in league.scout_reports),
                "phases": list(self.phase_log),
                "phases_ended_by": dict(Counter(entry["ended_by"] for entry in self.phase_log)),
                "phase_guard_seconds": self.phase_guard_seconds,
            },
        }
