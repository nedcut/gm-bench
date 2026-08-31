"""The observation view model adapters receive.

The prompt scaffold in ``examples/gm_agent_common.py`` does not hand a model
the observation the simulator emits: it sorts, truncates, renames, and drops
fields before serializing. That compaction lives here, in the package, for two
reasons. It is imported by ``examples/gm_agent_common.py`` so adapters keep
using it verbatim, and it is imported by the ``scaffold-view`` baseline in
``gm_bench.agents`` so a registered agent can be measured on exactly the view
models see. A second copy would make the measured gap a statement about a
scaffold nobody runs the moment either copy changed.
"""

from __future__ import annotations

import os
from typing import Any

from gm_bench.agent_utils import position_aware_lineup, public_asset_value


def model_adapter_observation(observation: dict[str, Any]) -> dict[str, Any]:
    """Return the raw adapter payload with private run identity removed.

    The runner retains the seed for deterministic simulation, paired analysis,
    replay, and artifacts. External adapters do not need it to choose legal
    actions, however, and exposing it would let adapter code reconstruct hidden
    simulator state from the public generator. Use a shallow copy so removing
    the transport-only field never mutates the runner's canonical observation.
    """
    return {key: value for key, value in observation.items() if key != "seed"}


def compact_observation(observation: dict[str, Any], profile: str | None = None) -> dict[str, Any]:
    """Compact an observation to the view a model adapter receives.

    ``profile`` selects the truncation limits. Adapters leave it None and
    inherit ``GM_AGENT_PROFILE`` from the subprocess environment the harness
    pins. In-process callers (the ``scaffold-view`` baseline) must pass it
    explicitly: they run in the parent process, where that variable reflects the
    operator's shell rather than the lane, so inheriting it would let an ambient
    value silently decide which view was measured.
    """
    if profile is None:
        profile = os.environ.get("GM_AGENT_PROFILE", "compact")
    if profile == "tiny":
        roster_limit = 18
        free_agent_limit = 6
        draft_limit = 6
        trade_limit = 0
    else:
        roster_limit = 24
        free_agent_limit = 16
        draft_limit = 16
        trade_limit = 12
    team = observation.get("team") or {}
    roster = team.get("roster") or []
    roster_sorted = sorted(roster, key=lambda player: player["overall"], reverse=True) if roster else []
    free_agents = observation.get("free_agents") or []
    if not free_agents and observation.get("free_agents_summary"):
        free_agents = [{"id": pid} for pid in observation["free_agents_summary"].get("top_ids", [])]
    free_agents_sorted = sorted(
        [player for player in free_agents if isinstance(player, dict) and "overall" in player],
        key=public_asset_value,
        reverse=True,
    )
    draft_class = observation.get("draft_class") or []
    if not draft_class and observation.get("draft_class_summary"):
        draft_class = [{"id": pid} for pid in observation["draft_class_summary"].get("top_ids", [])]
    draft_sorted = sorted(
        [player for player in draft_class if isinstance(player, dict) and "overall" in player],
        key=public_asset_value,
        reverse=True,
    )
    trade_market = observation.get("trade_market") or []
    payload: dict[str, Any] = {
        "season": observation.get("season"),
        "phase": observation.get("phase"),
        "observation_tier": observation.get("observation_tier", "full"),
        "interaction_round": observation.get("interaction_round", 0),
        "rules": observation.get("rules"),
        "team": {
            "id": team.get("id"),
            "name": team.get("name"),
            "wins": team.get("wins"),
            "losses": team.get("losses"),
            "payroll": team.get("payroll"),
            "cap_room": team.get("cap_room"),
            "dead_cap": team.get("dead_cap", {}),
            "championships": team.get("championships"),
            "draft_picks": team.get("draft_picks"),
            "picks": team.get("picks"),
            "top_roster": roster_sorted[:roster_limit] if roster_sorted else team.get("roster_summary"),
        },
        "free_agents": free_agents_sorted[:free_agent_limit],
        "draft_class": draft_sorted[:draft_limit],
        "draft_order": observation.get("draft_order", []),
        "draft_lottery": observation.get("draft_lottery"),
        "trade_market": trade_market[:trade_limit],
        "incoming_offers": observation.get("incoming_offers", [])[:3],
        "scout_reports": observation.get("scout_reports", {}),
        "waiver_wire_summary": observation.get("waiver_wire_summary"),
        "available_actions": observation.get("available_actions", []),
        "action_results": observation.get("action_results"),
        "history": observation.get("history"),
        "memo": observation.get("memo", ""),
        "hint": observation.get("hint"),
    }
    if observation.get("free_agents_summary"):
        payload["free_agents_summary"] = observation["free_agents_summary"]
    if observation.get("draft_class_summary"):
        payload["draft_class_summary"] = observation["draft_class_summary"]
    if observation.get("trade_market_summary"):
        payload["trade_market_summary"] = observation["trade_market_summary"]
    return payload


def scaffold_fallback_lineup(observation: dict[str, Any]) -> list[int]:
    """The legal lineup the prompt hands a model for free.

    Computed from the untruncated roster, so it is available even when the
    compact payload no longer carries enough players to build one.
    """
    roster = (observation.get("team") or {}).get("roster") or []
    return position_aware_lineup(roster) if roster else []


def scaffold_view_observation(observation: dict[str, Any], profile: str | None = None) -> dict[str, Any]:
    """Re-shape the model payload so a scripted policy can read it.

    Only naming is undone: ``team.top_roster`` goes back to ``team.roster``,
    and the candidate lists the compactor always emits are guaranteed present.
    Every truncation stays in place. The payload is deliberately *not* round
    tripped through JSON first -- that would turn ``team.draft_picks`` season
    keys into strings and make scripted ``.get(season)`` lookups miss, which is
    a Python typing artifact rather than information a model is denied.
    """
    payload = compact_observation(observation, profile)
    team = dict(payload["team"])
    roster = team.pop("top_roster", None)
    team["roster"] = list(roster) if isinstance(roster, list) else []
    payload["team"] = team
    for key in ("free_agents", "draft_class", "trade_market", "incoming_offers"):
        if not isinstance(payload.get(key), list):
            payload[key] = []
    payload["scaffold_fallback_lineup"] = scaffold_fallback_lineup(observation)
    return payload
