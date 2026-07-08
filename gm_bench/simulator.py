"""League simulation and action validation."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any

from gm_bench.generator import generate_draft_class, generate_league_data
from gm_bench.models import (
    LINEUP_MIN_POSITIONS,
    LINEUP_SIZE,
    PICK_TRADE_MAX_SEASONS_AHEAD,
    ROSTER_MIN,
    Player,
    SeasonSummary,
    Team,
    Transaction,
    pick_value,
)
from gm_bench.protocol import (
    INJURY_GAMES_DEFAULT,
    NON_PENALIZED_TYPES,
    PARTIAL_SEASON_FRACTION,
    PROTOCOL_VERSION,
    ActionResult,
    ObservationTier,
)
from gm_bench.scoring import score_team

TRADE_VALUE_THRESHOLD = 0.95
TRADE_LIMIT_PER_PARTNER = 2
MEMO_MAX_CHARS = 2000
HARD_CAP_BUFFER = 8.0
FA_RESERVATION_RANGE = (0.85, 1.0)
REJECTED_OFFER_LIMIT_PER_WINDOW = 2
SCOUT_POINTS_PER_SEASON = 3
SCOUT_REPORT_NOISE = 1.5
# A full season is this many games per team pairing. When a midseason break
# splits the season, the pre- and post-break legs must sum to exactly this so a
# midseason episode plays the same total schedule as a non-midseason one.
REGULAR_SEASON_GAMES_PER_PAIR = 3


@dataclass
class League:
    seed: int
    user_team_id: int = 0
    num_teams: int = 12
    cap: float = 86.0
    season: int = 1
    teams: dict[int, Team] = field(default_factory=dict)
    players: dict[int, Player] = field(default_factory=dict)
    free_agents: list[int] = field(default_factory=list)
    prospects: dict[int, Player] = field(default_factory=dict)
    transactions: list[Transaction] = field(default_factory=list)
    summaries: list[SeasonSummary] = field(default_factory=list)
    illegal_actions: int = 0
    rejected_offers: int = 0
    rng_state_offset: int = 0
    agent_memo: str = ""
    partner_trades: dict[int, int] = field(default_factory=dict)
    window_walkaways: dict[str, int] = field(default_factory=dict)
    current_offers: dict[str, dict[str, Any]] = field(default_factory=dict)
    scout_points_used: int = 0
    scout_reports: dict[int, float] = field(default_factory=dict)
    waiver_wire: list[int] = field(default_factory=list)
    partial_season_played: bool = False
    partial_games_per_pair: int = 0
    _action_results: list[ActionResult] = field(default_factory=list)

    @classmethod
    def new(cls, seed: int, user_team_id: int = 0, num_teams: int = 12) -> "League":
        teams, players, free_agents = generate_league_data(seed, num_teams=num_teams)
        league = cls(
            seed=seed,
            user_team_id=user_team_id,
            num_teams=num_teams,
            teams=teams,
            players=players,
            free_agents=free_agents,
        )
        league.prospects = generate_draft_class(seed, league.season, num_teams * 5)
        return league

    @property
    def user_team(self) -> Team:
        return self.teams[self.user_team_id]

    def observation(
        self,
        phase: str,
        *,
        tier: ObservationTier = "full",
        action_results: list[dict[str, Any]] | None = None,
        interaction_round: int = 0,
    ) -> dict[str, Any]:
        full = tier == "full"
        payload: dict[str, Any] = {
            "benchmark": PROTOCOL_VERSION,
            "seed": self.seed,
            "season": self.season,
            "phase": phase,
            "observation_tier": tier,
            "interaction_round": interaction_round,
            "rules": {
                "salary_cap": self.cap,
                "hard_cap_buffer": HARD_CAP_BUFFER,
                "roster_min": ROSTER_MIN,
                "lineup_size": LINEUP_SIZE,
                "lineup_min_positions": LINEUP_MIN_POSITIONS,
                "trade_value_threshold": TRADE_VALUE_THRESHOLD,
                "trade_limit_per_partner": TRADE_LIMIT_PER_PARTNER,
                "fa_reservation_range": list(FA_RESERVATION_RANGE),
                "rejected_offer_limit_per_window": REJECTED_OFFER_LIMIT_PER_WINDOW,
                "pick_trading": {
                    "max_seasons_ahead": PICK_TRADE_MAX_SEASONS_AHEAD,
                    "pick_value_estimate": {
                        str(season): round(pick_value(self.season, season), 2)
                        for season in self._tradeable_pick_seasons()
                    },
                },
                "scouting": {
                    "points_per_season": SCOUT_POINTS_PER_SEASON,
                    "points_remaining": SCOUT_POINTS_PER_SEASON - self.scout_points_used,
                    "report_noise": SCOUT_REPORT_NOISE,
                },
            },
            "team": self.user_team.public_dict(self.players, self.cap, full_roster=full),
            "standings": self._standings_public(),
            "draft_order": self._draft_order(),
            "incoming_offers": self._incoming_offers_public(),
            "scout_reports": {str(player_id): report for player_id, report in sorted(self.scout_reports.items())},
            "history": [summary.__dict__ for summary in self.summaries[-5:]],
            "recent_transactions": [transaction.__dict__ for transaction in self.transactions[-12:]],
            "memo": self.agent_memo,
            "available_actions": self._available_actions(phase),
        }
        if action_results:
            payload["action_results"] = action_results
        if full:
            payload["free_agents"] = [self._free_agent_public(player_id) for player_id in self.free_agents]
            payload["draft_class"] = [player.public_dict() for player in self.prospects.values()]
            payload["trade_market"] = self._trade_market_public()
            payload["waiver_wire"] = [self._waiver_player_public(player_id) for player_id in self.waiver_wire]
        else:
            payload["free_agents_summary"] = self._list_summary(
                self.free_agents, key=lambda pid: self.players[pid].overall, limit=8
            )
            payload["draft_class_summary"] = self._list_summary(
                list(self.prospects.keys()),
                key=lambda pid: self.prospects[pid].overall,
                limit=8,
            )
            payload["trade_market_summary"] = {"count": len(self._trade_market_public())}
            payload["waiver_wire_summary"] = self._list_summary(
                self.waiver_wire, key=lambda pid: self.players[pid].overall, limit=6
            )
            payload["hint"] = (
                "Use inspect_team, inspect_player, list_free_agents, or scout for details. "
                "Send end_turn when finished gathering information."
            )
        return payload

    def _list_summary(self, ids: list[int], *, key: Any, limit: int) -> dict[str, Any]:
        ordered = sorted(ids, key=key, reverse=True)
        return {"count": len(ids), "top_ids": ordered[:limit]}

    def prepare_trade_deadline(self) -> None:
        """Generate incoming offers once for this trade-deadline decision window."""
        self.current_offers = self._generate_incoming_offers("trade_deadline")

    def _available_actions(self, phase: str) -> list[str]:
        actions = [
            "sign_free_agent",
            "release",
            "trade",
            "set_lineup",
            "memo",
            "noop",
            "inspect_team",
            "inspect_player",
            "list_free_agents",
            "scout",
            "end_turn",
        ]
        if phase == "draft":
            actions.append("draft")
        if phase == "midseason":
            actions.append("claim_waiver")
        # Advertise negotiation actions from actual state, not the phase name:
        # they only apply when a pending incoming offer exists (trade deadline).
        if self.current_offers:
            actions.extend(["accept_trade_offer", "reject_trade_offer", "counter_trade_offer"])
        return actions

    def apply_actions(self, actions: list[dict[str, Any]], phase: str) -> list[ActionResult]:
        # Walk-aways last one decision window: each call to apply_actions is one
        # window, so counterparties who broke off talks come back next window.
        self.window_walkaways = {}
        self._action_results = []
        if not isinstance(actions, list):
            self._record({}, phase, False, "agent response must be a list of actions")
            return self._action_results
        for action in actions[:24]:
            if not isinstance(action, dict):
                self._record({}, phase, False, "action must be an object")
                continue
            action_type = action.get("type", "noop")
            if action_type == "end_turn":
                self._record(action, phase, True, "turn ended", penalize=False)
                break
            self._dispatch_action(action_type, action, phase)
        return self._action_results

    def _dispatch_action(self, action_type: str, action: dict[str, Any], phase: str) -> ActionResult:
        if action_type == "noop":
            return self._record(action, phase, True, "no-op", penalize=False)
        handlers = {
            "memo": self._memo,
            "sign_free_agent": self._sign_free_agent,
            "release": self._release,
            "trade": self._trade,
            "draft": self._draft,
            "set_lineup": self._set_lineup,
            "scout": self._scout,
            "inspect_team": self._inspect_team,
            "inspect_player": self._inspect_player,
            "list_free_agents": self._list_free_agents,
            "accept_trade_offer": self._accept_offer,
            "accept_offer": self._accept_offer,
            "reject_trade_offer": self._decline_offer,
            "decline_offer": self._decline_offer,
            "counter_trade_offer": self._counter_offer,
            "claim_waiver": self._claim_waiver,
        }
        handler = handlers.get(action_type)
        if handler is None:
            return self._record(action, phase, False, f"unknown action type {action_type!r}")
        return self._safe_apply(handler, action, phase)

    def _safe_apply(self, handler: Any, action: dict[str, Any], phase: str) -> ActionResult:
        try:
            result = handler(action, phase)
            if isinstance(result, ActionResult):
                return result
            # Mutating handlers still call _record without returning.
            return self._action_results[-1]
        except (TypeError, ValueError):
            return self._record(action, phase, False, "action has invalid or missing argument values")

    def run_autopilot_opponents(self, phase: str = "preseason") -> None:
        """Opponent front offices act after every user decision window.

        Preseason additionally trims oversized rosters. Every phase includes
        need-based and opportunistic free-agent signings, so the user has no
        monopoly on the free-agent pool between phases. At the trade deadline,
        opponents also make one-for-one trades among themselves.
        """
        rng = self._rng(f"opponents:{phase}")
        for team in self.teams.values():
            if team.id == self.user_team_id:
                continue
            if phase == "preseason":
                self._trim_expiring_contracts(team, rng)
            self._opponent_signings(team, rng)
        if phase == "trade_deadline":
            self._opponent_trades()

    def run_opponent_draft(self, before_user: bool) -> None:
        """Let opponents draft in inverse-standings order around the user's slot.

        Called twice per draft phase: once before the user's decision (teams
        picking ahead of the user) and once after (teams picking behind). The
        order is worst record first, team id as tiebreak.
        """
        order = self._draft_order()
        if self.user_team_id in order:
            user_index = order.index(self.user_team_id)
            picking = order[:user_index] if before_user else order[user_index + 1 :]
        else:
            picking = [] if before_user else order
        for team_id in picking:
            # A team that traded for extra picks exercises all of them at its slot.
            for _ in range(self.teams[team_id].draft_picks.get(self.season, 0)):
                self._opponent_draft_pick(self.teams[team_id])

    def prepare_midseason(self) -> None:
        if self.partial_season_played:
            return
        self.simulate_partial_season(PARTIAL_SEASON_FRACTION)
        self._generate_midseason_injuries()
        self._populate_waiver_wire()
        self.partial_season_played = True

    def simulate_partial_season(self, fraction: float) -> None:
        rng = self._rng("partial_season")
        ratings = {team.id: self._team_strength(team, apply_injury_noise=True, rng=rng) for team in self.teams.values()}
        # Round (not truncate) so the pre-break leg keeps its intended share, and
        # record it so simulate_season can play the exact complement.
        games_per_pair = max(1, min(REGULAR_SEASON_GAMES_PER_PAIR - 1, round(REGULAR_SEASON_GAMES_PER_PAIR * fraction)))
        self.partial_games_per_pair = games_per_pair
        for home in self.teams.values():
            for away in self.teams.values():
                if home.id >= away.id:
                    continue
                for _ in range(games_per_pair):
                    self._play_game(home, away, ratings, rng)
        self._update_morale_from_standings()

    def simulate_season(self) -> SeasonSummary:
        rng = self._rng("season")
        if not self.partial_season_played:
            for team in self.teams.values():
                team.wins = 0
                team.losses = 0
                team.playoff_rounds = 0
            games_per_pair = REGULAR_SEASON_GAMES_PER_PAIR
        else:
            # Play exactly the games the midseason leg didn't, so the two legs
            # sum to a full season rather than truncating each independently.
            for team in self.teams.values():
                team.playoff_rounds = 0
            games_per_pair = max(1, REGULAR_SEASON_GAMES_PER_PAIR - self.partial_games_per_pair)
        ratings = {team.id: self._team_strength(team, apply_injury_noise=True, rng=rng) for team in self.teams.values()}
        for home in self.teams.values():
            for away in self.teams.values():
                if home.id >= away.id:
                    continue
                for _ in range(games_per_pair):
                    self._play_game(home, away, ratings, rng)

        playoff_teams = sorted(self.teams.values(), key=lambda team: team.wins, reverse=True)[:8]
        champion = self._simulate_playoffs(playoff_teams, ratings, rng)
        champion.championships += 1

        self._age_and_contracts(rng)
        payroll = self._payroll(self.user_team)
        summary = SeasonSummary(
            season=self.season,
            wins=self.user_team.wins,
            losses=self.user_team.losses,
            payroll=round(payroll, 2),
            cap_room=round(self.cap - payroll, 2),
            champion_team_id=champion.id,
            playoff_rounds=self.user_team.playoff_rounds,
            score_after_season=round(score_team(self, self.user_team_id), 3),
        )
        self.summaries.append(summary)
        self.season += 1
        self.partner_trades = {}
        self.scout_points_used = 0
        # Offers are scoped to a decision window and regenerated on every
        # observation(); clear them at the season boundary so a stale offer_id
        # can never be accepted across seasons regardless of call order.
        self.current_offers = {}
        self.waiver_wire = []
        self.partial_season_played = False
        self.partial_games_per_pair = 0
        for team in self.teams.values():
            team.draft_picks.setdefault(self.season, 1)
        self.prospects = generate_draft_class(self.seed, self.season, self.num_teams * 5)
        return summary

    def _play_game(self, home: Team, away: Team, ratings: dict[int, float], rng: random.Random) -> None:
        probability = 1.0 / (1.0 + math.exp(-(ratings[home.id] - ratings[away.id]) / 7.5))
        if rng.random() < probability:
            home.wins += 1
            away.losses += 1
        else:
            away.wins += 1
            home.losses += 1

    def _update_morale_from_standings(self) -> None:
        ordered = sorted(self.teams.values(), key=lambda team: team.wins, reverse=True)
        for rank, team in enumerate(ordered):
            delta = 4.0 - rank * 0.6
            for player_id in team.roster:
                player = self.players[player_id]
                player.morale = min(100.0, max(20.0, player.morale + delta))

    def _generate_midseason_injuries(self) -> None:
        rng = self._rng("injuries")
        candidates = [player for player in self.players.values() if player.team_id is not None]
        rng.shuffle(candidates)
        for player in candidates[: rng.randint(2, 5)]:
            if rng.random() < player.injury_risk * 2.5:
                player.injured_games = max(player.injured_games, INJURY_GAMES_DEFAULT)

    def _populate_waiver_wire(self) -> None:
        rng = self._rng("waiver")
        opponents = [team for team in self.teams.values() if team.id != self.user_team_id]
        for team in opponents:
            if len(team.roster) <= ROSTER_MIN or rng.random() > 0.35:
                continue
            player = min((self.players[pid] for pid in team.roster), key=lambda item: item.asset_value)
            self._remove_from_team(team, player.id)
            player.team_id = None
            player.salary = 0.0
            player.contract_years = 0
            if player.id not in self.waiver_wire:
                self.waiver_wire.append(player.id)

    def _scout(self, action: dict[str, Any], phase: str) -> None:
        """Spend one scouting point for a near-true read on a player's potential.

        The report is `true_potential` plus small deterministic noise — far
        tighter than the public `potential` estimate. Reports persist across
        seasons and are echoed in every observation's `scout_reports`, so a
        point spent early keeps paying off. Noise is seeded per player (not via
        `_rng`), so scouting never perturbs the league's RNG stream.
        """
        player_id = int(action.get("player_id", -1))
        target = self.players.get(player_id) or self.prospects.get(player_id)
        if target is None:
            self._record(action, phase, False, "no such player or prospect to scout")
            return
        if player_id in self.scout_reports:
            self._record(action, phase, False, "player already scouted; see scout_reports")
            return
        if self.scout_points_used >= SCOUT_POINTS_PER_SEASON:
            self._record(action, phase, False, "no scouting points left this season")
            return
        noise = random.Random(f"{self.seed}:scout:{player_id}").uniform(-SCOUT_REPORT_NOISE, SCOUT_REPORT_NOISE)
        self.scout_points_used += 1
        self.scout_reports[player_id] = round(target.true_potential + noise, 1)
        self._record(action, phase, True, f"scouted {target.name}: potential ≈ {self.scout_reports[player_id]}")

    def _inspect_team(self, action: dict[str, Any], phase: str) -> ActionResult:
        team_id = int(action.get("team_id", -1))
        if team_id not in self.teams:
            return self._record(action, phase, False, "unknown team id", penalize=False)
        team = self.teams[team_id]
        data = {
            "team": team.public_dict(self.players, self.cap),
            "roster": [self.players[pid].public_dict() for pid in team.roster],
        }
        return self._record(action, phase, True, f"inspected {team.name}", data=data, penalize=False)

    def _inspect_player(self, action: dict[str, Any], phase: str) -> ActionResult:
        player_id = int(action.get("player_id", -1))
        if player_id not in self.players:
            return self._record(action, phase, False, "unknown player id", penalize=False)
        return self._record(
            action,
            phase,
            True,
            f"inspected {self.players[player_id].name}",
            data={"player": self.players[player_id].public_dict()},
            penalize=False,
        )

    def _list_free_agents(self, action: dict[str, Any], phase: str) -> ActionResult:
        position = action.get("position")
        min_overall = float(action.get("min_overall", 0.0))
        limit = min(24, max(1, int(action.get("limit", 12))))
        players = [self.players[pid] for pid in self.free_agents]
        if position in {"F", "D", "G"}:
            players = [player for player in players if player.position == position]
        players = [player for player in players if player.overall >= min_overall]
        players.sort(key=lambda player: player.overall, reverse=True)
        data = {"free_agents": [self._free_agent_public(player.id) for player in players[:limit]]}
        return self._record(
            action, phase, True, f"listed {len(data['free_agents'])} free agents", data=data, penalize=False
        )

    def _memo(self, action: dict[str, Any], phase: str) -> None:
        text = action.get("text", "")
        if not isinstance(text, str):
            self._record(action, phase, False, "memo text must be a string")
            return
        memo = text[:MEMO_MAX_CHARS]
        self.agent_memo = memo
        self._record({**action, "text": memo}, phase, True, "memo saved")

    def _sign_free_agent(self, action: dict[str, Any], phase: str) -> None:
        player_id = int(action.get("player_id", -1))
        years = int(action.get("years", 1))
        salary = float(action.get("salary", 0.0))
        if player_id not in self.free_agents or player_id not in self.players:
            self._record(action, phase, False, "player is not an available free agent")
            return
        if years < 1 or years > 5:
            self._record(action, phase, False, "contract years must be 1-5")
            return
        # A non-positive salary is not a negotiable bid — it is a malformed
        # action, so it must not ride the penalty-free rejected-offer path.
        if salary <= 0:
            self._record(action, phase, False, "salary must be a positive amount")
            return
        player = self.players[player_id]
        counterparty = f"player:{player_id}"
        if self._payroll(self.user_team) + salary > self.cap + HARD_CAP_BUFFER:
            self._record(action, phase, False, "signing would exceed hard cap buffer")
            return
        if self._walkaway(counterparty):
            self._record(
                action, phase, False, "player has broken off negotiations for this window", rejected_offer=True
            )
            return
        if salary < self._fa_reservation(player_id):
            self._note_rejection(counterparty)
            self._record(
                action,
                phase,
                False,
                f"player declines the offer; the ask is {player.asking_salary:.2f}",
                rejected_offer=True,
            )
            return
        self.free_agents.remove(player_id)
        player.team_id = self.user_team_id
        player.salary = round(salary, 2)
        player.contract_years = years
        self.user_team.roster.append(player_id)
        self._record(action, phase, True, f"signed {player.name}")

    def _release(self, action: dict[str, Any], phase: str) -> None:
        player_id = int(action.get("player_id", -1))
        if player_id not in self.user_team.roster:
            self._record(action, phase, False, "player is not on your roster")
            return
        if len(self.user_team.roster) <= ROSTER_MIN:
            self._record(action, phase, False, f"release would drop roster below the {ROSTER_MIN}-player minimum")
            return
        player = self.players[player_id]
        self._remove_from_team(self.user_team, player_id)
        player.team_id = None
        player.contract_years = 0
        player.salary = 0.0
        self.free_agents.append(player_id)
        self._record(action, phase, True, f"released {player.name}")

    def _trade(self, action: dict[str, Any], phase: str) -> None:
        partner_id = int(action.get("partner_team_id", -1))
        give = [int(player_id) for player_id in action.get("give_player_ids", [])]
        receive = [int(player_id) for player_id in action.get("receive_player_ids", [])]
        give_picks = [int(season) for season in action.get("give_pick_seasons", [])]
        receive_picks = [int(season) for season in action.get("receive_pick_seasons", [])]
        if partner_id not in self.teams or partner_id == self.user_team_id:
            self._record(action, phase, False, "invalid trade partner")
            return
        partner = self.teams[partner_id]
        if not (give or give_picks) or not (receive or receive_picks):
            self._record(action, phase, False, "trades must include assets from both teams")
            return
        pick_error = self._validate_pick_seasons(self.user_team, give_picks) or self._validate_pick_seasons(
            partner, receive_picks
        )
        if pick_error:
            self._record(action, phase, False, pick_error)
            return
        if len(set(give)) != len(give) or len(set(receive)) != len(receive):
            self._record(action, phase, False, "trade lists must not contain duplicate player ids")
            return
        if any(player_id not in self.user_team.roster for player_id in give):
            self._record(action, phase, False, "cannot trade players not on your roster")
            return
        if any(player_id not in partner.roster for player_id in receive):
            self._record(action, phase, False, "requested player is not on partner roster")
            return
        if self.partner_trades.get(partner_id, 0) >= TRADE_LIMIT_PER_PARTNER:
            self._record(action, phase, False, "partner has no appetite for more trades this season")
            return
        # Contract expiries can leave a team below the floor before it re-signs, so
        # only block trades that shrink a roster to below the minimum — a roster
        # already under the floor may still make size-neutral or growing trades.
        user_after = len(self.user_team.roster) - len(give) + len(receive)
        partner_after = len(partner.roster) - len(receive) + len(give)
        if user_after < ROSTER_MIN and user_after < len(self.user_team.roster):
            self._record(action, phase, False, f"trade would drop your roster below the {ROSTER_MIN}-player minimum")
            return
        if partner_after < ROSTER_MIN and partner_after < len(partner.roster):
            self._record(action, phase, False, f"trade would drop partner roster below the {ROSTER_MIN}-player minimum")
            return
        perceived_give = sum(
            self.players[player_id].asset_value * self._partner_valuation_bias(partner_id, player_id)
            for player_id in give
        ) + sum(
            pick_value(self.season, season) * self._partner_valuation_bias(partner_id, f"pick:{season}")
            for season in give_picks
        )
        perceived_receive = sum(
            self.players[player_id].asset_value * self._partner_valuation_bias(partner_id, player_id)
            for player_id in receive
        ) + sum(
            pick_value(self.season, season) * self._partner_valuation_bias(partner_id, f"pick:{season}")
            for season in receive_picks
        )
        partner_payroll_after = (
            self._payroll(partner)
            - sum(self.players[player_id].salary for player_id in receive)
            + sum(self.players[player_id].salary for player_id in give)
        )
        user_payroll_after = (
            self._payroll(self.user_team)
            - sum(self.players[player_id].salary for player_id in give)
            + sum(self.players[player_id].salary for player_id in receive)
        )
        if partner_payroll_after > self.cap + HARD_CAP_BUFFER or user_payroll_after > self.cap + HARD_CAP_BUFFER:
            self._record(action, phase, False, "trade would exceed hard cap buffer")
            return
        counterparty = f"team:{partner_id}"
        if self._walkaway(counterparty):
            self._record(
                action, phase, False, "partner has broken off trade talks for this window", rejected_offer=True
            )
            return
        if perceived_give < perceived_receive * TRADE_VALUE_THRESHOLD:
            self._note_rejection(counterparty)
            self._record(action, phase, False, "partner rejects the offer as too light", rejected_offer=True)
            return
        for player_id in give:
            self._remove_from_team(self.user_team, player_id)
            partner.roster.append(player_id)
            self.players[player_id].team_id = partner_id
        for player_id in receive:
            self._remove_from_team(partner, player_id)
            self.user_team.roster.append(player_id)
            self.players[player_id].team_id = self.user_team_id
        for season in give_picks:
            self._transfer_pick(self.user_team, partner, season)
        for season in receive_picks:
            self._transfer_pick(partner, self.user_team, season)
        self.partner_trades[partner_id] = self.partner_trades.get(partner_id, 0) + 1
        self._record(action, phase, True, "trade accepted")

    def _incoming_offers_public(self) -> list[dict[str, Any]]:
        """Publish the current incoming-offer pool without regenerating it.

        Offers are generated once per trade-deadline window via
        ``prepare_trade_deadline``. Observation only publishes whatever is
        currently in ``current_offers`` so multi-round interaction cannot
        resurrect an offer the agent already accepted or declined.
        """
        published = []
        for offer_id, offer in self.current_offers.items():
            published.append(
                {
                    "offer_id": offer_id,
                    "team_id": offer["partner_id"],
                    "team_name": self.teams[offer["partner_id"]].name,
                    "you_receive_players": [self.players[pid].public_dict() for pid in offer["you_receive"]],
                    "they_receive_players": [self.players[pid].public_dict() for pid in offer["they_receive"]],
                    "you_receive_pick_seasons": offer["you_receive_picks"],
                    "they_receive_pick_seasons": offer["they_receive_picks"],
                    "expires": "this decision point",
                }
            )
        return published

    def _generate_incoming_offers(self, phase: str) -> dict[str, dict[str, Any]]:
        """Build offers from partners' hidden valuations.

        A partner offers a player it privately undervalues and asks for a user
        player it perceives as at least as valuable — so every offer looks fair
        to the partner, but only some are good for the user. Distinguishing the
        bargains (partner undervalues a genuinely good player) from the traps
        (partner is offloading a genuinely bad one) is the skill being tested.
        Seeded directly, not via `_rng`, so publishing offers never perturbs the
        league's RNG stream — scripted baselines that ignore offers score
        identically with or without this feature.
        """
        rng = random.Random(f"{self.seed}:{self.season}:{phase}:incoming-offers")
        offers: dict[str, dict[str, Any]] = {}
        opponents = [team for team in self.teams.values() if team.id != self.user_team_id]
        rng.shuffle(opponents)
        for partner in opponents[:3]:
            if self.partner_trades.get(partner.id, 0) >= TRADE_LIMIT_PER_PARTNER:
                continue
            if len(partner.roster) <= ROSTER_MIN:
                continue
            offered = min(
                (self.players[player_id] for player_id in partner.roster),
                key=lambda player: player.asset_value * self._partner_valuation_bias(partner.id, player.id),
            )
            wanted_candidates = [
                self.players[player_id]
                for player_id in self.user_team.roster
                if self.players[player_id].asset_value * self._partner_valuation_bias(partner.id, player_id)
                >= offered.asset_value * self._partner_valuation_bias(partner.id, offered.id) * 1.03
            ]
            if not wanted_candidates or len(self.user_team.roster) <= ROSTER_MIN:
                continue
            # Ask for the cheapest user player that still clears the partner's bar,
            # keeping most offers plausible rather than obviously predatory.
            wanted = min(
                wanted_candidates,
                key=lambda player: player.asset_value * self._partner_valuation_bias(partner.id, player.id),
            )
            offer_id = f"offer-{partner.id}-{self.season}-{phase}-{offered.id}-{wanted.id}"
            offers[offer_id] = {
                "partner_id": partner.id,
                "you_receive": [offered.id],
                "they_receive": [wanted.id],
                "you_receive_picks": [],
                "they_receive_picks": [],
            }
        return offers

    def _accept_offer(self, action: dict[str, Any], phase: str) -> None:
        offer_id = str(action.get("offer_id", ""))
        offer = self.current_offers.get(offer_id)
        if offer is None:
            self._record(action, phase, False, "no such active offer (offers expire every decision point)")
            return
        partner = self.teams[offer["partner_id"]]
        you_receive = offer["you_receive"]
        they_receive = offer["they_receive"]
        if any(player_id not in partner.roster for player_id in you_receive) or any(
            player_id not in self.user_team.roster for player_id in they_receive
        ):
            self._record(action, phase, False, "offer is stale: a player already changed teams")
            return
        if self.partner_trades.get(partner.id, 0) >= TRADE_LIMIT_PER_PARTNER:
            self._record(action, phase, False, "partner has no appetite for more trades this season")
            return
        user_payroll_after = (
            self._payroll(self.user_team)
            - sum(self.players[pid].salary for pid in they_receive)
            + sum(self.players[pid].salary for pid in you_receive)
        )
        partner_payroll_after = (
            self._payroll(partner)
            - sum(self.players[pid].salary for pid in you_receive)
            + sum(self.players[pid].salary for pid in they_receive)
        )
        # Mirror _trade: neither side may be pushed past the hard-cap buffer.
        # Without the partner check, an accepted offer could dump salary onto a
        # partner who cannot afford it, which _trade would have rejected.
        if user_payroll_after > self.cap + HARD_CAP_BUFFER or partner_payroll_after > self.cap + HARD_CAP_BUFFER:
            self._record(action, phase, False, "accepting would exceed hard cap buffer")
            return
        for player_id in they_receive:
            self._remove_from_team(self.user_team, player_id)
            partner.roster.append(player_id)
            self.players[player_id].team_id = partner.id
        for player_id in you_receive:
            self._remove_from_team(partner, player_id)
            self.user_team.roster.append(player_id)
            self.players[player_id].team_id = self.user_team_id
        for season in offer["they_receive_picks"]:
            self._transfer_pick(self.user_team, partner, season)
        for season in offer["you_receive_picks"]:
            self._transfer_pick(partner, self.user_team, season)
        self.partner_trades[partner.id] = self.partner_trades.get(partner.id, 0) + 1
        del self.current_offers[offer_id]
        self._record(action, phase, True, f"accepted offer from {partner.name}")

    def _decline_offer(self, action: dict[str, Any], phase: str) -> None:
        offer_id = str(action.get("offer_id", ""))
        if offer_id not in self.current_offers:
            self._record(action, phase, False, "no such active offer")
            return
        partner = self.teams[self.current_offers[offer_id]["partner_id"]]
        del self.current_offers[offer_id]
        self._record(action, phase, True, f"declined offer from {partner.name}")

    def _counter_offer(self, action: dict[str, Any], phase: str) -> ActionResult:
        offer_id = str(action.get("offer_id", ""))
        offer = self.current_offers.get(offer_id)
        if offer is None:
            return self._record(action, phase, False, "no such active offer")
        trade_action = {
            "type": "trade",
            "partner_team_id": offer["partner_id"],
            "give_player_ids": action.get("give_player_ids", offer["they_receive"]),
            "receive_player_ids": action.get("receive_player_ids", offer["you_receive"]),
            "give_pick_seasons": action.get("give_pick_seasons", offer["they_receive_picks"]),
            "receive_pick_seasons": action.get("receive_pick_seasons", offer["you_receive_picks"]),
        }
        self._trade(trade_action, phase)
        result = self._action_results[-1]
        if result.accepted:
            del self.current_offers[offer_id]
            result.message = f"counter accepted for offer {offer_id}"
        return result

    def _claim_waiver(self, action: dict[str, Any], phase: str) -> ActionResult:
        if phase != "midseason":
            return self._record(action, phase, False, "waiver claims are only allowed during midseason")
        player_id = int(action.get("player_id", -1))
        if player_id not in self.waiver_wire:
            return self._record(action, phase, False, "player is not on the waiver wire")
        if self._payroll(self.user_team) + self.players[player_id].asking_salary > self.cap + HARD_CAP_BUFFER:
            return self._record(action, phase, False, "claim would exceed hard cap buffer")
        self.waiver_wire.remove(player_id)
        player = self.players[player_id]
        player.team_id = self.user_team_id
        player.salary = player.asking_salary
        player.contract_years = 1
        self.user_team.roster.append(player_id)
        return self._record(action, phase, True, f"claimed {player.name} from waivers")

    def _tradeable_pick_seasons(self) -> list[int]:
        return list(range(self.season + 1, self.season + PICK_TRADE_MAX_SEASONS_AHEAD + 1))

    def _picks_owned(self, team: Team, season: int) -> int:
        # The generator pre-grants one pick per team for early seasons; a season
        # beyond that horizon that no trade has touched is an implicit single pick.
        if season in team.draft_picks:
            return team.draft_picks[season]
        return 1 if season > self.season else 0

    def _validate_pick_seasons(self, owner: Team, seasons: list[int]) -> str | None:
        window = self._tradeable_pick_seasons()
        for season in seasons:
            if season not in window:
                return f"pick seasons must be between {window[0]} and {window[-1]}"
        for season in set(seasons):
            if seasons.count(season) > self._picks_owned(owner, season):
                return f"{owner.name} does not own enough season-{season} picks"
        return None

    def _transfer_pick(self, giver: Team, receiver: Team, season: int) -> None:
        giver.draft_picks[season] = self._picks_owned(giver, season) - 1
        receiver.draft_picks[season] = self._picks_owned(receiver, season) + 1

    def _draft(self, action: dict[str, Any], phase: str) -> None:
        if phase != "draft":
            self._record(action, phase, False, "draft actions are only allowed during the draft phase")
            return
        prospect_id = int(action.get("prospect_id", -1))
        if prospect_id not in self.prospects:
            self._record(action, phase, False, "prospect not in current draft class")
            return
        if self.user_team.draft_picks.get(self.season, 0) <= 0:
            self._record(action, phase, False, "no current-season draft pick available")
            return
        prospect = self._assign_prospect(self.user_team, prospect_id)
        self._record(action, phase, True, f"drafted {prospect.name}")

    def _set_lineup(self, action: dict[str, Any], phase: str) -> None:
        lineup = [int(player_id) for player_id in action.get("player_ids", [])]
        if len(lineup) != LINEUP_SIZE or len(set(lineup)) != LINEUP_SIZE:
            self._record(action, phase, False, f"lineup must contain {LINEUP_SIZE} unique player ids")
            return
        if any(player_id not in self.user_team.roster for player_id in lineup):
            self._record(action, phase, False, "lineup includes players not on roster")
            return
        positions = {"F": 0, "D": 0, "G": 0}
        for player_id in lineup:
            positions[self.players[player_id].position] += 1
        if any(positions[key] < LINEUP_MIN_POSITIONS[key] for key in LINEUP_MIN_POSITIONS):
            mins = ", ".join(f"{count} {pos}" for pos, count in LINEUP_MIN_POSITIONS.items())
            self._record(action, phase, False, f"lineup must include at least {mins}")
            return
        self.user_team.lineup = lineup
        self._record(action, phase, True, "lineup set")

    def _record(
        self,
        action: dict[str, Any],
        phase: str,
        accepted: bool,
        message: str,
        team_id: int | None = None,
        rejected_offer: bool = False,
        *,
        data: dict[str, Any] | None = None,
        penalize: bool | None = None,
    ) -> ActionResult:
        """Log an action. Declines that hinge on hidden valuations are counted as
        ``rejected_offers`` (legitimate negotiation, no protocol penalty); every
        other non-accepted action is a protocol violation unless ``penalize`` says
        otherwise (or the action type is in ``NON_PENALIZED_TYPES``)."""
        if team_id is None:
            team_id = self.user_team_id
        result = ActionResult(action=action, accepted=accepted, message=message, data=data)
        if not accepted and team_id == self.user_team_id:
            if rejected_offer:
                self.rejected_offers += 1
            else:
                should_penalize = (
                    penalize if penalize is not None else action.get("type", "") not in NON_PENALIZED_TYPES
                )
                if should_penalize:
                    self.illegal_actions += 1
        self.transactions.append(Transaction(self.season, phase, team_id, action, accepted, message))
        if team_id == self.user_team_id:
            self._action_results.append(result)
        return result

    def _walkaway(self, counterparty: str) -> bool:
        """Whether a counterparty has broken off negotiations for this window."""
        return self.window_walkaways.get(counterparty, 0) >= REJECTED_OFFER_LIMIT_PER_WINDOW

    def _note_rejection(self, counterparty: str) -> None:
        self.window_walkaways[counterparty] = self.window_walkaways.get(counterparty, 0) + 1

    def _fa_reservation(self, player_id: int) -> float:
        """Hidden, deterministic minimum salary a free agent will accept.

        A per-player fraction of the asking price in FA_RESERVATION_RANGE,
        re-rolled each season, so the optimal bid can be estimated but not
        solved from the observation. Offering the full ask always succeeds.
        Seeded directly (not via `_rng`) so evaluating an offer never perturbs
        the league's RNG stream.
        """
        rng = random.Random(f"{self.seed}:{self.season}:reservation:{player_id}")
        low, high = FA_RESERVATION_RANGE
        return self.players[player_id].asking_salary * rng.uniform(low, high)

    def _standings_public(self) -> list[dict[str, Any]]:
        return [
            {
                "team_id": team.id,
                "team_name": team.name,
                "wins": team.wins,
                "losses": team.losses,
                "championships": team.championships,
                "public_strength": round(self._team_strength(team, apply_injury_noise=False), 1),
                "draft_picks": dict(sorted(team.draft_picks.items())),
            }
            for team in sorted(self.teams.values(), key=lambda item: item.wins, reverse=True)
        ]

    def _free_agent_public(self, player_id: int) -> dict[str, Any]:
        player = self.players[player_id].public_dict()
        player["asking_salary"] = self.players[player_id].asking_salary
        return player

    def _waiver_player_public(self, player_id: int) -> dict[str, Any]:
        player = self.players[player_id].public_dict()
        player["asking_salary"] = self.players[player_id].asking_salary
        return player

    def _trade_market_public(self) -> list[dict[str, Any]]:
        market: list[dict[str, Any]] = []
        for team in self.teams.values():
            if team.id == self.user_team_id:
                continue
            candidates = sorted(
                (self.players[player_id] for player_id in team.roster),
                key=self._public_trade_estimate,
            )
            for player in candidates[:2]:
                market.append(
                    {
                        "team_id": team.id,
                        "team_name": team.name,
                        "player": player.public_dict(),
                        "estimated_price": self._public_trade_estimate(player),
                    }
                )
        return sorted(market, key=lambda item: item["estimated_price"])[:24]

    @staticmethod
    def _public_trade_estimate(player: Player) -> float:
        """Noisy public trade valuation using only visible player attributes."""
        age_factor = max(0.05, 1.14 - max(player.age - 23, 0) * 0.05)
        public_skill = player.overall * 0.55 + player.potential * 0.45
        contract_drag = player.salary * 0.55 if player.salary > 0 else 0.0
        return round(max(1.0, (public_skill - 44.0) * age_factor - contract_drag), 2)

    def _partner_valuation_bias(self, partner_id: int, player_id: int | str) -> float:
        """Hidden, deterministic per-partner scouting bias on a player's or pick's value.

        Re-rolled each season so trade acceptance cannot be computed exactly from
        public observations, only estimated. Seeded directly (not via `_rng`) so
        evaluating an offer never perturbs the league's RNG stream.
        """
        rng = random.Random(f"{self.seed}:{self.season}:valuation:{partner_id}:{player_id}")
        return rng.uniform(0.9, 1.1)

    def _draft_order(self) -> list[int]:
        """Current-season pick order: worst record first, team id as tiebreak."""
        ordered = sorted(self.teams.values(), key=lambda team: (team.wins, team.id))
        return [team.id for team in ordered if team.draft_picks.get(self.season, 0) > 0]

    def _opponent_draft_pick(self, team: Team) -> None:
        if not self.prospects or team.draft_picks.get(self.season, 0) <= 0:
            return
        prospect_id = max(
            self.prospects,
            key=lambda pid: (
                self.prospects[pid].potential * 0.6 + self.prospects[pid].overall * 0.4 - self.prospects[pid].age * 0.3,
                -pid,
            ),
        )
        prospect = self._assign_prospect(team, prospect_id)
        self._record(
            {"type": "draft", "prospect_id": prospect.id},
            "draft",
            True,
            f"{team.name} drafted {prospect.name}",
            team_id=team.id,
        )

    def _assign_prospect(self, team: Team, prospect_id: int) -> Player:
        prospect = self.prospects.pop(prospect_id)
        prospect.team_id = team.id
        prospect.salary = 0.95
        prospect.contract_years = 3
        prospect.drafted_round = 1
        self.players[prospect.id] = prospect
        team.roster.append(prospect.id)
        team.draft_picks[self.season] -= 1
        return prospect

    def _remove_from_team(self, team: Team, player_id: int) -> None:
        team.roster.remove(player_id)
        if player_id in team.lineup:
            team.lineup.remove(player_id)

    def _effective_lineup(self, team: Team) -> list[Player]:
        """The players who actually dress: the set lineup, repaired as needed.

        Starts from the team's stored lineup (ids no longer on the roster are
        skipped), tops up to LINEUP_SIZE with the best remaining players by
        overall, then swaps in bench players to satisfy position minimums.
        Teams with no stored lineup get a best-legal auto lineup.
        """
        roster = [self.players[player_id] for player_id in team.roster]
        if len(roster) <= LINEUP_SIZE:
            return roster
        roster_ids = set(team.roster)
        chosen: dict[int, Player] = {}
        for player_id in dict.fromkeys(team.lineup):
            if player_id in roster_ids and len(chosen) < LINEUP_SIZE:
                chosen[player_id] = self.players[player_id]
        bench = sorted((player for player in roster if player.id not in chosen), key=lambda p: p.overall, reverse=True)
        for player in bench:
            if len(chosen) >= LINEUP_SIZE:
                break
            chosen[player.id] = player
        for position, minimum in LINEUP_MIN_POSITIONS.items():
            candidates = [player for player in bench if player.id not in chosen and player.position == position]
            while sum(1 for player in chosen.values() if player.position == position) < minimum and candidates:
                surplus = [
                    player
                    for player in chosen.values()
                    if player.position != position
                    and sum(1 for other in chosen.values() if other.position == player.position)
                    > LINEUP_MIN_POSITIONS[player.position]
                ]
                if not surplus:
                    break
                drop = min(surplus, key=lambda player: player.overall)
                del chosen[drop.id]
                add = candidates.pop(0)
                chosen[add.id] = add
        return list(chosen.values())

    def _team_strength(self, team: Team, apply_injury_noise: bool, rng: random.Random | None = None) -> float:
        lineup = sorted(self._effective_lineup(team), key=lambda player: player.overall, reverse=True)
        if not lineup:
            return 20.0
        position_bonus = min(sum(1 for player in lineup if player.position == "G"), 2) * 2.5
        weighted = 0.0
        total_weight = 0.0
        for index, player in enumerate(lineup):
            weight = 1.0 if index < 6 else 0.74 if index < 12 else 0.48
            effective = player.overall
            if apply_injury_noise and rng is not None and rng.random() < player.injury_risk:
                effective -= rng.uniform(5.0, 18.0)
            weighted += effective * weight
            total_weight += weight
        cap_penalty = max(0.0, self._payroll(team) - self.cap) * 0.25
        return weighted / total_weight + position_bonus - cap_penalty

    def _simulate_playoffs(self, teams: list[Team], ratings: dict[int, float], rng: random.Random) -> Team:
        bracket = teams[:]
        rounds = 0
        while len(bracket) > 1:
            rounds += 1
            next_round: list[Team] = []
            for index in range(0, len(bracket), 2):
                home = bracket[index]
                away = bracket[-index - 1]
                probability = 1.0 / (1.0 + math.exp(-(ratings[home.id] - ratings[away.id]) / 6.0))
                winner = home if rng.random() < probability else away
                winner.playoff_rounds = max(winner.playoff_rounds, rounds)
                next_round.append(winner)
            bracket = next_round
        return bracket[0]

    def _age_and_contracts(self, rng: random.Random) -> None:
        dressed: set[int] = set()
        for team in self.teams.values():
            dressed.update(player.id for player in self._effective_lineup(team))
        for player in list(self.players.values()):
            player.age += 1
            if player.team_id is None:
                # Free agents get no playing time: they rust slightly and decline
                # normally with age, but never develop.
                if player.age >= 30:
                    player.overall -= rng.uniform(0.4, 1.9) * (1.0 + max(player.age - 33, 0) * 0.15)
                else:
                    player.overall -= rng.uniform(0.0, 0.6)
                player.overall = min(92.0, max(30.0, player.overall))
                player.potential = min(97.0, max(30.0, player.potential + rng.gauss(0, 1.2)))
                continue
            growth_room = max(0.0, player.true_potential - player.overall)
            if player.age <= 24:
                # Playing time drives development: bench players grow at half rate.
                usage = 1.0 if player.id in dressed else 0.5
                player.overall += rng.uniform(0.2, 2.8) * min(1.0, growth_room / 10.0) * usage
            elif player.age >= 30:
                player.overall -= rng.uniform(0.4, 1.9) * (1.0 + max(player.age - 33, 0) * 0.15)
            else:
                player.overall += rng.uniform(-0.5, 0.8)
            player.overall = min(92.0, max(30.0, player.overall))
            player.potential = min(97.0, max(30.0, player.potential + rng.gauss(0, 1.2)))
            player.contract_years -= 1
            if player.contract_years <= 0:
                team = self.teams.get(player.team_id)
                if team and player.id in team.roster:
                    self._remove_from_team(team, player.id)
                player.team_id = None
                player.salary = 0.0
                player.contract_years = 0
                self.free_agents.append(player.id)

    def _trim_expiring_contracts(self, team: Team, rng: random.Random) -> None:
        if len(team.roster) <= 23:
            return
        excess = sorted((self.players[player_id] for player_id in team.roster), key=lambda player: player.asset_value)
        for player in excess[: max(0, len(team.roster) - 23)]:
            self._remove_from_team(team, player.id)
            player.team_id = None
            player.salary = 0.0
            player.contract_years = 0
            self.free_agents.append(player.id)

    def _opponent_signings(self, team: Team, rng: random.Random) -> None:
        needed = max(0, 21 - len(team.roster))
        candidates = sorted(
            (self.players[player_id] for player_id in self.free_agents), key=lambda player: player.overall, reverse=True
        )
        for player in candidates[: needed * 2]:
            if needed <= 0:
                break
            ask = player.asking_salary
            if self._payroll(team) + ask <= self.cap + 4.0:
                self._sign_to_team(team, player, rng)
                needed -= 1
        self._opponent_opportunistic_signing(team, rng)

    def _opponent_opportunistic_signing(self, team: Team, rng: random.Random) -> None:
        """Sign one clear upgrade over the team's weakest dressed player.

        This is what makes free agency competitive: opponents grab standout
        free agents between phases instead of leaving the pool untouched for
        the user, so waiting on a signing carries real risk. A team with a
        full roster waives its least valuable player to make room, but only
        when the incoming player is clearly better than the one waived.
        """
        lineup = self._effective_lineup(team)
        if not lineup:
            return
        floor_overall = min(player.overall for player in lineup)
        upgrades = sorted(
            (
                self.players[player_id]
                for player_id in self.free_agents
                if self.players[player_id].overall >= floor_overall + 2.0
            ),
            key=lambda player: player.overall,
            reverse=True,
        )
        for player in upgrades:
            waived: Player | None = None
            if len(team.roster) >= 23:
                waived = min((self.players[player_id] for player_id in team.roster), key=lambda item: item.asset_value)
                if waived.overall + 2.0 >= player.overall:
                    continue
            payroll_after = self._payroll(team) - (waived.salary if waived else 0.0) + player.asking_salary
            if payroll_after > self.cap + 4.0:
                continue
            if waived is not None:
                self._remove_from_team(team, waived.id)
                waived.team_id = None
                waived.salary = 0.0
                waived.contract_years = 0
                self.free_agents.append(waived.id)
            self._sign_to_team(team, player, rng)
            return

    def _sign_to_team(self, team: Team, player: Player, rng: random.Random) -> None:
        self.free_agents.remove(player.id)
        team.roster.append(player.id)
        player.team_id = team.id
        player.salary = player.asking_salary
        player.contract_years = rng.randint(1, 3)

    def _opponent_trades(self) -> None:
        """One deadline round of one-for-one swaps between opponent teams.

        Each front office evaluates a swap with its own hidden valuation bias,
        so a trade happens only when both sides believe they gain. Every
        opponent participates in at most one such trade per season. Trades are
        recorded in the transaction feed as market signal for the user.
        """
        traded: set[int] = set()
        opponents = [team for team in self.teams.values() if team.id != self.user_team_id]
        for index, team_a in enumerate(opponents):
            if team_a.id in traded:
                continue
            for team_b in opponents[index + 1 :]:
                if team_b.id in traded:
                    continue
                swap = self._find_mutual_swap(team_a, team_b)
                if swap is None:
                    continue
                player_a, player_b = swap
                self._remove_from_team(team_a, player_a.id)
                self._remove_from_team(team_b, player_b.id)
                team_a.roster.append(player_b.id)
                team_b.roster.append(player_a.id)
                player_a.team_id = team_b.id
                player_b.team_id = team_a.id
                traded.add(team_a.id)
                traded.add(team_b.id)
                self._record(
                    {
                        "type": "trade",
                        "partner_team_id": team_b.id,
                        "give_player_ids": [player_a.id],
                        "receive_player_ids": [player_b.id],
                    },
                    "trade_deadline",
                    True,
                    f"{team_a.name} traded {player_a.name} to {team_b.name} for {player_b.name}",
                    team_id=team_a.id,
                )
                break

    def _find_mutual_swap(self, team_a: Team, team_b: Team) -> tuple[Player, Player] | None:
        """Find a same-position swap both teams' hidden valuations prefer.

        Each team shops from the five players it privately values least; the
        divergent per-team biases are what create genuine win-win swaps.
        """

        def shop_list(team: Team) -> list[Player]:
            return sorted(
                (self.players[player_id] for player_id in team.roster),
                key=lambda player: player.asset_value * self._partner_valuation_bias(team.id, player.id),
            )[:5]

        def perceived(team: Team, player: Player) -> float:
            return player.asset_value * self._partner_valuation_bias(team.id, player.id)

        for player_a in shop_list(team_a):
            for player_b in shop_list(team_b):
                if player_a.position != player_b.position:
                    continue
                if perceived(team_a, player_b) < perceived(team_a, player_a) * 1.03:
                    continue
                if perceived(team_b, player_a) < perceived(team_b, player_b) * 1.03:
                    continue
                payroll_a = self._payroll(team_a) - player_a.salary + player_b.salary
                payroll_b = self._payroll(team_b) - player_b.salary + player_a.salary
                if payroll_a > self.cap + HARD_CAP_BUFFER or payroll_b > self.cap + HARD_CAP_BUFFER:
                    continue
                return player_a, player_b
        return None

    def _payroll(self, team: Team) -> float:
        return sum(self.players[player_id].salary for player_id in team.roster)

    def _rng(self, namespace: str) -> random.Random:
        self.rng_state_offset += 1
        return random.Random(f"{self.seed}:{self.season}:{self.rng_state_offset}:{namespace}")
