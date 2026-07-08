"""Scripted agents and external-process adapter."""

from __future__ import annotations

import json
import os
import random
import shlex
import subprocess
from abc import ABC, abstractmethod
from typing import Any

from gm_bench.agent_utils import position_aware_lineup, public_asset_value
from gm_bench.telemetry import normalize_usage


class Agent(ABC):
    name = "agent"

    @abstractmethod
    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        raise NotImplementedError

    def act_with_usage(self, observation: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        """Return (actions, usage). Scripted agents have no model usage to report."""
        return self.act(observation), None


class RandomAgent(Agent):
    name = "random"

    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        rng = random.Random(f"{observation['seed']}:{observation['season']}:{observation['phase']}:random")
        actions: list[dict[str, Any]] = []
        free_agents = observation["free_agents"][:]
        rng.shuffle(free_agents)
        if free_agents and rng.random() < 0.45:
            player = free_agents[0]
            actions.append(
                {"type": "sign_free_agent", "player_id": player["id"], "years": 1, "salary": player["asking_salary"]}
            )
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
                    actions.append(
                        {
                            "type": "sign_free_agent",
                            "player_id": player["id"],
                            "years": 1,
                            "salary": player["asking_salary"],
                        }
                    )
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
                actions.append(
                    {
                        "type": "sign_free_agent",
                        "player_id": player["id"],
                        "years": 2,
                        "salary": player["asking_salary"],
                    }
                )
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
                actions.append(
                    {
                        "type": "sign_free_agent",
                        "player_id": player["id"],
                        "years": 3,
                        "salary": player["asking_salary"],
                    }
                )
                cap_room -= player["asking_salary"]
        lineup = position_aware_lineup(
            observation["team"]["roster"], lambda player: player["potential"] * 0.65 + player["overall"] * 0.35
        )
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
                actions.append(
                    {
                        "type": "sign_free_agent",
                        "player_id": player["id"],
                        "years": years,
                        "salary": player["asking_salary"],
                    }
                )
                cap_room -= player["asking_salary"]
        if observation["phase"] == "draft" and observation["draft_class"]:
            prospect = max(observation["draft_class"], key=public_asset_value)
            actions.append({"type": "draft", "prospect_id": prospect["id"]})
        lineup = position_aware_lineup(
            observation["team"]["roster"], lambda player: player["overall"] * 0.78 + player["potential"] * 0.22
        )
        if lineup:
            actions.append({"type": "set_lineup", "player_ids": lineup})
        return actions


class ShrewdAgent(Agent):
    """A stronger-on-average honest reference than `value`.

    Uses only public observation data, like every scripted baseline. It exists
    to keep the skill bar honest — a model-backed candidate that cannot beat
    `shrewd`'s panel average has not demonstrated anything a short heuristic
    can't do. On top of `value`-style signings it:

    - releases clearly-negative veteran contracts before shopping, so the
      freed cap is spent in the same decision window;
    - dresses high-upside youth over marginal veterans, since only dressed
      players develop at full speed and young asset value scores double.

    The youth-dressing rule is a horizon bet: it wins on average across seed
    panels but loses individual seeds when the developed prospects don't pan
    out, so no per-seed dominance over `value` is claimed or pinned. Midseason
    (now in the default episode) uses a looser FA bar and overall-only dress —
    the remaining games reward current form over development.
    """

    name = "shrewd"

    RELEASE_VALUE_FLOOR = -2.0
    MIN_KEEP_ROSTER = 20

    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        roster = observation["team"]["roster"]
        cap_room = observation["team"]["cap_room"]
        midseason = observation["phase"] == "midseason"

        # Cap hygiene: skip releases at midseason — dumping salary after the
        # partial leg disrupts a roster that still has half a season to play.
        released_ids: set[int] = set()
        if not midseason:
            deadweight = sorted(
                (
                    player
                    for player in roster
                    if player["age"] >= 30
                    and player["salary"] > 0
                    and public_asset_value(player) < self.RELEASE_VALUE_FLOOR
                ),
                key=public_asset_value,
            )
            releasable = max(0, len(roster) - self.MIN_KEEP_ROSTER)
            for player in deadweight[: min(2, releasable)]:
                actions.append({"type": "release", "player_id": player["id"]})
                released_ids.add(player["id"])
                cap_room += player["salary"]

        # Midseason FA bar is slightly looser: the partial-season break is the
        # best window to spend remaining cap before the stretch run.
        fa_threshold = 5.0 if midseason else 6.0
        free_agents = sorted(observation["free_agents"], key=public_asset_value, reverse=True)
        for player in free_agents[:8]:
            if player["asking_salary"] <= cap_room and public_asset_value(player) > fa_threshold:
                years = 3 if player["age"] <= 27 else 1
                actions.append(
                    {
                        "type": "sign_free_agent",
                        "player_id": player["id"],
                        "years": years,
                        "salary": player["asking_salary"],
                    }
                )
                cap_room -= player["asking_salary"]

        if observation["phase"] == "draft" and observation["draft_class"]:
            prospect = max(observation["draft_class"], key=public_asset_value)
            actions.append({"type": "draft", "prospect_id": prospect["id"]})

        # Dress for today and tomorrow: mostly overall, but bump young players
        # with real growth room so they develop at full speed. At midseason,
        # dress strictly by overall — the remaining games reward current form.
        def dress_rank(player: dict[str, Any]) -> float:
            if midseason:
                return player["overall"]
            upside = max(0.0, player["potential"] - player["overall"])
            youth_bonus = upside * 0.45 if player["age"] <= 24 else 0.0
            return player["overall"] + youth_bonus

        remaining = [player for player in roster if player["id"] not in released_ids]
        lineup = position_aware_lineup(remaining, dress_rank)
        if lineup:
            actions.append({"type": "set_lineup", "player_ids": lineup})
        return actions


class StrategicAgent(ShrewdAgent):
    """Reference policy that exercises the benchmark's planning mechanics.

    `shrewd` is deliberately compact, but that leaves scouting, incoming
    offers, pick trading, and memo persistence without a competent reference
    policy. This agent keeps the same roster-management core and adds
    conservative public-information policies for those surfaces.
    """

    name = "strategic"
    OFFER_EDGE = 1.08
    PICK_TRADE_PRICE_CEILING = 0.82
    ENABLE_PICK_TRADES = False

    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        phase = observation["phase"]
        interaction_round = int(observation.get("interaction_round", 0))

        if phase == "draft":
            scout_action = self._next_scout_action(observation)
            if scout_action is not None:
                return [scout_action]

        actions = super().act(observation)
        if phase == "draft":
            self._apply_scouted_draft_choice(actions, observation)

        if phase == "preseason" and interaction_round == 0:
            actions.insert(
                0,
                {
                    "type": "memo",
                    "text": "Build sustainable value, preserve cap flexibility, and reassess at the deadline.",
                },
            )

        if phase == "trade_deadline":
            protected_ids = {
                int(action["player_id"])
                for action in actions
                if action.get("type") == "release" and "player_id" in action
            }
            offer_actions, offer_player_ids, used_partner_ids = self._offer_actions(observation)
            actions.extend(offer_actions)
            protected_ids.update(offer_player_ids)
            if self.ENABLE_PICK_TRADES:
                projected_cap_room = self._projected_cap_room(observation, actions)
                pick_trade = self._pick_trade_action(
                    observation,
                    excluded_player_ids=protected_ids,
                    excluded_partner_ids=used_partner_ids,
                    available_cap_room=projected_cap_room,
                )
                if pick_trade is not None:
                    actions.append(pick_trade)
        return actions

    @staticmethod
    def _scouted_value(player: dict[str, Any], reports: dict[str, Any]) -> float:
        report = reports.get(str(player["id"]))
        if not isinstance(report, (int, float)):
            return public_asset_value(player)
        return public_asset_value({**player, "potential": float(report)})

    def _next_scout_action(self, observation: dict[str, Any]) -> dict[str, Any] | None:
        current_season = int(observation["season"])
        if int(observation["team"]["draft_picks"].get(current_season, 0)) <= 0:
            return None
        points_remaining = int(observation["rules"]["scouting"]["points_remaining"])
        if points_remaining <= 0:
            return None
        reports = observation.get("scout_reports") or {}
        unscouted = [player for player in observation.get("draft_class", []) if str(player["id"]) not in reports]
        if not unscouted:
            return None
        target = max(unscouted, key=public_asset_value)
        return {"type": "scout", "player_id": target["id"]}

    def _apply_scouted_draft_choice(
        self,
        actions: list[dict[str, Any]],
        observation: dict[str, Any],
    ) -> None:
        current_season = int(observation["season"])
        if int(observation["team"]["draft_picks"].get(current_season, 0)) <= 0:
            actions[:] = [action for action in actions if action.get("type") != "draft"]
            return
        prospects = observation.get("draft_class") or []
        if not prospects:
            return
        reports = observation.get("scout_reports") or {}
        target = max(prospects, key=lambda player: self._scouted_value(player, reports))
        for action in actions:
            if action.get("type") == "draft":
                action["prospect_id"] = target["id"]
                return

    def _offer_actions(
        self,
        observation: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], set[int], set[int]]:
        offers = observation.get("incoming_offers") or []
        if not offers:
            return [], set(), set()
        pick_values = observation["rules"]["pick_trading"]["pick_value_estimate"]

        def side_value(players_key: str, picks_key: str, offer: dict[str, Any]) -> float:
            return sum(public_asset_value(player) for player in offer.get(players_key, [])) + sum(
                float(pick_values.get(str(season), 0.0)) for season in offer.get(picks_key, [])
            )

        ranked: list[tuple[float, dict[str, Any]]] = []
        for offer in offers:
            receive = side_value("you_receive_players", "you_receive_pick_seasons", offer)
            give = side_value("they_receive_players", "they_receive_pick_seasons", offer)
            ranked.append((receive - give * self.OFFER_EDGE, offer))
        ranked.sort(key=lambda item: item[0], reverse=True)
        accepted_id = ranked[0][1]["offer_id"] if ranked[0][0] >= 0 else None

        actions: list[dict[str, Any]] = []
        protected_player_ids: set[int] = set()
        partner_ids: set[int] = set()
        for _edge, offer in ranked:
            partner_ids.add(int(offer["team_id"]))
            protected_player_ids.update(int(player["id"]) for player in offer.get("they_receive_players", []))
            action_type = "accept_trade_offer" if offer["offer_id"] == accepted_id else "reject_trade_offer"
            actions.append({"type": action_type, "offer_id": offer["offer_id"]})
        return actions, protected_player_ids, partner_ids

    @staticmethod
    def _projected_cap_room(
        observation: dict[str, Any],
        actions: list[dict[str, Any]],
    ) -> float:
        cap_room = float(observation["team"]["cap_room"])
        roster_by_id = {int(player["id"]): player for player in observation["team"]["roster"]}
        offers_by_id = {offer["offer_id"]: offer for offer in observation.get("incoming_offers", [])}
        for action in actions:
            action_type = action.get("type")
            if action_type == "release":
                player = roster_by_id.get(int(action.get("player_id", -1)))
                if player is not None:
                    cap_room += float(player["salary"])
            elif action_type == "sign_free_agent":
                cap_room -= float(action.get("salary", 0.0))
            elif action_type == "accept_trade_offer":
                offer = offers_by_id.get(action.get("offer_id"))
                if offer is not None:
                    cap_room += sum(float(player["salary"]) for player in offer.get("they_receive_players", []))
                    cap_room -= sum(float(player["salary"]) for player in offer.get("you_receive_players", []))
        return cap_room

    def _pick_trade_action(
        self,
        observation: dict[str, Any],
        *,
        excluded_player_ids: set[int],
        excluded_partner_ids: set[int],
        available_cap_room: float,
    ) -> dict[str, Any] | None:
        next_season = int(observation["season"]) + 1
        pick_value_estimate = float(
            observation["rules"]["pick_trading"]["pick_value_estimate"].get(str(next_season), 0.0)
        )
        if int(observation["team"]["draft_picks"].get(next_season, 1)) <= 0:
            return None
        candidates = [
            offer
            for offer in observation.get("trade_market", [])
            if offer["team_id"] not in excluded_partner_ids
            and offer["player"]["id"] not in excluded_player_ids
            and offer["player"]["age"] <= 27
            and offer["player"]["salary"] <= available_cap_room
            and float(offer["estimated_price"]) <= pick_value_estimate * self.PICK_TRADE_PRICE_CEILING
        ]
        if not candidates:
            return None
        target = max(candidates, key=lambda offer: public_asset_value(offer["player"]))
        return {
            "type": "trade",
            "partner_team_id": target["team_id"],
            "give_player_ids": [],
            "receive_player_ids": [target["player"]["id"]],
            "give_pick_seasons": [next_season],
            "receive_pick_seasons": [],
        }


class PickTraderAgent(StrategicAgent):
    """Strategic reference with conservative future-pick acquisitions enabled."""

    name = "pick-trader"
    ENABLE_PICK_TRADES = True


class ExploitAgent(Agent):
    """Red-team diagnostic that replays known-degenerate strategies.

    Hoards cheap free agents for depth/asset points and attempts value-pump
    trades (receiving more public value than it gives, which the pre-fix 0.78
    acceptance threshold allowed). It is kept as a baseline canary: if a rules
    or scoring change re-opens an exploit, this agent's score jumps past the
    honest baselines and the regression test in test_validity_fixes catches it.
    """

    name = "exploit"

    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        team = observation["team"]
        cap_room = team["cap_room"]
        for player in sorted(observation["free_agents"], key=lambda item: item["asking_salary"]):
            if len(actions) >= 8:
                break
            if player["asking_salary"] <= cap_room:
                actions.append(
                    {
                        "type": "sign_free_agent",
                        "player_id": player["id"],
                        "years": 1,
                        "salary": player["asking_salary"],
                    }
                )
                cap_room -= player["asking_salary"]

        givable = sorted(team["roster"], key=public_asset_value)
        used_give_ids: set[int] = set()
        offers = sorted(
            observation["trade_market"], key=lambda offer: public_asset_value(offer["player"]), reverse=True
        )
        for offer in offers:
            if len(actions) >= 16:
                break
            receive_value = public_asset_value(offer["player"])
            give = next(
                (
                    player
                    for player in givable
                    if player["id"] not in used_give_ids
                    and receive_value / 1.25 <= public_asset_value(player) < receive_value
                ),
                None,
            )
            if give is None:
                continue
            used_give_ids.add(give["id"])
            actions.append(
                {
                    "type": "trade",
                    "partner_team_id": offer["team_id"],
                    "give_player_ids": [give["id"]],
                    "receive_player_ids": [offer["player"]["id"]],
                }
            )

        if observation["phase"] == "draft" and observation["draft_class"]:
            prospect = max(observation["draft_class"], key=public_asset_value)
            actions.append({"type": "draft", "prospect_id": prospect["id"]})
        lineup = position_aware_lineup(team["roster"], lambda player: player["overall"])
        if lineup:
            actions.append({"type": "set_lineup", "player_ids": lineup})
        return actions


class ExternalProcessAgent(Agent):
    name = "external"

    def __init__(
        self,
        command: str,
        timeout_seconds: float = 10.0,
        *,
        env: dict[str, str] | None = None,
        name: str | None = None,
    ) -> None:
        self.command = command
        self.timeout_seconds = timeout_seconds
        self.env = env
        if name is not None:
            self.name = name

    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        actions, _usage = self.act_with_usage(observation)
        return actions

    def act_with_usage(self, observation: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        """Run the adapter and parse its stdout.

        Two stdout shapes are accepted: a bare JSON action list (the original
        protocol, kept so third-party adapters don't break) and an envelope
        ``{"actions": [...], "usage": {...}}`` that also reports model usage.
        """
        run_env = None
        if self.env:
            run_env = os.environ.copy()
            run_env.update(self.env)
        try:
            completed = subprocess.run(
                shlex.split(self.command),
                input=json.dumps(observation),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.timeout_seconds,
                check=False,
                env=run_env,
            )
        except subprocess.TimeoutExpired:
            return [{"type": "noop", "error": f"external agent timed out after {self.timeout_seconds}s"}], None
        except OSError as exc:
            return [{"type": "noop", "error": f"external agent could not be launched: {exc}"}], None
        if completed.returncode != 0:
            return [{"type": "noop", "error": completed.stderr[-500:]}], None
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            return [{"type": "noop", "error": "external agent returned invalid JSON"}], None
        if isinstance(payload, list):
            return payload, None
        if isinstance(payload, dict) and isinstance(payload.get("actions"), list):
            return payload["actions"], normalize_usage(payload.get("usage"))
        return [{"type": "noop", "error": "external agent must return an action list or envelope"}], None


AGENTS: dict[str, type[Agent]] = {
    "random": RandomAgent,
    "conservative": ConservativeAgent,
    "win-now": WinNowAgent,
    "rebuild": RebuildAgent,
    "value": ValueAgent,
    "shrewd": ShrewdAgent,
    "strategic": StrategicAgent,
    "pick-trader": PickTraderAgent,
    "exploit": ExploitAgent,
}
