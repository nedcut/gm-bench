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
    ROSTER_MIN,
    Player,
    SeasonSummary,
    Team,
    Transaction,
)
from gm_bench.protocol import (
    BENCHMARK_VERSION,
    INJURY_GAMES_DEFAULT,
    NON_PENALIZED_TYPES,
    PARTIAL_SEASON_FRACTION,
    SCOUTS_PER_SEASON,
    ActionResult,
    IncomingTradeOffer,
    ObservationTier,
)
from gm_bench.scoring import score_team

TRADE_VALUE_THRESHOLD = 0.95
TRADE_LIMIT_PER_PARTNER = 2
MEMO_MAX_CHARS = 2000
HARD_CAP_BUFFER = 8.0
PICK_ASSET_VALUE = 14.0
# A full season is this many games per team pairing. When a midseason break
# splits the season, the pre- and post-break legs must sum to exactly this so a
# midseason episode plays the same total schedule as a --no-midseason one.
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
    rng_state_offset: int = 0
    agent_memo: str = ""
    partner_trades: dict[int, int] = field(default_factory=dict)
    waiver_wire: list[int] = field(default_factory=list)
    incoming_trade_offers: list[IncomingTradeOffer] = field(default_factory=list)
    scouted_players: dict[int, dict[str, float]] = field(default_factory=dict)
    scouts_used_this_season: int = 0
    partial_season_played: bool = False
    partial_games_per_pair: int = 0
    _incoming_offer_counter: int = 0

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
            "benchmark": BENCHMARK_VERSION,
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
                "scouts_per_season": SCOUTS_PER_SEASON,
                "supports_draft_pick_trades": True,
            },
            "team": self.user_team.public_dict(self.players, self.cap, full_roster=full),
            "standings": self._standings_public(),
            "draft_order": self._draft_order(),
            "history": [summary.__dict__ for summary in self.summaries[-5:]],
            "recent_transactions": [transaction.__dict__ for transaction in self.transactions[-12:]],
            "memo": self.agent_memo,
            "scouting_budget": {
                "used": self.scouts_used_this_season,
                "remaining": max(0, SCOUTS_PER_SEASON - self.scouts_used_this_season),
            },
            "incoming_trade_offers": [offer.public_dict(self.players) for offer in self.incoming_trade_offers],
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
        # they only apply to a pending incoming offer, which exists solely at the
        # trade deadline. Listing them when the offer queue is empty would tempt
        # an agent into an "offer not found" move that is penalized as illegal.
        if self.incoming_trade_offers:
            actions.extend(["accept_trade_offer", "reject_trade_offer", "counter_trade_offer"])
        return actions

    def _list_summary(self, ids: list[int], *, key: Any, limit: int) -> dict[str, Any]:
        ordered = sorted(ids, key=key, reverse=True)
        return {"count": len(ids), "top_ids": ordered[:limit]}

    def apply_actions(self, actions: list[dict[str, Any]], phase: str) -> list[ActionResult]:
        results: list[ActionResult] = []
        if not isinstance(actions, list):
            results.append(self._record({}, phase, False, "agent response must be a list of actions"))
            return results
        terminal = False
        for action in actions[:24]:
            if terminal:
                break
            if not isinstance(action, dict):
                results.append(self._record({}, phase, False, "action must be an object"))
                continue
            action_type = action.get("type", "noop")
            if action_type == "end_turn":
                results.append(self._record(action, phase, True, "turn ended", penalize=False))
                terminal = True
                continue
            result = self._dispatch_action(action_type, action, phase)
            results.append(result)
        return results

    def _dispatch_action(self, action_type: str, action: dict[str, Any], phase: str) -> ActionResult:
        handlers = {
            "noop": self._memo_noop,
            "memo": self._memo,
            "sign_free_agent": self._sign_free_agent,
            "release": self._release,
            "trade": self._trade,
            "draft": self._draft,
            "set_lineup": self._set_lineup,
            "inspect_team": self._inspect_team,
            "inspect_player": self._inspect_player,
            "list_free_agents": self._list_free_agents,
            "scout": self._scout,
            "accept_trade_offer": self._accept_trade_offer,
            "reject_trade_offer": self._reject_trade_offer,
            "counter_trade_offer": self._counter_trade_offer,
            "claim_waiver": self._claim_waiver,
        }
        handler = handlers.get(action_type)
        if handler is None:
            return self._record(action, phase, False, f"unknown action type {action_type!r}")
        return self._safe_apply(handler, action, phase)

    def _memo_noop(self, action: dict[str, Any], phase: str) -> ActionResult:
        return self._record(action, phase, True, "no-op", penalize=False)

    def _safe_apply(self, handler: Any, action: dict[str, Any], phase: str) -> ActionResult:
        try:
            return handler(action, phase)
        except (TypeError, ValueError):
            action_type = action.get("type", "")
            penalize = action_type not in NON_PENALIZED_TYPES
            return self._record(
                action, phase, False, "action has invalid or missing argument values", penalize=penalize
            )

    def prepare_midseason(self) -> None:
        if self.partial_season_played:
            return
        self.simulate_partial_season(PARTIAL_SEASON_FRACTION)
        self._generate_midseason_injuries()
        self._populate_waiver_wire()
        self.partial_season_played = True

    def prepare_trade_deadline(self) -> None:
        self._generate_incoming_trade_offers()

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

    def run_autopilot_opponents(self, phase: str = "preseason") -> None:
        rng = self._rng(f"opponents:{phase}")
        for team in self.teams.values():
            if team.id == self.user_team_id:
                continue
            if phase == "preseason":
                self._trim_expiring_contracts(team, rng)
            self._opponent_signings(team, rng)
            if phase == "midseason":
                self._opponent_waiver_claim(team, rng)
        if phase == "trade_deadline":
            self._opponent_trades()

    def run_opponent_draft(self, before_user: bool) -> None:
        order = self._draft_order()
        if self.user_team_id in order:
            user_index = order.index(self.user_team_id)
            picking = order[:user_index] if before_user else order[user_index + 1 :]
        else:
            picking = [] if before_user else order
        for team_id in picking:
            self._opponent_draft_pick(self.teams[team_id])

    def simulate_season(self) -> SeasonSummary:
        rng = self._rng("season")
        if not self.partial_season_played:
            for team in self.teams.values():
                team.wins = 0
                team.losses = 0
            games_per_pair = REGULAR_SEASON_GAMES_PER_PAIR
        else:
            # Play exactly the games the midseason leg didn't, so the two legs
            # sum to a full season rather than truncating each independently.
            games_per_pair = max(1, REGULAR_SEASON_GAMES_PER_PAIR - self.partial_games_per_pair)
        ratings = {team.id: self._team_strength(team, apply_injury_noise=True, rng=rng) for team in self.teams.values()}
        for home in self.teams.values():
            for away in self.teams.values():
                if home.id >= away.id:
                    continue
                for _ in range(games_per_pair):
                    self._play_game(home, away, ratings, rng)

        for team in self.teams.values():
            team.playoff_rounds = 0
        playoff_teams = sorted(self.teams.values(), key=lambda team: team.wins, reverse=True)[:8]
        champion = self._simulate_playoffs(playoff_teams, ratings, rng)
        champion.championships += 1
        self._update_morale_from_standings()

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
        self.scouts_used_this_season = 0
        self.scouted_players = {}
        self.incoming_trade_offers = []
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

    def _generate_incoming_trade_offers(self) -> None:
        self.incoming_trade_offers = []
        rng = self._rng("incoming_offers")
        opponents = [team for team in self.teams.values() if team.id != self.user_team_id]
        rng.shuffle(opponents)
        for partner in opponents[:3]:
            offer = self._build_incoming_offer(partner, rng)
            if offer is not None:
                self.incoming_trade_offers.append(offer)

    def _build_incoming_offer(self, partner: Team, rng: random.Random) -> IncomingTradeOffer | None:
        if len(partner.roster) < 2 or len(self.user_team.roster) < 2:
            return None
        give_player = min(
            (self.players[pid] for pid in partner.roster),
            key=lambda player: player.asset_value * self._partner_valuation_bias(partner.id, player.id),
        )
        receive_candidates = [
            self.players[pid] for pid in self.user_team.roster if self.players[pid].position == give_player.position
        ]
        if not receive_candidates:
            receive_candidates = [self.players[pid] for pid in self.user_team.roster]
        receive_player = max(receive_candidates, key=lambda player: player.overall)
        if receive_player.id == give_player.id:
            return None
        self._incoming_offer_counter += 1
        give_picks: list[int] = []
        receive_picks: list[int] = []
        if rng.random() < 0.25 and partner.draft_picks.get(self.season + 1, 0) > 0:
            give_picks = [self.season + 1]
        return IncomingTradeOffer(
            offer_id=f"{self.season}-{self._incoming_offer_counter}",
            from_team_id=partner.id,
            from_team_name=partner.name,
            give_player_ids=[give_player.id],
            receive_player_ids=[receive_player.id],
            give_pick_seasons=give_picks,
            receive_pick_seasons=receive_picks,
        )

    def _memo(self, action: dict[str, Any], phase: str) -> ActionResult:
        text = action.get("text", "")
        if not isinstance(text, str):
            return self._record(action, phase, False, "memo text must be a string", penalize=False)
        memo = text[:MEMO_MAX_CHARS]
        self.agent_memo = memo
        return self._record({**action, "text": memo}, phase, True, "memo saved", penalize=False)

    def _inspect_team(self, action: dict[str, Any], phase: str) -> ActionResult:
        team_id = int(action.get("team_id", -1))
        if team_id not in self.teams:
            return self._record(action, phase, False, "unknown team id", penalize=False)
        team = self.teams[team_id]
        roster = [self._player_detail(self.players[pid]) for pid in team.roster]
        data = {
            "team": team.public_dict(self.players, self.cap, full_roster=False),
            "roster": roster,
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
            data={"player": self._player_detail(self.players[player_id])},
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

    def _scout(self, action: dict[str, Any], phase: str) -> ActionResult:
        if self.scouts_used_this_season >= SCOUTS_PER_SEASON:
            return self._record(action, phase, False, "no scouting budget remaining", penalize=False)
        player_id = int(action.get("player_id", -1))
        prospect_id = action.get("prospect_id")
        target: Player | None = None
        if player_id in self.players:
            target = self.players[player_id]
        elif prospect_id is not None and int(prospect_id) in self.prospects:
            target = self.prospects[int(prospect_id)]
        if target is None:
            return self._record(action, phase, False, "scout target not found", penalize=False)
        self.scouts_used_this_season += 1
        spread = max(2.0, (100.0 - target.potential) * 0.08)
        report = {
            "player_id": target.id,
            "true_potential_estimate": {
                "low": round(max(30.0, target.true_potential - spread), 1),
                "high": round(min(97.0, target.true_potential + spread), 1),
            },
            "public_potential": round(target.potential, 1),
        }
        self.scouted_players[target.id] = report["true_potential_estimate"]
        return self._record(action, phase, True, f"scouted {target.name}", data=report, penalize=False)

    def _player_detail(self, player: Player) -> dict[str, Any]:
        payload = player.public_dict()
        if player.id in self.scouted_players:
            payload["scouted_true_potential"] = self.scouted_players[player.id]
        if player.team_id is None and player.id in self.free_agents:
            payload["asking_salary"] = player.asking_salary
        return payload

    def _accept_trade_offer(self, action: dict[str, Any], phase: str) -> ActionResult:
        offer = self._find_offer(action.get("offer_id"))
        if offer is None:
            return self._record(action, phase, False, "trade offer not found")
        trade_action = {
            "type": "trade",
            "partner_team_id": offer.from_team_id,
            "give_player_ids": list(offer.receive_player_ids),
            "receive_player_ids": list(offer.give_player_ids),
            "give_pick_seasons": list(offer.receive_pick_seasons),
            "receive_pick_seasons": list(offer.give_pick_seasons),
        }
        result = self._trade(trade_action, phase)
        if result.accepted:
            self.incoming_trade_offers = [
                item for item in self.incoming_trade_offers if item.offer_id != offer.offer_id
            ]
            result.message = f"accepted offer {offer.offer_id}"
        return result

    def _reject_trade_offer(self, action: dict[str, Any], phase: str) -> ActionResult:
        offer = self._find_offer(action.get("offer_id"))
        if offer is None:
            return self._record(action, phase, False, "trade offer not found")
        self.incoming_trade_offers = [item for item in self.incoming_trade_offers if item.offer_id != offer.offer_id]
        return self._record(action, phase, True, f"rejected offer {offer.offer_id}")

    def _counter_trade_offer(self, action: dict[str, Any], phase: str) -> ActionResult:
        offer = self._find_offer(action.get("offer_id"))
        if offer is None:
            return self._record(action, phase, False, "trade offer not found")
        trade_action = {
            "type": "trade",
            "partner_team_id": offer.from_team_id,
            "give_player_ids": [int(pid) for pid in action.get("give_player_ids", offer.receive_player_ids)],
            "receive_player_ids": [int(pid) for pid in action.get("receive_player_ids", offer.give_player_ids)],
            "give_pick_seasons": [int(year) for year in action.get("give_pick_seasons", offer.receive_pick_seasons)],
            "receive_pick_seasons": [int(year) for year in action.get("receive_pick_seasons", offer.give_pick_seasons)],
        }
        result = self._trade(trade_action, phase)
        if result.accepted:
            self.incoming_trade_offers = [
                item for item in self.incoming_trade_offers if item.offer_id != offer.offer_id
            ]
            result.message = f"counter accepted for offer {offer.offer_id}"
        return result

    def _find_offer(self, offer_id: Any) -> IncomingTradeOffer | None:
        if not isinstance(offer_id, str):
            return None
        for offer in self.incoming_trade_offers:
            if offer.offer_id == offer_id:
                return offer
        return None

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

    def _sign_free_agent(self, action: dict[str, Any], phase: str) -> ActionResult:
        player_id = int(action.get("player_id", -1))
        years = int(action.get("years", 1))
        salary = float(action.get("salary", 0.0))
        if player_id not in self.free_agents or player_id not in self.players:
            return self._record(action, phase, False, "player is not an available free agent")
        if years < 1 or years > 5:
            return self._record(action, phase, False, "contract years must be 1-5")
        player = self.players[player_id]
        minimum = player.asking_salary * 0.9
        if salary < minimum:
            return self._record(action, phase, False, f"salary below player's market ask of {minimum:.2f}")
        if self._payroll(self.user_team) + salary > self.cap + HARD_CAP_BUFFER:
            return self._record(action, phase, False, "signing would exceed hard cap buffer")
        self.free_agents.remove(player_id)
        player.team_id = self.user_team_id
        player.salary = round(salary, 2)
        player.contract_years = years
        self.user_team.roster.append(player_id)
        return self._record(action, phase, True, f"signed {player.name}")

    def _release(self, action: dict[str, Any], phase: str) -> ActionResult:
        player_id = int(action.get("player_id", -1))
        if player_id not in self.user_team.roster:
            return self._record(action, phase, False, "player is not on your roster")
        if len(self.user_team.roster) <= ROSTER_MIN:
            return self._record(
                action, phase, False, f"release would drop roster below the {ROSTER_MIN}-player minimum"
            )
        player = self.players[player_id]
        self._remove_from_team(self.user_team, player_id)
        player.team_id = None
        player.contract_years = 0
        player.salary = 0.0
        self.free_agents.append(player_id)
        return self._record(action, phase, True, f"released {player.name}")

    def _trade(self, action: dict[str, Any], phase: str) -> ActionResult:
        partner_id = int(action.get("partner_team_id", -1))
        give = [int(player_id) for player_id in action.get("give_player_ids", [])]
        receive = [int(player_id) for player_id in action.get("receive_player_ids", [])]
        give_picks = [int(year) for year in action.get("give_pick_seasons", [])]
        receive_picks = [int(year) for year in action.get("receive_pick_seasons", [])]
        if partner_id not in self.teams or partner_id == self.user_team_id:
            return self._record(action, phase, False, "invalid trade partner")
        partner = self.teams[partner_id]
        if (not give and not give_picks) or (not receive and not receive_picks):
            return self._record(action, phase, False, "trades must move assets on both sides")
        if len(set(give)) != len(give) or len(set(receive)) != len(receive):
            return self._record(action, phase, False, "trade lists must not contain duplicate player ids")
        if any(player_id not in self.user_team.roster for player_id in give):
            return self._record(action, phase, False, "cannot trade players not on your roster")
        if any(player_id not in partner.roster for player_id in receive):
            return self._record(action, phase, False, "requested player is not on partner roster")
        if not self._has_picks(self.user_team, give_picks):
            return self._record(action, phase, False, "you do not own one or more offered draft picks")
        if not self._has_picks(partner, receive_picks):
            return self._record(action, phase, False, "partner does not own one or more requested draft picks")
        if self.partner_trades.get(partner_id, 0) >= TRADE_LIMIT_PER_PARTNER:
            return self._record(action, phase, False, "partner has no appetite for more trades this season")
        user_after = len(self.user_team.roster) - len(give) + len(receive)
        partner_after = len(partner.roster) - len(receive) + len(give)
        if user_after < ROSTER_MIN and user_after < len(self.user_team.roster):
            return self._record(
                action, phase, False, f"trade would drop your roster below the {ROSTER_MIN}-player minimum"
            )
        if partner_after < ROSTER_MIN and partner_after < len(partner.roster):
            return self._record(
                action, phase, False, f"trade would drop partner roster below the {ROSTER_MIN}-player minimum"
            )
        perceived_give = self._trade_asset_value(give, give_picks, partner_id)
        perceived_receive = self._trade_asset_value(receive, receive_picks, partner_id)
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
            return self._record(action, phase, False, "trade would exceed hard cap buffer")
        if perceived_give < perceived_receive * TRADE_VALUE_THRESHOLD:
            return self._record(action, phase, False, "partner rejects the offer as too light")
        for player_id in give:
            self._remove_from_team(self.user_team, player_id)
            partner.roster.append(player_id)
            self.players[player_id].team_id = partner_id
        for player_id in receive:
            self._remove_from_team(partner, player_id)
            self.user_team.roster.append(player_id)
            self.players[player_id].team_id = self.user_team_id
        self._transfer_picks(self.user_team, partner, give_picks, receive_picks)
        self.partner_trades[partner_id] = self.partner_trades.get(partner_id, 0) + 1
        return self._record(action, phase, True, "trade accepted")

    def _trade_asset_value(self, player_ids: list[int], pick_seasons: list[int], partner_id: int) -> float:
        total = sum(
            self.players[player_id].asset_value * self._partner_valuation_bias(partner_id, player_id)
            for player_id in player_ids
        )
        total += sum(self._pick_asset_value(season) for season in pick_seasons)
        return total

    def _pick_asset_value(self, season_year: int) -> float:
        distance = max(0, season_year - self.season)
        return PICK_ASSET_VALUE * max(0.55, 1.0 - distance * 0.12)

    def _has_picks(self, team: Team, seasons: list[int]) -> bool:
        for season_year in seasons:
            if team.draft_picks.get(season_year, 0) <= 0:
                return False
        return True

    def _transfer_picks(self, user: Team, partner: Team, give: list[int], receive: list[int]) -> None:
        for season_year in give:
            user.draft_picks[season_year] -= 1
            partner.draft_picks[season_year] = partner.draft_picks.get(season_year, 0) + 1
        for season_year in receive:
            partner.draft_picks[season_year] -= 1
            user.draft_picks[season_year] = user.draft_picks.get(season_year, 0) + 1

    def _draft(self, action: dict[str, Any], phase: str) -> ActionResult:
        if phase != "draft":
            return self._record(action, phase, False, "draft actions are only allowed during the draft phase")
        prospect_id = int(action.get("prospect_id", -1))
        if prospect_id not in self.prospects:
            return self._record(action, phase, False, "prospect not in current draft class")
        if self.user_team.draft_picks.get(self.season, 0) <= 0:
            return self._record(action, phase, False, "no current-season draft pick available")
        prospect = self._assign_prospect(self.user_team, prospect_id)
        return self._record(action, phase, True, f"drafted {prospect.name}")

    def _set_lineup(self, action: dict[str, Any], phase: str) -> ActionResult:
        lineup = [int(player_id) for player_id in action.get("player_ids", [])]
        if len(lineup) != LINEUP_SIZE or len(set(lineup)) != LINEUP_SIZE:
            return self._record(action, phase, False, f"lineup must contain {LINEUP_SIZE} unique player ids")
        if any(player_id not in self.user_team.roster for player_id in lineup):
            return self._record(action, phase, False, "lineup includes players not on roster")
        positions = {"F": 0, "D": 0, "G": 0}
        for player_id in lineup:
            positions[self.players[player_id].position] += 1
        if any(positions[key] < LINEUP_MIN_POSITIONS[key] for key in LINEUP_MIN_POSITIONS):
            mins = ", ".join(f"{count} {pos}" for pos, count in LINEUP_MIN_POSITIONS.items())
            return self._record(action, phase, False, f"lineup must include at least {mins}")
        self.user_team.lineup = lineup
        return self._record(action, phase, True, "lineup set")

    def _record(
        self,
        action: dict[str, Any],
        phase: str,
        accepted: bool,
        message: str,
        *,
        team_id: int | None = None,
        data: dict[str, Any] | None = None,
        penalize: bool | None = None,
    ) -> ActionResult:
        if team_id is None:
            team_id = self.user_team_id
        action_type = action.get("type", "")
        should_penalize = (
            penalize
            if penalize is not None
            else (not accepted and team_id == self.user_team_id and action_type not in NON_PENALIZED_TYPES)
        )
        if should_penalize:
            self.illegal_actions += 1
        self.transactions.append(Transaction(self.season, phase, team_id, action, accepted, message))
        return ActionResult(action=action, accepted=accepted, message=message, data=data)

    def _waiver_player_public(self, player_id: int) -> dict[str, Any]:
        player = self.players[player_id].public_dict()
        player["asking_salary"] = self.players[player_id].asking_salary
        return player

    def _standings_public(self) -> list[dict[str, Any]]:
        return [
            {
                "team_id": team.id,
                "team_name": team.name,
                "wins": team.wins,
                "losses": team.losses,
                "championships": team.championships,
                "public_strength": round(self._team_strength(team, apply_injury_noise=False), 1),
            }
            for team in sorted(self.teams.values(), key=lambda item: item.wins, reverse=True)
        ]

    def _free_agent_public(self, player_id: int) -> dict[str, Any]:
        return self._player_detail(self.players[player_id])

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
        age_factor = max(0.05, 1.14 - max(player.age - 23, 0) * 0.05)
        public_skill = player.overall * 0.55 + player.potential * 0.45
        contract_drag = player.salary * 0.55 if player.salary > 0 else 0.0
        return round(max(1.0, (public_skill - 44.0) * age_factor - contract_drag), 2)

    def _partner_valuation_bias(self, partner_id: int, player_id: int) -> float:
        rng = random.Random(f"{self.seed}:{self.season}:valuation:{partner_id}:{player_id}")
        return rng.uniform(0.9, 1.1)

    def _draft_order(self) -> list[int]:
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
            penalize=False,
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
        lineup = sorted(self._effective_lineup(team), key=lambda player: player.effective_overall, reverse=True)
        if not lineup:
            return 20.0
        position_bonus = min(sum(1 for player in lineup if player.position == "G"), 2) * 2.5
        weighted = 0.0
        total_weight = 0.0
        for index, player in enumerate(lineup):
            weight = 1.0 if index < 6 else 0.74 if index < 12 else 0.48
            effective = player.effective_overall
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
            if player.injured_games > 0:
                player.injured_games = max(0, player.injured_games - rng.randint(4, 10))
            player.age += 1
            if player.team_id is None:
                if player.age >= 30:
                    player.overall -= rng.uniform(0.4, 1.9) * (1.0 + max(player.age - 33, 0) * 0.15)
                else:
                    player.overall -= rng.uniform(0.0, 0.6)
                player.overall = min(92.0, max(30.0, player.overall))
                player.potential = min(97.0, max(30.0, player.potential + rng.gauss(0, 1.2)))
                continue
            growth_room = max(0.0, player.true_potential - player.overall)
            if player.age <= 24:
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
        del rng
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

    def _opponent_waiver_claim(self, team: Team, rng: random.Random) -> None:
        if not self.waiver_wire or rng.random() > 0.5:
            return
        player_id = max(self.waiver_wire, key=lambda pid: self.players[pid].overall)
        if self._payroll(team) + self.players[player_id].asking_salary > self.cap + 4.0:
            return
        self.waiver_wire.remove(player_id)
        player = self.players[player_id]
        player.team_id = team.id
        player.salary = player.asking_salary
        player.contract_years = 1
        team.roster.append(player_id)

    def _sign_to_team(self, team: Team, player: Player, rng: random.Random) -> None:
        self.free_agents.remove(player.id)
        team.roster.append(player.id)
        player.team_id = team.id
        player.salary = player.asking_salary
        player.contract_years = rng.randint(1, 3)

    def _opponent_trades(self) -> None:
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
                    penalize=False,
                )
                break

    def _find_mutual_swap(self, team_a: Team, team_b: Team) -> tuple[Player, Player] | None:
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
