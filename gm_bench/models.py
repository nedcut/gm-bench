"""Core data structures for GM-Bench."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Position = Literal["F", "D", "G"]
ActionType = Literal["sign_free_agent", "release", "trade", "draft", "set_lineup", "noop"]


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
    morale: float = 0.0
    drafted_round: int | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
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
        return max(0.0, (self.overall * 0.55 + self.potential * 0.45 - 45.0) * age_factor * contract_factor)


@dataclass
class Team:
    id: int
    name: str
    market: float
    patience: float
    roster: list[int] = field(default_factory=list)
    wins: int = 0
    losses: int = 0
    championships: int = 0
    playoff_rounds: int = 0
    draft_picks: dict[int, int] = field(default_factory=dict)

    def public_dict(self, players: dict[int, Player], cap: float) -> dict[str, Any]:
        payroll = sum(players[player_id].salary for player_id in self.roster)
        return {
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
            "roster": [players[player_id].public_dict() for player_id in self.roster],
        }


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

