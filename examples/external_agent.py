"""Tiny external agent example for the GM-Bench JSON protocol."""

from __future__ import annotations

import json
import sys


def main() -> None:
    observation = json.load(sys.stdin)
    actions = []

    free_agents = sorted(
        observation["free_agents"],
        key=lambda player: (player["overall"] / max(player["asking_salary"], 0.1)),
        reverse=True,
    )
    cap_room = observation["team"]["cap_room"]
    for player in free_agents[:3]:
        if player["asking_salary"] <= cap_room and player["age"] <= 31:
            actions.append(
                {
                    "type": "sign_free_agent",
                    "player_id": player["id"],
                    "years": 1,
                    "salary": player["asking_salary"],
                }
            )
            cap_room -= player["asking_salary"]

    lineup = position_aware_lineup(observation["team"]["roster"])
    if lineup:
        actions.append({"type": "set_lineup", "player_ids": lineup})
    print(json.dumps(actions))


def position_aware_lineup(roster):
    selected = []
    selected_ids = set()
    for position, count in {"F": 10, "D": 4, "G": 1}.items():
        candidates = sorted((player for player in roster if player["position"] == position), key=lambda player: player["overall"], reverse=True)
        if len(candidates) < count:
            return []
        for player in candidates[:count]:
            selected.append(player)
            selected_ids.add(player["id"])
    remaining = sorted((player for player in roster if player["id"] not in selected_ids), key=lambda player: player["overall"], reverse=True)
    selected.extend(remaining[: 18 - len(selected)])
    return [player["id"] for player in selected]


if __name__ == "__main__":
    main()
