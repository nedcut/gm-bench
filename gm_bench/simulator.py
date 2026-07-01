"""League simulation and action validation."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any

from gm_bench.generator import generate_draft_class, generate_league_data
from gm_bench.models import Player, SeasonSummary, Team, Transaction
from gm_bench.scoring import score_team


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

    @classmethod
    def new(cls, seed: int, user_team_id: int = 0, num_teams: int = 12) -> "League":
        teams, players, free_agents = generate_league_data(seed, num_teams=num_teams)
        league = cls(seed=seed, user_team_id=user_team_id, num_teams=num_teams, teams=teams, players=players, free_agents=free_agents)
        league.prospects = generate_draft_class(seed, league.season, num_teams * 5)
        return league

    @property
    def user_team(self) -> Team:
        return self.teams[self.user_team_id]

    def observation(self, phase: str) -> dict[str, Any]:
        return {
            "benchmark": "gm-bench-mvp",
            "seed": self.seed,
            "season": self.season,
            "phase": phase,
            "rules": {
                "salary_cap": self.cap,
                "roster_min": 18,
                "lineup_size": 18,
                "positions": {"F": 12, "D": 4, "G": 2},
                "trade_value_threshold": 0.78,
            },
            "team": self.user_team.public_dict(self.players, self.cap),
            "standings": self._standings_public(),
            "free_agents": [self._free_agent_public(player_id) for player_id in self.free_agents],
            "draft_class": [player.public_dict() for player in self.prospects.values()],
            "trade_market": self._trade_market_public(),
            "history": [summary.__dict__ for summary in self.summaries[-5:]],
            "recent_transactions": [transaction.__dict__ for transaction in self.transactions[-12:]],
        }

    def apply_actions(self, actions: list[dict[str, Any]], phase: str) -> None:
        if not isinstance(actions, list):
            self._record({}, phase, False, "agent response must be a list of actions")
            return
        for action in actions[:24]:
            if not isinstance(action, dict):
                self._record({}, phase, False, "action must be an object")
                continue
            action_type = action.get("type", "noop")
            if action_type == "noop":
                self._record(action, phase, True, "no-op")
            elif action_type == "sign_free_agent":
                self._safe_apply(self._sign_free_agent, action, phase)
            elif action_type == "release":
                self._safe_apply(self._release, action, phase)
            elif action_type == "trade":
                self._safe_apply(self._trade, action, phase)
            elif action_type == "draft":
                self._safe_apply(self._draft, action, phase)
            elif action_type == "set_lineup":
                self._safe_apply(self._set_lineup, action, phase)
            else:
                self._record(action, phase, False, f"unknown action type {action_type!r}")

    def _safe_apply(self, handler: Any, action: dict[str, Any], phase: str) -> None:
        try:
            handler(action, phase)
        except (TypeError, ValueError):
            self._record(action, phase, False, "action has invalid or missing argument values")

    def run_autopilot_opponents(self) -> None:
        rng = self._rng("opponents")
        for team in self.teams.values():
            if team.id == self.user_team_id:
                continue
            self._trim_expiring_contracts(team, rng)
            self._opponent_signings(team, rng)
            self._opponent_lineup(team)

    def simulate_season(self) -> SeasonSummary:
        rng = self._rng("season")
        ratings = {team.id: self._team_strength(team, apply_injury_noise=True, rng=rng) for team in self.teams.values()}
        for team in self.teams.values():
            team.wins = 0
            team.losses = 0
            team.playoff_rounds = 0

        games_per_pair = 3
        for home in self.teams.values():
            for away in self.teams.values():
                if home.id >= away.id:
                    continue
                for _ in range(games_per_pair):
                    probability = 1.0 / (1.0 + math.exp(-(ratings[home.id] - ratings[away.id]) / 7.5))
                    if rng.random() < probability:
                        home.wins += 1
                        away.losses += 1
                    else:
                        away.wins += 1
                        home.losses += 1

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
        self.prospects = generate_draft_class(self.seed, self.season, self.num_teams * 5)
        return summary

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
        player = self.players[player_id]
        minimum = player.asking_salary * 0.9
        if salary < minimum:
            self._record(action, phase, False, f"salary below player's market ask of {minimum:.2f}")
            return
        if self._payroll(self.user_team) + salary > self.cap + 8.0:
            self._record(action, phase, False, "signing would exceed hard cap buffer")
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
        player = self.players[player_id]
        self.user_team.roster.remove(player_id)
        player.team_id = None
        player.contract_years = 0
        player.salary = 0.0
        self.free_agents.append(player_id)
        self._record(action, phase, True, f"released {player.name}")

    def _trade(self, action: dict[str, Any], phase: str) -> None:
        partner_id = int(action.get("partner_team_id", -1))
        give = [int(player_id) for player_id in action.get("give_player_ids", [])]
        receive = [int(player_id) for player_id in action.get("receive_player_ids", [])]
        if partner_id not in self.teams or partner_id == self.user_team_id:
            self._record(action, phase, False, "invalid trade partner")
            return
        partner = self.teams[partner_id]
        if not give or not receive:
            self._record(action, phase, False, "trades must include players from both teams")
            return
        if any(player_id not in self.user_team.roster for player_id in give):
            self._record(action, phase, False, "cannot trade players not on your roster")
            return
        if any(player_id not in partner.roster for player_id in receive):
            self._record(action, phase, False, "requested player is not on partner roster")
            return
        give_value = sum(self.players[player_id].asset_value for player_id in give)
        receive_value = sum(self.players[player_id].asset_value for player_id in receive)
        partner_payroll_after = self._payroll(partner) - sum(self.players[player_id].salary for player_id in receive) + sum(
            self.players[player_id].salary for player_id in give
        )
        user_payroll_after = self._payroll(self.user_team) - sum(self.players[player_id].salary for player_id in give) + sum(
            self.players[player_id].salary for player_id in receive
        )
        if partner_payroll_after > self.cap + 8.0 or user_payroll_after > self.cap + 8.0:
            self._record(action, phase, False, "trade would exceed hard cap buffer")
            return
        if give_value < receive_value * 0.78:
            self._record(action, phase, False, "partner rejects low-value offer")
            return
        for player_id in give:
            self.user_team.roster.remove(player_id)
            partner.roster.append(player_id)
            self.players[player_id].team_id = partner_id
        for player_id in receive:
            partner.roster.remove(player_id)
            self.user_team.roster.append(player_id)
            self.players[player_id].team_id = self.user_team_id
        self._record(action, phase, True, "trade accepted")

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
        prospect = self.prospects.pop(prospect_id)
        prospect.team_id = self.user_team_id
        prospect.salary = 0.95
        prospect.contract_years = 3
        prospect.drafted_round = 1
        self.players[prospect.id] = prospect
        self.user_team.roster.append(prospect.id)
        self.user_team.draft_picks[self.season] -= 1
        self._record(action, phase, True, f"drafted {prospect.name}")

    def _set_lineup(self, action: dict[str, Any], phase: str) -> None:
        lineup = [int(player_id) for player_id in action.get("player_ids", [])]
        if len(lineup) != 18 or len(set(lineup)) != 18:
            self._record(action, phase, False, "lineup must contain 18 unique player ids")
            return
        if any(player_id not in self.user_team.roster for player_id in lineup):
            self._record(action, phase, False, "lineup includes players not on roster")
            return
        positions = {"F": 0, "D": 0, "G": 0}
        for player_id in lineup:
            positions[self.players[player_id].position] += 1
        if positions["G"] < 1 or positions["D"] < 4 or positions["F"] < 10:
            self._record(action, phase, False, "lineup must include at least 10 F, 4 D, and 1 G")
            return
        roster = self.user_team.roster
        self.user_team.roster = lineup + [player_id for player_id in roster if player_id not in set(lineup)]
        self._record(action, phase, True, "lineup set")

    def _record(self, action: dict[str, Any], phase: str, accepted: bool, message: str) -> None:
        if not accepted:
            self.illegal_actions += 1
        self.transactions.append(Transaction(self.season, phase, self.user_team_id, action, accepted, message))

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

    def _team_strength(self, team: Team, apply_injury_noise: bool, rng: random.Random | None = None) -> float:
        lineup = sorted((self.players[player_id] for player_id in team.roster), key=lambda player: player.overall, reverse=True)[:18]
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
        for player in list(self.players.values()):
            if player.team_id is None:
                continue
            player.age += 1
            growth_room = max(0.0, player.true_potential - player.overall)
            if player.age <= 24:
                player.overall += rng.uniform(0.2, 2.8) * min(1.0, growth_room / 10.0)
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
                    team.roster.remove(player.id)
                player.team_id = None
                player.salary = 0.0
                player.contract_years = 0
                self.free_agents.append(player.id)

    def _trim_expiring_contracts(self, team: Team, rng: random.Random) -> None:
        if len(team.roster) <= 23:
            return
        excess = sorted((self.players[player_id] for player_id in team.roster), key=lambda player: player.asset_value)
        for player in excess[: max(0, len(team.roster) - 23)]:
            team.roster.remove(player.id)
            player.team_id = None
            player.salary = 0.0
            player.contract_years = 0
            self.free_agents.append(player.id)

    def _opponent_signings(self, team: Team, rng: random.Random) -> None:
        needed = max(0, 21 - len(team.roster))
        candidates = sorted((self.players[player_id] for player_id in self.free_agents), key=lambda player: player.overall, reverse=True)
        for player in candidates[: needed * 2]:
            if needed <= 0:
                break
            ask = player.asking_salary
            if self._payroll(team) + ask <= self.cap + 4.0:
                self.free_agents.remove(player.id)
                team.roster.append(player.id)
                player.team_id = team.id
                player.salary = ask
                player.contract_years = rng.randint(1, 3)
                needed -= 1

    def _opponent_lineup(self, team: Team) -> None:
        team.roster = [player.id for player in sorted((self.players[player_id] for player_id in team.roster), key=lambda player: player.overall, reverse=True)]

    def _payroll(self, team: Team) -> float:
        return sum(self.players[player_id].salary for player_id in team.roster)

    def _rng(self, namespace: str) -> random.Random:
        self.rng_state_offset += 1
        return random.Random(f"{self.seed}:{self.season}:{self.rng_state_offset}:{namespace}")
