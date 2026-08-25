"""Decision-level recording for illustrative content.

The published benchmark artifacts keep aggregates only: an episode row stops at
``final_score`` and usage. That is enough to compare policies and not enough to
show anyone *what a policy actually did*, so nothing on disk can answer "which
call cost this model the season".

This module records that missing layer. For each decision window it captures the
observation the agent saw, the actions it returned, and the immediate change in
``score_components`` those actions caused -- alongside the same three things for
every *ghost*: another policy handed the same decision on a throwaway copy of
the league, whose turn is then discarded.

Recording lives entirely outside the frozen contract sources
-------------------------------------------------------------
``contract_fingerprint()`` is a byte-exact hash of ``gm_bench/runner.py``,
``simulator.py``, ``scoring.py`` and friends. Editing any of them -- even to add
a no-op hook, even in a docstring -- invalidates every result published under
the current contract. So nothing here touches them.

Instead this module mirrors only ``run_episode``'s outer season/phase loop and
calls the real ``run_decision_point`` for the subject *and* for every ghost.
The interaction-round logic, protocol accounting and telemetry are therefore
the genuine article rather than a copy that can drift.
``tests/test_recorder.py`` pins the mirrored loop to ``run_episode`` by asserting
the two produce identical final league state.

Immediate deltas are the point
------------------------------
A decision graded by the resulting *state* -- cap room, asset value, roster
depth, current strength -- is deterministic. A decision graded by the rest of
the season is not: within-seed score noise runs to an SD of 53 points and
survives pairing, which is larger than the spread between most published models.
See ``docs/run_logs/gap-decomposition-and-panel-power-2026-07-26.md``.

Nothing here feeds a score, a leaderboard row, or a published artifact.
"""

from __future__ import annotations

import copy
import dataclasses
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from gm_bench.agents import AGENTS, Agent
from gm_bench.protocol import PHASES, EpisodeConfig
from gm_bench.runner import _observation_tier_for_agent, run_decision_point
from gm_bench.scoring import SCORE_COMPONENT_METRICS, score_components
from gm_bench.simulator import League

RECORD_SCHEMA = "gm-bench-decision-record-v1"
# Ordered best-first. Several ghosts on one state give a puzzle real distractors:
# every option is a policy that genuinely wanted that move, from the same
# information, rather than a plausible-looking invention.
DEFAULT_GHOSTS = ("pick-trader", "value", "win-now", "conservative")

# Metrics a single decision window can actually move. Wins, playoff rounds and
# championships only change when a season is simulated, so a decision-level
# delta on them is always zero and would just be noise in the record.
IMMEDIATE_METRICS = tuple(
    name for name in SCORE_COMPONENT_METRICS if name not in {"recent_wins", "playoff_rounds", "championships"}
)


def component_delta(before: dict[str, float], after: dict[str, float]) -> dict[str, float]:
    """Immediate change in the metrics a decision window can move.

    Returns both the raw metric deltas and the weighted ``*_contribution``
    deltas. The contributions are what a score-unit ranking needs; the raws are
    what a human-readable card needs ("gave up 12.4 of asset value").
    ``cap_room`` is clamped inside its contribution, so the two are not a fixed
    ratio and both are kept.
    """
    delta: dict[str, float] = {}
    for name in IMMEDIATE_METRICS:
        delta[name] = round(after[name] - before[name], 6)
        key = f"{name}_contribution"
        delta[key] = round(after[key] - before[key], 6)
    return delta


class DecisionRecorder:
    """Append-only JSONL sink for decision windows."""

    def __init__(
        self,
        path: str | Path,
        *,
        agent_name: str,
        ghost_agents: str | Sequence[str] | None = DEFAULT_GHOSTS,
        include_observation: bool = True,
    ) -> None:
        if ghost_agents is None:
            ghosts: tuple[str, ...] = ()
        elif isinstance(ghost_agents, str):
            ghosts = (ghost_agents,)
        else:
            ghosts = tuple(ghost_agents)
        unknown = [name for name in ghosts if name not in AGENTS]
        if unknown:
            raise ValueError(f"unknown ghost agents {unknown}; expected names from {sorted(AGENTS)}")
        self.path = Path(path)
        self.agent_name = agent_name
        self.ghost_agents = ghosts
        self.include_observation = include_observation
        self.seed: int | None = None
        self.decision_index = 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("w", encoding="utf-8")

    def start_episode(self, seed: int) -> None:
        self.seed = seed
        self.decision_index = 0

    def write(self, record: dict[str, Any]) -> None:
        self.decision_index += 1
        payload = {"schema": RECORD_SCHEMA, "seed": self.seed, "decision_index": self.decision_index, **record}
        if not self.include_observation:
            payload.pop("observation", None)
        self._handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
        self._handle.flush()

    def close(self) -> None:
        if not self._handle.closed:
            self._handle.close()

    def __enter__(self) -> "DecisionRecorder":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def probe_observation(league: League, phase: str, tier: str) -> dict[str, Any]:
    """The observation the agent is about to receive, taken without side effects.

    ``League.observation`` is not read-only -- it regenerates the incoming trade
    offers for the window -- so it cannot be called on the live league just to
    look. Running it on a deep copy is equivalent because both are deterministic
    from identical state, and leaves the real league untouched.
    """
    probe = copy.deepcopy(league)
    probe.begin_decision_window()
    return probe.observation(phase, tier=tier, interaction_round=0)


def _ghost_config(config: EpisodeConfig, tier: str) -> EpisodeConfig:
    """Force a scripted ghost onto the subject's observation tier.

    Built-in agents are normally handed the untruncated observation. A ghost
    that saw more than the subject would turn every card into a mix of "chose
    differently" and "was shown more", which is the asymmetry ``ScaffoldViewAgent``
    exists to measure separately. Holding the tier constant keeps a card about
    the choice alone.
    """
    return dataclasses.replace(config, observation_tier=tier, builtin_full_observation=False)


def record_episode(
    agent: Agent,
    seed: int,
    recorder: DecisionRecorder,
    *,
    seasons: int = 5,
    user_team_id: int = 0,
    config: EpisodeConfig | None = None,
) -> League:
    """Play an episode, recording every decision window. Returns the final league.

    Mirrors ``runner.run_episode``'s season/phase ordering exactly and delegates
    each decision to the real ``run_decision_point``. Pinned by
    ``tests/test_recorder.py::test_recorded_episode_matches_run_episode``.
    """
    episode_config = config or EpisodeConfig()
    league = League.new(seed=seed, user_team_id=user_team_id)
    recorder.start_episode(seed)
    phases = list(PHASES) if episode_config.include_midseason else [phase for phase in PHASES if phase != "midseason"]
    tier = _observation_tier_for_agent(agent, episode_config)
    ghost_config = _ghost_config(episode_config, tier)

    for season_index in range(1, seasons + 1):
        for phase in phases:
            if phase == "midseason":
                league.prepare_midseason()
            if phase == "trade_deadline":
                league.prepare_trade_deadline()
            if phase == "draft":
                league.run_opponent_draft(before_user=True)

            before = score_components(league, user_team_id)
            observation = probe_observation(league, phase, tier)
            logged = len(league.transactions)
            ghosts = [
                _run_ghost(name, league, phase, ghost_config, before, logged)
                for name in recorder.ghost_agents
            ]

            point = run_decision_point(league, agent, phase, episode_config)
            after = score_components(league, user_team_id)
            recorder.write(
                {
                    "agent": recorder.agent_name,
                    "season": season_index,
                    "phase": phase,
                    "observation": observation,
                    "actions": _actions_since(league, logged, user_team_id),
                    "results": point["results"],
                    "delta": component_delta(before, after),
                    "failed": point["failed"],
                    "illegal_actions_total": league.illegal_actions,
                    "ghosts": ghosts,
                }
            )

            if phase == "draft":
                league.run_opponent_draft(before_user=False)
            league.run_autopilot_opponents(phase)
        league.simulate_season()
    return league


def _run_ghost(
    name: str,
    league: League,
    phase: str,
    config: EpisodeConfig,
    before: dict[str, float],
    logged: int,
) -> dict[str, Any]:
    """Play one policy's turn on a throwaway copy of this league.

    A ghost that raises is recorded as an error rather than killing the run:
    this is illustrative content, and losing one card beats losing an episode.
    """
    ghost_league = copy.deepcopy(league)
    try:
        point = run_decision_point(ghost_league, AGENTS[name](), phase, config)
    except Exception as exc:  # noqa: BLE001 - recording must not break a run
        return {"agent": name, "error": f"{type(exc).__name__}: {exc}"}
    return {
        "agent": name,
        "actions": _actions_since(ghost_league, logged, ghost_league.user_team_id),
        "results": point["results"],
        "delta": component_delta(before, score_components(ghost_league, ghost_league.user_team_id)),
    }


def _actions_since(league: League, logged: int, team_id: int) -> list[dict[str, Any]]:
    """Actions this team submitted after the log reached ``logged`` entries.

    Sliced by index rather than scanned backwards, because the log interleaves
    opponent activity -- the draft records other teams' picks -- and a backwards
    scan would stop at the first one. Rejected actions are kept: a policy that
    tried an illegal trade still made that choice.
    """
    return [
        transaction.action
        for transaction in league.transactions[logged:]
        if transaction.team_id == team_id
    ]
