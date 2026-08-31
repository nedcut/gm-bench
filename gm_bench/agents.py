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
from gm_bench.repair import repair_adapter_output
from gm_bench.scaffold_view import model_adapter_observation, scaffold_view_observation
from gm_bench.telemetry import normalize_usage


def _release_surplus(player: dict[str, Any]) -> float:
    """How much better off the roster is without this player, in value units.

    `public_asset_value` already nets out `0.7 * salary`, so it is the value of
    *keeping* the player. Releasing swaps that for a dead-cap charge that buys
    nothing, so the comparison is:

        keep    =  public_asset_value(player)          (on-ice value less salary)
        release = -0.7 * release_dead_cap.total            (a cost with no player)

    and the surplus from releasing is `release - keep`. Positive means the
    contract is underwater by more than it costs to escape. The 0.7 weight is
    reused from `public_asset_value` so both sides are in the same units.

    Players with no guaranteed years carry no charge, so for them this reduces
    to "is the player worth less than nothing", which is the honest question.
    """
    dead_cap = player.get("release_dead_cap") or {}
    total_charge = float(dead_cap.get("total", 0.0))
    return -public_asset_value(player) - 0.7 * total_charge


def _release_cap_room_delta(player: dict[str, Any], *, season: int) -> float:
    """Net cap-room change this season from releasing a player.

    Uses the published per-season charge for the current season rather than
    approximating with a salary fraction, so multi-year guarantees are priced
    against what the observation actually shows.
    """
    dead_cap = player.get("release_dead_cap") or {}
    by_season = dead_cap.get("by_season") or {}
    current_charge = float(by_season.get(str(season), 0.0))
    return float(player["salary"]) - current_charge


def _contract_quote(player: dict[str, Any], years: int) -> float:
    """Return the public guaranteed quote for a term."""
    quotes = player.get("contract_quotes") or player.get("extension_quotes") or {}
    if str(years) in quotes:
        return float(quotes[str(years)])
    return float(player["asking_salary"])


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
            salary = _contract_quote(player, 2)
            if salary <= cap_room + 1.5 and player["overall"] >= 57:
                actions.append(
                    {
                        "type": "sign_free_agent",
                        "player_id": player["id"],
                        "years": 2,
                        "salary": salary,
                    }
                )
                cap_room -= salary
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
            salary = _contract_quote(player, 3)
            if player["age"] <= 25 and salary <= cap_room:
                actions.append(
                    {
                        "type": "sign_free_agent",
                        "player_id": player["id"],
                        "years": 3,
                        "salary": salary,
                    }
                )
                cap_room -= salary
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
            years = 3 if player["age"] <= 27 else 1
            salary = _contract_quote(player, years)
            if salary <= cap_room and public_asset_value(player) > 7.0:
                actions.append(
                    {
                        "type": "sign_free_agent",
                        "player_id": player["id"],
                        "years": years,
                        "salary": salary,
                    }
                )
                cap_room -= salary
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

    # A release is worth making when the cap it frees buys more than the player
    # still provides. `release_dead_cap` publishes the exact charge, so this is
    # a comparison the policy can actually make rather than a magic threshold.
    #
    # This replaces a `public_asset_value < -2.0` floor that was unreachable in
    # combination with the age and salary tests it was ANDed with: instrumenting
    # 40 preseason windows on seeds 11-18 found zero candidates, before and
    # after contract economics existed (issue #91). The docstring above has
    # advertised release behaviour that never once executed.
    #
    # The bar is deliberately set so that clearing it means the player is
    # genuinely underwater, not merely mediocre. If that turns out to be rare,
    # that is a real statement about dead cap deterring releases -- which is
    # only distinguishable from a dead branch now that the branch can fire.
    RELEASE_SURPLUS_MARGIN = 1.5
    MIN_KEEP_ROSTER = 20

    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        roster = observation["team"]["roster"]
        cap_room = observation["team"]["cap_room"]
        midseason = observation["phase"] == "midseason"
        season = int(observation["season"])

        if observation["phase"] == "preseason":
            extension_candidates = sorted(
                (
                    player
                    for player in roster
                    if player.get("extension_quotes") and player["age"] <= 27 and public_asset_value(player) > 8.0
                ),
                key=public_asset_value,
                reverse=True,
            )
            for player in extension_candidates[:2]:
                years = 4 if player["age"] <= 24 else 3
                salary = _contract_quote(player, years)
                if cap_room + player["salary"] >= salary:
                    actions.append(
                        {
                            "type": "extend_contract",
                            "player_id": player["id"],
                            "years": years,
                            "salary": salary,
                        }
                    )
                    cap_room += player["salary"] - salary

        # Cap hygiene: skip releases at midseason — dumping salary after the
        # partial leg disrupts a roster that still has half a season to play.
        released_ids: set[int] = set()
        if not midseason:
            deadweight = sorted(
                (player for player in roster if _release_surplus(player) > self.RELEASE_SURPLUS_MARGIN),
                key=_release_surplus,
                reverse=True,
            )
            releasable = max(0, len(roster) - self.MIN_KEEP_ROSTER)
            for player in deadweight[: min(2, releasable)]:
                actions.append({"type": "release", "player_id": player["id"]})
                released_ids.add(player["id"])
                cap_room += _release_cap_room_delta(player, season=season)

        # Midseason FA bar is slightly looser: the partial-season break is the
        # best window to spend remaining cap before the stretch run.
        fa_threshold = 5.0 if midseason else 6.0
        free_agents = sorted(observation["free_agents"], key=public_asset_value, reverse=True)
        for player in free_agents[:8]:
            years = 3 if player["age"] <= 27 else 1
            salary = _contract_quote(player, years)
            if salary <= cap_room and public_asset_value(player) > fa_threshold:
                actions.append(
                    {
                        "type": "sign_free_agent",
                        "player_id": player["id"],
                        "years": years,
                        "salary": salary,
                    }
                )
                cap_room -= salary

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
    PICK_SALE_VALUE_FLOOR = 1.0
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
                    cap_room += _release_cap_room_delta(player, season=int(observation["season"]))
            elif action_type == "sign_free_agent":
                cap_room -= float(action.get("salary", 0.0))
            elif action_type == "extend_contract":
                player = roster_by_id.get(int(action.get("player_id", -1)))
                if player is not None:
                    cap_room += float(player["salary"]) - float(action.get("salary", 0.0))
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
        roster = observation["team"]["roster"]
        if len(roster) <= self.MIN_KEEP_ROSTER:
            return None
        candidates = [
            player
            for player in roster
            if player["id"] not in excluded_player_ids
            and player["age"] >= 28
            and player["contract_years"] <= 2
            and public_asset_value(player) >= pick_value_estimate * self.PICK_SALE_VALUE_FLOOR
        ]
        partner_offers = [
            offer for offer in observation.get("trade_market", []) if offer["team_id"] not in excluded_partner_ids
        ]
        if not candidates or not partner_offers:
            return None
        # Contract guarantees make an aging veteran expensive to cut. Move the
        # smallest asset that still covers the public pick estimate, avoiding
        # dead cap while preserving the roster floor. A team marketing the
        # weakest player is the deterministic first buyer for added depth.
        player = min(candidates, key=public_asset_value)
        partner_id = min(partner_offers, key=lambda offer: public_asset_value(offer["player"]))["team_id"]
        return {
            "type": "trade",
            "partner_team_id": partner_id,
            "give_player_ids": [player["id"]],
            "receive_player_ids": [],
            "give_pick_seasons": [],
            "receive_pick_seasons": [next_season],
        }


class PickTraderAgent(StrategicAgent):
    """Strategic reference with conservative future-pick acquisitions enabled."""

    name = "pick-trader"
    ENABLE_PICK_TRADES = True


class ScaffoldViewAgent(PickTraderAgent):
    """`pick-trader` run on the payload a model adapter actually receives.

    Registered baselines are handed the untruncated observation
    (`runner._observation_tier_for_agent` forces the full tier for anything in
    `AGENTS`), while model agents only ever see
    `scaffold_view.compact_observation` of it: sorted-and-sliced free agents and
    draft prospects, a head slice of the trade market, three incoming offers.
    This agent keeps the pick-trader policy and changes nothing but the view,
    so the difference between the two rows isolates observation asymmetry
    rather than a difference in strategy.

    That is narrower than "what the scaffold costs", and the gap must not be
    quoted as such. Model rows additionally run fresh-spawned with only a
    2,000-character memo carrying state between decision points, under a
    4,096-token output cap and one bounded protocol repair. None of those are
    held constant here: the scripted policy is stateless and rebuilds its plan
    from the observation every turn, so it pays no memo cost to begin with.
    What this reference measures is the cost of view truncation, nothing more.

    Two deliberate faithfulness choices:

    * The prompt hands every model a legal lineup computed from the *full*
      roster. That freebie is offered here too, and used only when the policy
      could not build a lineup from the truncated roster it was given. Like the
      prompt's copy it is computed before the batch runs, so it is dropped when
      the same batch ships a player out rather than dressing a departed player.
    * The payload is passed in-process instead of through JSON. Serializing
      would turn `team.draft_picks` season keys into strings and silently break
      scripted `.get(season)` lookups -- a Python typing artifact that costs a
      model nothing, and which would otherwise dominate the measured gap.
    """

    name = "scaffold-view"
    # An accepted offer ships players out just as a release or an outgoing
    # trade does, and the injected lineup predates all of them.
    ROSTER_SHRINKING_ACTIONS = frozenset({"release", "trade", "accept_trade_offer"})
    # Pinned, not inherited. This agent runs in the harness process, where
    # GM_AGENT_PROFILE reflects the operator's shell rather than the lane the
    # model ran under -- an ambient "tiny" would hand the reference a 24/16/16
    # view while the model saw 18/6/6 and silently understate the truncation cost.
    # Compare against a tiny-profile row only by instantiating with profile="tiny"
    # (which also changes agent.name so the baseline cache cannot collide).
    PROFILE = "compact"

    def __init__(self, profile: str | None = None) -> None:
        super().__init__()
        self.profile = profile or self.PROFILE
        # The baseline cache keys on agent.name and does not record profile, so a
        # non-default profile must not share the registered compact identity —
        # otherwise a tiny episode can be cached and later served to a compact run.
        if self.profile != self.PROFILE:
            self.name = f"{type(self).name}:{self.profile}"

    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        view = scaffold_view_observation(observation, self.profile)
        actions = super().act(view)
        fallback = view.get("scaffold_fallback_lineup") or []
        if not fallback or any(action.get("type") == "set_lineup" for action in actions):
            return actions
        if not any(action.get("type") in self.ROSTER_SHRINKING_ACTIONS for action in actions):
            actions.append({"type": "set_lineup", "player_ids": list(fallback)})
        return actions


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
        run_env = external_agent_environment(self.env)
        try:
            completed = subprocess.run(
                shlex.split(self.command),
                input=json.dumps(model_adapter_observation(observation)),
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
        # v6 buys exactly one model call per phase, so malformed output is
        # repaired locally under the published rules or recorded as a
        # structured no-op; there is no second, paid attempt.
        outcome = repair_adapter_output(completed.stdout, source="external agent")
        return outcome.actions, normalize_usage(outcome.usage)


_PRIVATE_SEED_ENV_PREFIX = "GM_BENCH_PRIVATE_SEED"
_PRIVATE_SEED_SECRET_ENV_VARS = frozenset({"GM_BENCH_SEED_PANEL_SALT"})


def external_agent_environment(overrides: dict[str, str] | None = None) -> dict[str, str]:
    """Build a child environment without private seed material.

    Apply adapter configuration first and scrub second so neither an inherited
    operator environment nor an explicit provider override can accidentally
    disclose the held-out panel. The prefix also covers future variables such
    as ``GM_BENCH_PRIVATE_SEED_SALT`` without removing ordinary provider and
    scaffold configuration.
    """
    run_env = os.environ.copy()
    if overrides:
        run_env.update(overrides)
    for key in tuple(run_env):
        if key.startswith(_PRIVATE_SEED_ENV_PREFIX) or key in _PRIVATE_SEED_SECRET_ENV_VARS:
            run_env.pop(key)
    return run_env


AGENTS: dict[str, type[Agent]] = {
    "random": RandomAgent,
    "conservative": ConservativeAgent,
    "win-now": WinNowAgent,
    "rebuild": RebuildAgent,
    "value": ValueAgent,
    "shrewd": ShrewdAgent,
    "strategic": StrategicAgent,
    "pick-trader": PickTraderAgent,
    "scaffold-view": ScaffoldViewAgent,
    "exploit": ExploitAgent,
}
