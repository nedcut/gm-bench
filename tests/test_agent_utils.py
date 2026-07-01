from __future__ import annotations

from gm_bench.agent_utils import LINEUP_MIN_POSITIONS, LINEUP_SIZE, position_aware_lineup, public_asset_value


def test_public_asset_value_prefers_young_high_potential_players() -> None:
    young = {"overall": 70, "potential": 85, "age": 22, "asking_salary": 3.0}
    old = {"overall": 70, "potential": 70, "age": 34, "asking_salary": 3.0}
    assert public_asset_value(young) > public_asset_value(old)


def test_position_aware_lineup_respects_minimums() -> None:
    roster = []
    player_id = 1
    for position, count in LINEUP_MIN_POSITIONS.items():
        for _ in range(count + 2):
            roster.append(
                {
                    "id": player_id,
                    "position": position,
                    "overall": 60 + player_id,
                    "potential": 70,
                    "age": 24,
                }
            )
            player_id += 1
    lineup = position_aware_lineup(roster)
    assert len(lineup) == LINEUP_SIZE
    positions = {position: 0 for position in LINEUP_MIN_POSITIONS}
    for player in roster:
        if player["id"] in lineup:
            positions[player["position"]] += 1
    for position, minimum in LINEUP_MIN_POSITIONS.items():
        assert positions[position] >= minimum
