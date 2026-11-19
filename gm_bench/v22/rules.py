"""The 2.2 league: 2.1's rules, with what the rules payload leaves out stated.

Contract source for 2.2 (fingerprinted by ``gm_bench.v22.contract``).
``League`` and ``League21`` are frozen sources and stay byte for byte. Every
change here is one a 2.1 panel showed models misreading
(``docs/bench_v2_1_queue.md``; item numbers below are that file's).

Two game mechanics change: item 27, and what a rival pays for a player you
picked up for nothing this season (below). Strength, prices, the draft and
every random draw are 2.1's.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from gm_bench.models import CENTER_SHARE, LINEUP_SIZE
from gm_bench.protocol import ActionResult
from gm_bench.simulator import (
    CENTER_LINEUP_BONUS_PER,
    CENTER_LINEUP_TARGET,
    EXPIRY_SCRAMBLE_CANDIDATES,
    FA_VETERAN_AGE,
    HARD_CAP_BUFFER,
    REJECTED_OFFER_LIMIT_PER_WINDOW,
    TRADE_LIMIT_PER_PARTNER,
)
from gm_bench.v21.rules import League21

# The constants of ``League._team_strength``, which has them as literals.
# ``tests/test_v22.py`` checks that the published formula reproduces the
# engine's strength, so the two cannot drift apart.
GOALIE_BONUS = 2.5
GOALIE_BONUS_MAX_GOALIES = 2
LINEUP_SLOT_WEIGHTS = ((6, 1.0), (12, 0.74), (LINEUP_SIZE, 0.48))
OVER_CAP_STRENGTH_PENALTY = 0.25
SEASON_INJURY_OVERALL_LOSS = (5.0, 18.0)


@dataclass
class League22(League21):
    """``League21`` plus the 2.2 changes; every other rule is 2.1's.

    - ``get_rules`` publishes the strength formula (item 26), the trade
      limits with their units and penalties (item 24), what an extension
      does (item 21) and the tradable pick seasons; each listed pick says
      whether it can be traded now (item 14). Your roster cards carry
      ``injured_games``, which the strength formula needs and 2.1 never
      showed. Three inherited descriptions that gave advice or promised a
      signing unconditionally are restated as mechanics.
    - ``inspect_player`` finds draft prospects, as its description says
      (item 3).
    - A signing refused because the player is not a free agent says where
      the player is (item 23). It is still an illegal move.
    - Trade-deadline offers are withdrawn when the deadline closes (item 27).
      2.1 kept them listed through the draft phase, where accepting a stale
      one was a penalized move.
    - A rival gives no trade value to a player you signed as a free agent or
      claimed off waivers this season: it could have had him for the same
      price. Under 2.1 a rival paid full asset value for each such player and
      summed them, so packages of cheap signings bought its best young
      players (the 2026-11-18 pilot; ``scripts/diagnose_package_trades.py``).
    """

    # Player id -> the season you signed him as a free agent or claimed him.
    acquired_free: dict[int, int] = field(default_factory=dict)

    def _acquired_free_this_season(self, player_id: int | str) -> bool:
        return self.acquired_free.get(player_id) == self.season and player_id in self.user_team.roster  # type: ignore[arg-type]

    def _partner_valuation_bias(self, partner_id: int, player_id: int | str) -> float:
        if self._acquired_free_this_season(player_id):
            return 0.0
        return super()._partner_valuation_bias(partner_id, player_id)

    def observation(self, phase: str, **kwargs: Any) -> dict[str, Any]:
        payload = super().observation(phase, **kwargs)
        window = self._tradeable_pick_seasons()
        rules = payload["rules"]
        low, high = SEASON_INJURY_OVERALL_LOSS
        rules["team_strength"] = {
            "goalie_bonus_per_dressed_goalie": GOALIE_BONUS,
            "goalie_bonus_max_goalies": GOALIE_BONUS_MAX_GOALIES,
            "lineup_slot_weights": [
                {"ranks_by_overall": [first + 1, last], "weight": weight}
                for first, (last, weight) in zip((0, *(last for last, _ in LINEUP_SLOT_WEIGHTS)), LINEUP_SLOT_WEIGHTS)
            ],
            "over_cap_penalty_per_unit": OVER_CAP_STRENGTH_PENALTY,
            "season_injury_overall_loss": [low, high],
            "description": (
                "Team strength is the weighted average overall of the dressed players who are not "
                "injured (injured_games is 0 on your roster cards; an injured player sits out that "
                "many of the team's games), ranked by overall with the slot weights above, plus "
                f"{GOALIE_BONUS} for each dressed goalie up to {GOALIE_BONUS_MAX_GOALIES}, plus the "
                f"center bonus, minus {OVER_CAP_STRENGTH_PENALTY} for each unit of payroll above the "
                "salary cap. Games are simulated twice a season (the first third, then the rest "
                "with the playoffs). Each time, every dressed player independently plays "
                f"{low:g} to {high:g} overall points below his rating for those games, with "
                "probability equal to his injury_risk."
            ),
        }
        # 2.1's text for these three advised ("often misses this", "not a free
        # option") or promised that a quote "always succeeds"; 2.2 states the rule.
        rules["lineup_center_bonus"]["description"] = (
            "Each forward's sub_position is 'C' (center) or 'W' (wing); roughly "
            f"{CENTER_SHARE:.0%} of forwards are centers league-wide. A dressed lineup earns "
            f"+{CENTER_LINEUP_BONUS_PER} team strength per dressed center up to {CENTER_LINEUP_TARGET}."
        )
        rules["free_agency_willingness"]["description"] = (
            "Each free agent's quotes are the market rate times his published "
            "signing_appeal.quote_multiplier: winning teams and a lineup role earn discounts, "
            "losing teams and a depth role cost premiums, and veterans "
            f"(age >= {FA_VETERAN_AGE}) weigh winning twice as heavily as younger players. He "
            "accepts any offer at or above the quote. The signing must still leave your payroll "
            f"within the salary cap plus {HARD_CAP_BUFFER:g}, a player you released this season "
            "will not re-sign until the next, and a player who has declined "
            f"{REJECTED_OFFER_LIMIT_PER_WINDOW} of your offers in a phase refuses until the next phase."
        )
        rules["contracts"]["expiry_risk"] = (
            "A roster player publishing extension_quotes is in his final contract year. Unless he "
            "is extended this preseason he becomes a free agent when the season ends. Right after "
            f"contracts expire, rival teams get one signing look at the {EXPIRY_SCRAMBLE_CANDIDATES} "
            "best expiring players leaguewide, before your next phase opens."
        )
        rules["trades"] = {
            "declines_before_talks_end": REJECTED_OFFER_LIMIT_PER_WINDOW,
            "completed_trades_per_partner_per_season": TRADE_LIMIT_PER_PARTNER,
            "description": (
                "A trade must include at least one player or pick from each team; one that does "
                "not is an illegal move. A trade partner or free agent who has declined "
                f"{REJECTED_OFFER_LIMIT_PER_WINDOW} of your offers in a phase refuses every further "
                "offer until the next phase; those refusals are not penalized. Each partner "
                f"completes at most {TRADE_LIMIT_PER_PARTNER} trades with you per season, counting "
                "accepted offers and counters; proposing or accepting another is an illegal move "
                "and is penalized. A partner gives no trade value to a player you signed as a free "
                "agent or claimed off waivers this season."
            ),
        }
        rules["contracts"]["extension_terms"] = (
            "extend_contract replaces the player's final contract year. years (2 to 5) counts "
            "from the current season, so a 2-year extension covers this season and the next. The "
            "new salary applies to this season's payroll at once."
        )
        rules["pick_trading"]["tradable_seasons"] = window
        rules["pick_trading"]["description"] = (
            f"Only picks for draft seasons {window[0]} to {window[-1]} can be traded now. The window "
            "moves forward one season each season. The current season's pick cannot be traded; "
            "naming a season outside the window in a trade is an illegal move."
        )
        for pick in payload["team"]["picks"]:
            pick["tradable_now"] = pick["season"] in window
        for card in payload["team"].get("roster", []):
            card["injured_games"] = self.players[card["id"]].injured_games
        return payload

    def _inspect_player(self, action: dict[str, Any], phase: str) -> ActionResult:
        try:
            player_id = int(action.get("player_id", -1))
        except (TypeError, ValueError):
            return super()._inspect_player(action, phase)
        prospect = self.prospects.get(player_id)
        if player_id in self.players or prospect is None:
            return super()._inspect_player(action, phase)
        return self._record(
            action,
            phase,
            True,
            f"inspected draft prospect {prospect.name}",
            data={"player": {**prospect.public_dict(), "draft_prospect": True}},
            penalize=False,
        )

    def _sign_free_agent(self, action: dict[str, Any], phase: str) -> None:
        try:
            player_id = int(action.get("player_id", -1))
        except (TypeError, ValueError):
            super()._sign_free_agent(action, phase)
            return
        reason = None
        if player_id in self.waiver_wire:
            reason = "player is on the waiver wire, not a free agent; claim_waiver is the tool (midseason only)"
        elif player_id in self.prospects:
            reason = "that id is a draft prospect, not a free agent; prospects join a team through the draft"
        elif player_id in self.players and self.players[player_id].team_id is not None:
            team = self.teams[self.players[player_id].team_id]
            where = "your own roster" if team.id == self.user_team_id else f"{team.name} (team id {team.id})"
            reason = f"player is not a free agent: he is under contract on {where}"
        elif player_id not in self.players:
            reason = f"no player with id {player_id}"
        if reason is None:
            super()._sign_free_agent(action, phase)
            if player_id in self.user_team.roster:
                self.acquired_free[player_id] = self.season
        else:
            # Same outcome as 2.1's "player is not an available free agent": an illegal move.
            self._record(action, phase, False, reason)

    def _claim_waiver(self, action: dict[str, Any], phase: str) -> ActionResult:
        held = set(self.user_team.roster)
        result = super()._claim_waiver(action, phase)
        for player_id in set(self.user_team.roster) - held:
            self.acquired_free[player_id] = self.season
        return result

    def run_autopilot_opponents(self, phase: str = "preseason") -> None:
        super().run_autopilot_opponents(phase)
        if phase == "trade_deadline":
            self.current_offers = {}
