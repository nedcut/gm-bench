"""GM-Bench protocol constants and interaction types."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Literal

BENCHMARK_VERSION = "gm-bench-v2"
PHASES = ("preseason", "midseason", "trade_deadline", "draft")
ObservationTier = Literal["summary", "full"]

CORE_ACTION_TYPES = frozenset(
    {
        "sign_free_agent",
        "release",
        "trade",
        "draft",
        "set_lineup",
        "memo",
        "noop",
        "claim_waiver",
    }
)
QUERY_ACTION_TYPES = frozenset({"inspect_team", "inspect_player", "list_free_agents", "scout"})
NEGOTIATION_ACTION_TYPES = frozenset({"accept_trade_offer", "reject_trade_offer", "counter_trade_offer"})
CONTROL_ACTION_TYPES = frozenset({"end_turn"})
ALL_ACTION_TYPES = CORE_ACTION_TYPES | QUERY_ACTION_TYPES | NEGOTIATION_ACTION_TYPES | CONTROL_ACTION_TYPES

# Informational actions never count as illegal when rejected for bad args — only malformed.
NON_PENALIZED_TYPES = QUERY_ACTION_TYPES | frozenset({"noop", "memo", "end_turn"})

SCOUTS_PER_SEASON = 3
MAX_INTERACTION_ROUNDS = 5
PARTIAL_SEASON_FRACTION = 0.35
INJURY_GAMES_DEFAULT = 8


@dataclass
class ActionResult:
    action: dict[str, Any]
    accepted: bool
    message: str
    data: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "action": self.action,
            "accepted": self.accepted,
            "message": self.message,
        }
        if self.data is not None:
            payload["data"] = self.data
        return payload


@dataclass
class IncomingTradeOffer:
    offer_id: str
    from_team_id: int
    from_team_name: str
    give_player_ids: list[int] = field(default_factory=list)
    receive_player_ids: list[int] = field(default_factory=list)
    give_pick_seasons: list[int] = field(default_factory=list)
    receive_pick_seasons: list[int] = field(default_factory=list)

    def public_dict(self, players: dict[int, Any]) -> dict[str, Any]:
        return {
            "offer_id": self.offer_id,
            "from_team_id": self.from_team_id,
            "from_team_name": self.from_team_name,
            "they_give": [players[pid].public_dict() for pid in self.give_player_ids if pid in players],
            "they_want": [players[pid].public_dict() for pid in self.receive_player_ids if pid in players],
            "they_give_pick_seasons": list(self.give_pick_seasons),
            "they_want_pick_seasons": list(self.receive_pick_seasons),
        }


@dataclass
class EpisodeConfig:
    observation_tier: ObservationTier = "full"
    max_interaction_rounds: int = MAX_INTERACTION_ROUNDS
    persistent_session: bool = False
    strict: bool = False
    include_midseason: bool = True
    builtin_full_observation: bool = True

    def baseline_cache_fingerprint(self) -> str:
        """Fingerprint the fields that change a played-out episode.

        Two runs whose configs differ here produce different episodes, so their
        cached baseline scores must not collide. ``persistent_session`` is
        excluded: it only selects the candidate's transport and never alters an
        in-process scripted baseline. The default config returns ``""`` so its
        keys stay identical to the historical cache and keep hitting.
        """

        default = EpisodeConfig()
        relevant = (
            "observation_tier",
            "max_interaction_rounds",
            "strict",
            "include_midseason",
            "builtin_full_observation",
        )
        if all(getattr(self, name) == getattr(default, name) for name in relevant):
            return ""
        payload = json.dumps({name: getattr(self, name) for name in relevant}, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
