"""Browser game adapter over the frozen agentic episode, with replayable saves.

Only public observation data leaves this adapter. Saves contain the setup and
human calls, never pickled Python objects or private player valuations.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from gm_bench.agentic.episode import AgenticEpisode
from gm_bench.agentic.tools import TOOLS_BY_NAME, validate_arguments
from gm_bench.scoring import breakdown_from_components, score_components

SAVE_SCHEMA = "gm-bench-human-v1"
MAX_CALLS = 10000
GAME_TOOLS = frozenset(
    name for name, spec in TOOLS_BY_NAME.items() if spec["kind"] in {"move", "control"} or name == "scout"
)


def _check_seed(seed: Any) -> None:
    if type(seed) is not int or not 0 <= seed <= 2147483647:
        raise ValueError("Choose a whole-number seed between 0 and 2147483647.")


@lru_cache(maxsize=8)
def _reference(seed: int) -> dict[str, Any]:
    from gm_bench.agents import AGENTS
    from gm_bench.runner import run_episode

    result = run_episode(AGENTS["pick-trader"](), seed=seed, seasons=5)
    return {
        "name": "Pick-trader",
        "final_score": result.final_score,
        "wins": result.wins,
        "championships": result.championships,
    }


class BrowserGame:
    def __init__(self, seed: int = 1, *, engine_version: str = "development") -> None:
        _check_seed(seed)
        self.engine_version = engine_version
        # Humans can leave a tab open indefinitely. The model harness's wall
        # clock guard must not advance a human's game while they are away.
        self.episode = AgenticEpisode(seed, seasons=5, phase_guard_seconds=0)
        self.calls: list[dict[str, Any]] = []

    def act(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool not in GAME_TOOLS:
            raise ValueError("That action is not available in the game.")
        error = validate_arguments(tool, arguments)
        if error:
            raise ValueError(error)
        if self.episode.done:
            raise ValueError("This challenge is complete. Start a new challenge to play again.")
        if len(self.calls) >= MAX_CALLS:
            raise ValueError("This save has reached its action limit. Export it and start a new challenge.")
        result = self.episode.call_tool(tool, arguments)
        self.calls.append({"tool": tool, "arguments": arguments, "ok": bool(result["ok"])})
        return result

    def snapshot(self) -> dict[str, Any]:
        episode = self.episode
        league = episode.league
        observation = league.observation(episode.phase, tier="full")
        # Prospects are hidden until the draft, just as in the model lane.
        if episode.phase != "draft" or episode.done:
            observation["draft_class"] = []
        if episode.phase != "midseason" or episode.done:
            observation["waiver_wire"] = []
        observation.update(
            {
                "season": episode.season,
                "seasons_total": episode.seasons,
                "phase": episode.phase,
                "done": episode.done,
                "seed": episode.seed,
                "legal_tools": [] if episode.done else episode._legal_tools(observation["available_actions"]),
                "history": [summary.__dict__ for summary in league.summaries],
                "score": breakdown_from_components(score_components(league, league.user_team_id)),
                "score_terms": {
                    key.removesuffix("_contribution"): value
                    for key, value in score_components(league, league.user_team_id).items()
                    if key.endswith("_contribution")
                },
                "reference": _reference(episode.seed) if episode.done else None,
                "effective_lineup": [p.id for p in league._effective_lineup(league.user_team)],
                "teams": [
                    team.public_dict(league.players, league.cap, league.season) for team in league.teams.values()
                ],
                "actions_taken": len(self.calls),
            }
        )
        return observation

    def save(self) -> dict[str, Any]:
        return {
            "schema": SAVE_SCHEMA,
            "engine_version": self.engine_version,
            "seed": self.episode.seed,
            "calls": self.calls,
        }

    @classmethod
    def restore(cls, payload: Any, *, engine_version: str = "development") -> BrowserGame:
        if not isinstance(payload, dict) or payload.get("schema") != SAVE_SCHEMA:
            raise ValueError("This is not a GM-Bench game save.")
        if payload.get("engine_version") != engine_version:
            raise ValueError(
                "This save uses a different simulator version. Keep the file to use with its original version."
            )
        calls = payload.get("calls")
        if not isinstance(calls, list) or len(calls) > MAX_CALLS:
            raise ValueError("Invalid save action list.")
        game = cls(payload.get("seed"), engine_version=engine_version)
        for call in calls:
            if not isinstance(call, dict) or not isinstance(call.get("tool"), str) or type(call.get("ok")) is not bool:
                raise ValueError("Invalid saved action.")
            result = game.act(call["tool"], call.get("arguments"))
            if bool(result["ok"]) != call["ok"]:
                raise ValueError("The saved actions do not replay consistently.")
        return game


# A JSON boundary keeps PyProxy lifetimes out of the UI worker.
_game: BrowserGame | None = None


def dispatch(request_json: str, engine_version: str) -> str:
    global _game
    request = json.loads(request_json)
    command = request["command"]
    result = None
    if command == "reference":
        # The start screen shows the score to beat before a game exists; the
        # active game, if any, is left alone.
        seed = request.get("seed")
        _check_seed(seed)
        return json.dumps({"reference": _reference(seed)})
    if command == "new":
        candidate = BrowserGame(request.get("seed", 1), engine_version=engine_version)
        _game = candidate
    elif command == "restore":
        # Validate and replay into a candidate so a bad import never replaces
        # the active game.
        candidate = BrowserGame.restore(request["save"], engine_version=engine_version)
        _game = candidate
    elif command == "act" and _game is not None:
        result = _game.act(request["tool"], request.get("arguments", {}))
    else:
        raise ValueError("Start or resume a challenge first.")
    return json.dumps({"snapshot": _game.snapshot(), "save": _game.save(), "result": result})


def handle_request(request_json: str, engine_version: str) -> str:
    """Return expected input failures without exposing Python traces to players."""
    try:
        return dispatch(request_json, engine_version)
    except (ValueError, KeyError, TypeError) as error:
        return json.dumps({"error": str(error)})
