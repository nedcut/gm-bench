"""Seeded fictional league generation."""

from __future__ import annotations

import random

from gm_bench.models import Player, Team

FIRST_NAMES = [
    "Alex",
    "Ben",
    "Cal",
    "Drew",
    "Eli",
    "Finn",
    "Gabe",
    "Hugo",
    "Ivan",
    "Jules",
    "Kai",
    "Leo",
    "Milo",
    "Nico",
    "Owen",
    "Pax",
    "Quin",
    "Rafi",
    "Theo",
    "Vik",
]

LAST_NAMES = [
    "Anders",
    "Berg",
    "Chen",
    "Diaz",
    "Evans",
    "Frost",
    "Grant",
    "Hayes",
    "Ivers",
    "Jensen",
    "Keller",
    "Lund",
    "Mason",
    "Novak",
    "Olsen",
    "Price",
    "Quill",
    "Reed",
    "Stone",
    "Vale",
]

TEAM_NAMES = [
    "Anchorage Auroras",
    "Austin Jackals",
    "Boston Harbors",
    "Calgary Peaks",
    "Chicago Steel",
    "Denver Comets",
    "Halifax Schooners",
    "Miami Palms",
    "Montreal Saints",
    "Nashville Sound",
    "Portland Pines",
    "Seattle Surge",
    "Toronto Towers",
    "Vancouver Orcas",
    "Winnipeg North",
    "Quebec Citadels",
]


def _name(rng: random.Random, used: set[str]) -> str:
    while True:
        candidate = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
        if candidate not in used:
            used.add(candidate)
            return candidate


def generate_league_data(seed: int, num_teams: int = 12, roster_size: int = 23) -> tuple[dict[int, Team], dict[int, Player], list[int]]:
    rng = random.Random(seed)
    teams: dict[int, Team] = {}
    players: dict[int, Player] = {}
    free_agents: list[int] = []
    used_names: set[str] = set()
    next_player_id = 1

    for team_id, name in enumerate(TEAM_NAMES[:num_teams]):
        teams[team_id] = Team(
            id=team_id,
            name=name,
            market=rng.uniform(0.75, 1.25),
            patience=rng.uniform(0.75, 1.25),
            draft_picks={year: 1 for year in range(1, 8)},
        )

    for team in teams.values():
        for slot in range(roster_size):
            position = "G" if slot < 2 else "D" if slot < 8 else "F"
            age = int(min(38, max(18, rng.gauss(26.5, 4.6))))
            true_potential = min(92.0, max(42.0, rng.gauss(62.0, 9.0)))
            development_gap = max(0.0, true_potential - 50.0) * rng.uniform(0.18, 0.58)
            aging_penalty = max(0.0, age - 28) * rng.uniform(0.8, 1.8)
            overall = min(88.0, max(42.0, true_potential - development_gap - aging_penalty + rng.gauss(0, 3.3)))
            public_potential = min(94.0, max(38.0, true_potential + rng.gauss(0, 5.5)))
            salary = round(max(0.75, (overall - 43.0) * 0.22 * rng.uniform(0.75, 1.25)), 2)
            contract_years = rng.randint(1, 5)
            player = Player(
                id=next_player_id,
                name=_name(rng, used_names),
                position=position,
                age=age,
                overall=overall,
                potential=public_potential,
                true_potential=true_potential,
                salary=salary,
                contract_years=contract_years,
                team_id=team.id,
                injury_risk=rng.uniform(0.02, 0.16) + max(age - 31, 0) * 0.012,
            )
            players[player.id] = player
            team.roster.append(player.id)
            next_player_id += 1

    for slot in range(num_teams * 3):
        position = "G" if slot % 12 == 0 else "D" if slot % 4 == 0 else "F"
        age = int(min(37, max(19, rng.gauss(28.0, 4.8))))
        true_potential = min(86.0, max(40.0, rng.gauss(56.5, 7.0)))
        overall = min(82.0, max(39.0, true_potential - max(age - 29, 0) * rng.uniform(1.0, 2.0) + rng.gauss(0, 4.0)))
        player = Player(
            id=next_player_id,
            name=_name(rng, used_names),
            position=position,
            age=age,
            overall=overall,
            potential=min(90.0, max(35.0, true_potential + rng.gauss(0, 6.5))),
            true_potential=true_potential,
            salary=0.0,
            contract_years=0,
            team_id=None,
            injury_risk=rng.uniform(0.03, 0.19),
        )
        players[player.id] = player
        free_agents.append(player.id)
        next_player_id += 1

    return teams, players, free_agents


def generate_draft_class(seed: int, season: int, count: int) -> dict[int, Player]:
    rng = random.Random(seed * 1009 + season * 9176)
    used_names: set[str] = set()
    prospects: dict[int, Player] = {}
    base_id = 1_000_000 + season * 10_000
    for index in range(count):
        position = "G" if index % 13 == 0 else "D" if index % 4 == 0 else "F"
        true_potential = min(95.0, max(38.0, rng.gauss(63.0, 11.0)))
        public_potential = min(97.0, max(36.0, true_potential + rng.gauss(0, 8.0)))
        overall = min(74.0, max(35.0, true_potential - rng.uniform(9.0, 22.0) + rng.gauss(0, 3.0)))
        prospect = Player(
            id=base_id + index,
            name=_name(rng, used_names),
            position=position,
            age=rng.choice([18, 18, 19, 20]),
            overall=overall,
            potential=public_potential,
            true_potential=true_potential,
            salary=0.95,
            contract_years=3,
            team_id=None,
            injury_risk=rng.uniform(0.02, 0.12),
        )
        prospects[prospect.id] = prospect
    return prospects

