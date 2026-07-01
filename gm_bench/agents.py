"""Scripted agents and external-process adapter."""

from __future__ import annotations

import json
import random
import shlex
import subprocess
from abc import ABC, abstractmethod
from typing import Any

from gm_bench.agent_utils import position_aware_lineup, public_asset_value


class Agent(ABC):
    name = "agent"

    @abstractmethod
    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        raise NotImplementedError


class RandomAgent(Agent):
    name = "random"

    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        rng = random.Random(f"{observation['seed']}:{observation['season']}:{observation['phase']}:random")
        actions: list[dict[str, Any]] = []
        free_agents = observation["free_agents"][:]
        rng.shuffle(free_agents)
        if free_agents and rng.random() < 0.45:
            player = free_agents[0]
            actions.append({"type": "sign_free_agent", "player_id": player["id"], "years": 1, "salary": player["asking_salary"]})
        roster = observation["team"]["roster"][:]
        rng.shuffle(roster)
        lineup = position_aware_lineup(roster, lambda player: rng.random())
        if lineup:
            actions.append({"type": "set_lineup", "player_ids": lineup})
        if observation["phase"] == "draft" and observation["draft_class"]:
            prospect = rng.choice(observation["draft_class"])
            actions.append({"type": "draft", "prospect_id": prospect["id"]})
        return actions


class ConservativeAgent(Agent):
    name = "conservative"

    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        actions = []
        roster = observation["team"]["roster"]
        if observation["team"]["cap_room"] > 4:
            values = sorted(
                observation["free_agents"],
                key=lambda player: player["overall"] / max(player["asking_salary"], 0.1),
                reverse=True,
            )
            for player in values[:2]:
                if player["age"] <= 30 and player["asking_salary"] <= observation["team"]["cap_room"]:
                    actions.append({"type": "sign_free_agent", "player_id": player["id"], "years": 1, "salary": player["asking_salary"]})
                    break
        if observation["phase"] == "draft" and observation["draft_class"]:
            prospect = max(observation["draft_class"], key=lambda player: (player["potential"], player["overall"]))
            actions.append({"type": "draft", "prospect_id": prospect["id"]})
        lineup = position_aware_lineup(roster, lambda player: player["overall"])
        if lineup:
            actions.append({"type": "set_lineup", "player_ids": lineup})
        return actions


class WinNowAgent(Agent):
    name = "win-now"

    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        actions = []
        cap_room = observation["team"]["cap_room"]
        free_agents = sorted(observation["free_agents"], key=lambda player: player["overall"], reverse=True)
        for player in free_agents[:4]:
            if player["asking_salary"] <= cap_room + 1.5 and player["overall"] >= 57:
                actions.append({"type": "sign_free_agent", "player_id": player["id"], "years": 2, "salary": player["asking_salary"]})
                cap_room -= player["asking_salary"]
        if observation["phase"] == "draft" and observation["draft_class"]:
            prospect = max(observation["draft_class"], key=lambda player: player["overall"])
            actions.append({"type": "draft", "prospect_id": prospect["id"]})
        lineup = position_aware_lineup(observation["team"]["roster"], lambda player: player["overall"])
        if lineup:
            actions.append({"type": "set_lineup", "player_ids": lineup})
        return actions


class RebuildAgent(Agent):
    name = "rebuild"

    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        actions = []
        if observation["phase"] == "draft" and observation["draft_class"]:
            prospect = max(
                observation["draft_class"],
                key=lambda player: (player["potential"] * 1.25 - player["age"] * 0.4, player["overall"]),
            )
            actions.append({"type": "draft", "prospect_id": prospect["id"]})
        cap_room = observation["team"]["cap_room"]
        prospects = sorted(
            observation["free_agents"],
            key=lambda player: (player["potential"] - player["age"] * 0.55) / max(player["asking_salary"], 0.1),
            reverse=True,
        )
        for player in prospects[:3]:
            if player["age"] <= 25 and player["asking_salary"] <= cap_room:
                actions.append({"type": "sign_free_agent", "player_id": player["id"], "years": 3, "salary": player["asking_salary"]})
                cap_room -= player["asking_salary"]
        lineup = position_aware_lineup(observation["team"]["roster"], lambda player: player["potential"] * 0.65 + player["overall"] * 0.35)
        if lineup:
            actions.append({"type": "set_lineup", "player_ids": lineup})
        return actions


class ValueAgent(Agent):
    name = "value"

    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        actions = []
        cap_room = observation["team"]["cap_room"]
        free_agents = sorted(observation["free_agents"], key=public_asset_value, reverse=True)
        for player in free_agents[:5]:
            if player["asking_salary"] <= cap_room and public_asset_value(player) > 7.0:
                years = 3 if player["age"] <= 27 else 1
                actions.append({"type": "sign_free_agent", "player_id": player["id"], "years": years, "salary": player["asking_salary"]})
                cap_room -= player["asking_salary"]
        if observation["phase"] == "draft" and observation["draft_class"]:
            prospect = max(observation["draft_class"], key=public_asset_value)
            actions.append({"type": "draft", "prospect_id": prospect["id"]})
        lineup = position_aware_lineup(observation["team"]["roster"], lambda player: player["overall"] * 0.78 + player["potential"] * 0.22)
        if lineup:
            actions.append({"type": "set_lineup", "player_ids": lineup})
        return actions


class ExternalProcessAgent(Agent):
    name = "external"

    def __init__(self, command: str, timeout_seconds: float = 10.0) -> None:
        self.command = command
        self.timeout_seconds = timeout_seconds

    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            completed = subprocess.run(
                shlex.split(self.command),
                input=json.dumps(observation),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return [{"type": "noop", "error": f"external agent timed out after {self.timeout_seconds}s"}]
        except OSError as exc:
            return [{"type": "noop", "error": f"external agent could not be launched: {exc}"}]
        if completed.returncode != 0:
            return [{"type": "noop", "error": completed.stderr[-500:]}]
        try:
            actions = json.loads(completed.stdout)
        except json.JSONDecodeError:
            return [{"type": "noop", "error": "external agent returned invalid JSON"}]
        return actions if isinstance(actions, list) else [{"type": "noop", "error": "external agent must return a list"}]


AGENTS: dict[str, type[Agent]] = {
    "random": RandomAgent,
    "conservative": ConservativeAgent,
    "win-now": WinNowAgent,
    "rebuild": RebuildAgent,
    "value": ValueAgent,
}
