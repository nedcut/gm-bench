"""Core data structures for GM-Bench."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Position = Literal["F", "D", "G"]
ActionType = Literal[
    "sign_free_agent",
    "release",
    "trade",
    "draft",
    "set_lineup",
    "memo",
    "noop",
    "inspect_team",
    "inspect_player",
    "list_free_agents",
    "scout",
    "accept_trade_offer",
    "reject_trade_offer",
    "counter_trade_offer",
    "claim_waiver",
    "end_turn",
]

LINEUP_SIZE = 18
LINEUP_MIN_POSITIONS: dict[str, int] = {"F": 10, "D": 4, "G": 1}
ROSTER_MIN = 18


@dataclass
class Player:
    id: int
    name: str
    position: Position
    age: int
    overall: float
    potential: float
    true_potential: float
    salary: float
    contract_years: int
    team_id: int | None
    injury_risk: float
    morale: float = 50.0
    drafted_round: int | None = None
    injured_games: int = 0

    def public_dict(self, *, include_injury_status: bool = True) -> dict[str, Any]:
        payload = {
            "id": self.id,
            "name": self.name,
            "position": self.position,
            "age": self.age,
            "overall": round(self.overall, 1),
            "potential": round(self.potential, 1),
            "salary": round(self.salary, 2),
            "contract_years": self.contract_years,
            "injury_risk": round(self.injury_risk, 3),
            "morale": round(self.morale, 2),
        }
        if include_injury_status and self.injured_games > 0:
            payload["injured_games_remaining"] = self.injured_games
        return payload

    @property
    def asking_salary(self) -> float:
        age_penalty = max(0.72, 1.0 - max(self.age - 30, 0) * 0.035)
        return round(max(0.7, (self.overall - 44.0) * 0.22 * age_penalty), 2)

    @property
    def asset_value(self) -> float:
        age_factor = max(0.05, 1.18 - max(self.age - 23, 0) * 0.055)
        contract_factor = 1.0
        if self.contract_years > 0:
            surplus = max(-10.0, self.overall - 52.0 - self.salary * 2.5)
            contract_factor += surplus * 0.018
        morale_factor = 0.92 + min(max(self.morale, 0.0), 100.0) / 100.0 * 0.08
        return max(0.0, (self.overall * 0.55 + self.potential * 0.45 - 45.0) * age_factor * contract_factor * morale_factor)

    @property
    def effective_overall(self) -> float:
        injury_penalty = min(18.0, self.injured_games * 2.25) if self.injured_games > 0 else 0.0
        morale_penalty = max(0.0, (45.0 - self.morale) * 0.06)
        return max(30.0, self.overall - injury_penalty - morale_penalty)


@dataclass
class Team:
    id: int
    name: str
    market: float
    patience: float
    roster: list[int] = field(default_factory=list)
    lineup: list[int] = field(default_factory=list)
    wins: int = 0
    losses: int = 0
    championships: int = 0
    playoff_rounds: int = 0
    draft_picks: dict[int, int] = field(default_factory=dict)

    def public_dict(self, players: dict[int, Player], cap: float, *, full_roster: bool = True) -> dict[str, Any]:
        payroll = sum(players[player_id].salary for player_id in self.roster)
        roster_players = [players[player_id] for player_id in self.roster]
        payload: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "market": round(self.market, 2),
            "patience": round(self.patience, 2),
            "wins": self.wins,
            "losses": self.losses,
            "championships": self.championships,
            "playoff_rounds": self.playoff_rounds,
            "payroll": round(payroll, 2),
            "cap_room": round(cap - payroll, 2),
            "draft_picks": dict(sorted(self.draft_picks.items())),
            "lineup": list(self.lineup),
        }
        if full_roster:
            payload["roster"] = [players[player_id].public_dict() for player_id in self.roster]
        else:
            top = sorted(roster_players, key=lambda player: player.overall, reverse=True)[:8]
            payload["roster_summary"] = {
                "count": len(self.roster),
                "avg_overall": round(sum(player.overall for player in roster_players) / max(len(roster_players), 1), 2),
                "top_player_ids": [player.id for player in top],
            }
        return payload


@dataclass
class Transaction:
    season: int
    phase: str
    team_id: int
    action: dict[str, Any]
    accepted: bool
    message: str


@dataclass
class SeasonSummary:
    season: int
    wins: int
    losses: int
    payroll: float
    cap_room: float
    champion_team_id: int
    playoff_rounds: int
    score_after_season: float
