"""Hidden-information diagnostic ceiling reference.

The oracle is intentionally outside ``gm_bench.agents.AGENTS``: it is a
diagnostic reference rather than an official baseline.  It retains the proven
PickTrader policy, but can recover deterministic simulator-only information.
"""

from __future__ import annotations

import random
from functools import lru_cache
from typing import Any

from gm_bench.agents import PickTraderAgent
from gm_bench.generator import generate_draft_class, generate_league_data
from gm_bench.models import pick_value
from gm_bench.simulator import FA_RESERVATION_RANGE, TRADE_VALUE_THRESHOLD


@lru_cache(maxsize=None)
def _true_potentials(seed: int, through_season: int) -> dict[int, float]:
    """Regenerate immutable latent potential for players visible so far.

    Initial players are regenerated from the league seed.  Each draft class
    has an independent deterministic seed, so a later free agent or waiver can
    be traced to either the initial population or a prior draft class as well.
    """
    _teams, players, _free_agents = generate_league_data(seed)
    potentials = {player_id: player.true_potential for player_id, player in players.items()}
    for season in range(1, through_season + 1):
        draft_class = generate_draft_class(seed, season, 60)
        potentials.update({player_id: player.true_potential for player_id, player in draft_class.items()})
    return potentials


def _model_asset_value(player: dict[str, Any]) -> float:
    """Recompute the simulator's private trade asset value from public fields."""
    age_factor = max(0.05, 1.18 - max(float(player["age"]) - 23.0, 0.0) * 0.055)
    contract_factor = 1.0
    if int(player.get("contract_years", 0)) > 0:
        surplus = max(-10.0, float(player["overall"]) - 52.0 - float(player.get("salary", 0.0)) * 2.5)
        contract_factor += surplus * 0.018
    return max(
        0.0,
        (float(player["overall"]) * 0.55 + float(player["potential"]) * 0.45 - 45.0) * age_factor * contract_factor,
    )


class OracleAgent(PickTraderAgent):
    """A partial hidden-information ceiling reference.

    The policy inherits PickTrader's public-information roster strategy.  At a
    draft, it replaces the scouted public choice only when regenerated latent
    potential is meaningfully better despite a substantial public-potential
    discount.  This keeps the reference focused on strategic headroom rather
    than discarding score-relevant public asset value.

    Free-agent offers are retained only after checking the seeded reservation
    threshold.  Pick trades are retained only after recomputing the exact
    seeded partner valuation threshold.  The oracle cannot see or predict
    stochastic injuries, development rolls, simulated game outcomes, or
    opponents' future choices.
    """

    name = "oracle"
    TRUE_POTENTIAL_EDGE = 0.5
    PUBLIC_POTENTIAL_DISCOUNT = 5.0
    TRUE_VALUE_WEIGHT = 0.75

    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        actions = super().act(observation)
        self._apply_latent_draft_choice(actions, observation)
        return [action for action in actions if self._offer_will_land(action, observation)]

    def _apply_latent_draft_choice(self, actions: list[dict[str, Any]], observation: dict[str, Any]) -> None:
        if observation["phase"] != "draft" or int(observation.get("interaction_round", 0)) < 3:
            return
        draft_action = next((action for action in actions if action.get("type") == "draft"), None)
        prospects = observation.get("draft_class") or []
        if draft_action is None or not prospects:
            return
        by_id = {int(player["id"]): player for player in prospects}
        public_choice = by_id.get(int(draft_action["prospect_id"]))
        if public_choice is None:
            return
        latent_choice = max(prospects, key=lambda player: self._draft_value(observation, player))
        potentials = _true_potentials(int(observation["seed"]), int(observation["season"]))
        true_edge = potentials[int(latent_choice["id"])] - potentials[int(public_choice["id"])]
        public_discount = float(public_choice["potential"]) - float(latent_choice["potential"])
        if true_edge > self.TRUE_POTENTIAL_EDGE and public_discount > self.PUBLIC_POTENTIAL_DISCOUNT:
            draft_action["prospect_id"] = latent_choice["id"]

    def _draft_value(self, observation: dict[str, Any], player: dict[str, Any]) -> float:
        latent_potential = _true_potentials(int(observation["seed"]), int(observation["season"]))[int(player["id"])]
        public_value = float(player["overall"]) * 0.5 + float(player["potential"]) * 0.5
        latent_value = float(player["overall"]) * 0.5 + latent_potential * 0.5
        return self.TRUE_VALUE_WEIGHT * latent_value + (1.0 - self.TRUE_VALUE_WEIGHT) * public_value

    def _offer_will_land(self, action: dict[str, Any], observation: dict[str, Any]) -> bool:
        """Keep only outgoing offers whose deterministic hidden threshold passes."""
        action_type = action.get("type")
        if action_type == "sign_free_agent":
            player = next(
                (item for item in observation.get("free_agents", []) if item["id"] == action.get("player_id")),
                None,
            )
            if player is None:
                return False
            reservation = self._reservation(
                int(observation["seed"]),
                int(observation["season"]),
                int(player["id"]),
                float(player["asking_salary"]),
            )
            return float(action["salary"]) >= reservation
        if action_type == "trade":
            return self._pick_trade_will_land(action, observation)
        return True

    @staticmethod
    def _reservation(seed: int, season: int, player_id: int, asking_salary: float) -> float:
        low, high = FA_RESERVATION_RANGE
        return asking_salary * random.Random(f"{seed}:{season}:reservation:{player_id}").uniform(low, high)

    @staticmethod
    def _partner_value(seed: int, season: int, partner_id: int, asset_id: int | str, value: float) -> float:
        bias = random.Random(f"{seed}:{season}:valuation:{partner_id}:{asset_id}").uniform(0.9, 1.1)
        return value * bias

    def _pick_trade_will_land(self, action: dict[str, Any], observation: dict[str, Any]) -> bool:
        """Validate PickTrader's outgoing one-pick trade against hidden bias."""
        if action.get("give_player_ids") or action.get("receive_pick_seasons"):
            return False
        receive_ids = action.get("receive_player_ids", [])
        give_picks = action.get("give_pick_seasons", [])
        if len(receive_ids) != 1 or len(give_picks) != 1:
            return False
        target = next(
            (
                offer["player"]
                for offer in observation.get("trade_market", [])
                if offer["player"]["id"] == receive_ids[0]
            ),
            None,
        )
        if target is None:
            return False
        seed, season, partner_id = int(observation["seed"]), int(observation["season"]), int(action["partner_team_id"])
        give_pick = int(give_picks[0])
        perceived_give = self._partner_value(
            seed, season, partner_id, f"pick:{give_pick}", pick_value(season, give_pick)
        )
        perceived_receive = self._partner_value(seed, season, partner_id, int(target["id"]), _model_asset_value(target))
        return perceived_give >= perceived_receive * TRADE_VALUE_THRESHOLD
