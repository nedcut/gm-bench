"""Shared helpers for built-in and external GM agents."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from gm_bench.models import LINEUP_MIN_POSITIONS, LINEUP_SIZE


def public_asset_value(player: dict[str, Any]) -> float:
    age_factor = max(0.05, 1.16 - max(player["age"] - 23, 0) * 0.052)
    salary = player.get("asking_salary", player.get("salary", 0.0))
    return (player["overall"] * 0.5 + player["potential"] * 0.5 - 43.0) * age_factor - salary * 0.7


def position_aware_lineup(
    roster: list[dict[str, Any]],
    score_fn: Callable[[dict[str, Any]], float] | None = None,
) -> list[int]:
    if len(roster) < LINEUP_SIZE:
        return []
    rank = score_fn or (lambda player: player["overall"])
    selected: list[dict[str, Any]] = []
    selected_ids: set[int] = set()
    for position, count in LINEUP_MIN_POSITIONS.items():
        candidates = sorted(
            (player for player in roster if player["position"] == position),
            key=rank,
            reverse=True,
        )
        if len(candidates) < count:
            return []
        for player in candidates[:count]:
            selected.append(player)
            selected_ids.add(player["id"])
    remaining = sorted(
        (player for player in roster if player["id"] not in selected_ids),
        key=rank,
        reverse=True,
    )
    selected.extend(remaining[: LINEUP_SIZE - len(selected)])
    return [player["id"] for player in selected[:LINEUP_SIZE]]
