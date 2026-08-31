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
import hashlib
import json
import math
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from gm_bench.agents import AGENTS, Agent
from gm_bench.contract import contract_fingerprint, scaffold_fingerprint
from gm_bench.protocol import PHASES, EpisodeConfig
from gm_bench.runner import _observation_tier_for_agent, run_decision_point
from gm_bench.scaffold_view import compact_observation, scaffold_view_observation
from gm_bench.scoring import SCORE_COMPONENT_METRICS, score_components
from gm_bench.session import PersistentProcessAgent
from gm_bench.simulator import League

RECORD_SCHEMA = "gm-bench-decision-record-v1"
REPLAY_SCHEMA = "gm-bench-decision-replay-v1"
RECORDER_VERSION = "1"
# JSON number formatting differs subtly between CPython and Pyodide. Replay
# fixtures intentionally canonicalize finite floats to this precision so a
# browser replay can attest the same state without pretending to preserve
# meaningless binary tail bits. Non-finite values remain an error.
CANONICAL_FLOAT_DECIMALS = 12
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
        agent_metadata: dict[str, Any] | None = None,
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
        self.agent_metadata: dict[str, Any] = dict(agent_metadata or {})
        self.provenance = _provenance()
        self.seed: int | None = None
        self.decision_index = 0
        self._records: list[dict[str, Any]] = []
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("w", encoding="utf-8")

    def start_episode(self, seed: int) -> None:
        self.seed = seed
        self.decision_index = 0
        self._records = []

    def write(self, record: dict[str, Any]) -> None:
        self.decision_index += 1
        provider = self.agent_metadata.get("provider")
        if provider and "scaffold_fingerprint" not in self.provenance:
            self.provenance = _provenance(str(provider))
        payload = {
            "schema": RECORD_SCHEMA,
            "seed": self.seed,
            "decision_index": self.decision_index,
            "agent_metadata": self.agent_metadata,
            "provenance": self.provenance,
            **record,
        }
        if not self.include_observation:
            payload.pop("observation", None)
        self._records.append(copy.deepcopy(payload))
        self._handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
        self._handle.flush()

    def export_replay_fixture(
        self,
        path: str | Path,
        league: League,
        *,
        config: EpisodeConfig,
        user_team_id: int = 0,
    ) -> Path:
        """Write a self-contained, no-provider-call replay fixture."""
        fixture = {
            "schema": REPLAY_SCHEMA,
            "seed": self.seed,
            "config": dataclasses.asdict(config),
            "user_team_id": user_team_id,
            "agent": self.agent_name,
            "metadata": self.agent_metadata,
            "provenance": self.provenance,
            "decisions": [
                {
                    "decision_index": record["decision_index"],
                    "season": record["season"],
                    "phase": record["phase"],
                    # Every round is retained when the capture wrapper could
                    # observe it; old/manual records truthfully fall back to
                    # the flattened action list as one round.
                    "interaction_rounds": record.get("interaction_rounds")
                    or [{"round": 0, "actions": record.get("actions", [])}],
                }
                for record in self._records
            ],
            "expected": {
                "state": canonical_state(league),
                "state_digest": canonical_state_digest(league),
            },
        }
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(fixture, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        return destination

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
    profile = _agent_profile(agent)
    model_subject = bool(getattr(agent, "metadata", {}).get("provider"))
    ghost_config = _ghost_config(episode_config, tier)

    persistent = isinstance(agent, PersistentProcessAgent)
    try:
        if persistent:
            agent.start_episode(seed, seasons)
        for season_index in range(1, seasons + 1):
            for phase in phases:
                if phase == "midseason":
                    league.prepare_midseason()
                if phase == "trade_deadline":
                    league.prepare_trade_deadline()
                if phase == "draft":
                    league.run_opponent_draft(before_user=True)

                before = score_components(league, user_team_id)
                raw_observation = probe_observation(league, phase, tier)
                observation = compact_observation(raw_observation, profile) if model_subject else raw_observation
                logged = len(league.transactions)
                ghosts = [
                    _run_ghost(
                        name,
                        league,
                        phase,
                        ghost_config,
                        before,
                        logged,
                        profile=profile if model_subject else None,
                    )
                    for name in recorder.ghost_agents
                ]

                capture = _capture_agent(agent, profile=profile)
                point = run_decision_point(league, capture, phase, episode_config)
                after = score_components(league, user_team_id)
                recorder.write(
                    {
                        "agent": recorder.agent_name,
                        "season": season_index,
                        "phase": phase,
                        "observation": observation,
                        "actions": _actions_since(league, logged, user_team_id),
                        "interaction_rounds": capture.rounds,
                        "results": point["results"],
                        "usage_records": point["usage_records"],
                        "decision_seconds": point["decision_seconds"],
                        "harness_latency_ms": point["harness_latency_ms"],
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
    finally:
        if persistent:
            agent.end_episode()
    return league


def _run_ghost(
    name: str,
    league: League,
    phase: str,
    config: EpisodeConfig,
    before: dict[str, float],
    logged: int,
    *,
    profile: str | None = None,
) -> dict[str, Any]:
    """Play one policy's turn on a throwaway copy of this league.

    A ghost that raises is recorded as an error rather than killing the run:
    this is illustrative content, and losing one card beats losing an episode.
    """
    ghost_league = copy.deepcopy(league)
    ghost_agent: Agent = _ScaffoldGhostAgent(AGENTS[name](), profile) if profile else AGENTS[name]()
    capture = _DecisionCaptureAgent(ghost_agent, profile=profile)
    try:
        point = run_decision_point(ghost_league, capture, phase, config)
    except Exception as exc:  # noqa: BLE001 - recording must not break a run
        return {"agent": name, "error": f"{type(exc).__name__}: {exc}"}
    return {
        "agent": name,
        "interaction_rounds": capture.rounds,
        "actions": _actions_since(ghost_league, logged, ghost_league.user_team_id),
        "results": point["results"],
        "usage_records": point["usage_records"],
        "failed": point["failed"],
        "decision_seconds": point["decision_seconds"],
        "harness_latency_ms": point["harness_latency_ms"],
        "delta": component_delta(before, score_components(ghost_league, ghost_league.user_team_id)),
    }


class _DecisionCaptureAgent(Agent):
    """Delegate an agent while retaining exact per-round calls for fixtures."""

    def __init__(self, wrapped: Agent, *, profile: str) -> None:
        self.wrapped = wrapped
        self.name = wrapped.name
        self.profile = profile
        self.rounds: list[dict[str, Any]] = []
        self.metadata = getattr(wrapped, "metadata", {})

    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        actions, usage = self.wrapped.act_with_usage(observation)
        self._capture_observation(observation, actions, usage)
        return actions

    def act_with_usage(self, observation: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        actions, usage = self.wrapped.act_with_usage(observation)
        self._capture_observation(observation, actions, usage)
        return actions, usage

    def _capture_observation(
        self, observation: dict[str, Any], actions: list[dict[str, Any]], usage: dict[str, Any] | None
    ) -> None:
        self.rounds.append(
            {
                "round": int(observation.get("interaction_round", len(self.rounds))),
                "observation": compact_observation(observation, self.profile),
                "actions": copy.deepcopy(actions),
                "usage": copy.deepcopy(usage),
            }
        )


class _PersistentDecisionCaptureAgent(_DecisionCaptureAgent, PersistentProcessAgent):
    """Keep persistent follow-up dispatch while recording each response."""

    def __init__(self, wrapped: PersistentProcessAgent, *, profile: str) -> None:
        # The recorder owns no process. The wrapped agent receives lifecycle
        # calls once per episode; this proxy exists only for runner dispatch.
        _DecisionCaptureAgent.__init__(self, wrapped, profile=profile)
        self.wrapped = wrapped

    def act_on_results(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        actions, _usage = self.act_on_results_with_usage(results)
        return actions

    def act_on_results_with_usage(
        self,
        results: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        actions, usage = self.wrapped.act_on_results_with_usage(results)
        self.rounds.append(
            {
                "round": len(self.rounds),
                "action_results": copy.deepcopy(results),
                "actions": copy.deepcopy(actions),
                "usage": copy.deepcopy(usage),
            }
        )
        return actions, usage


def _capture_agent(agent: Agent, *, profile: str) -> _DecisionCaptureAgent:
    if isinstance(agent, PersistentProcessAgent):
        return _PersistentDecisionCaptureAgent(agent, profile=profile)
    return _DecisionCaptureAgent(agent, profile=profile)


class _ScaffoldGhostAgent(Agent):
    """Run the requested scripted policy on the model's compact scaffold."""

    def __init__(self, wrapped: Agent, profile: str) -> None:
        self.wrapped = wrapped
        self.name = wrapped.name
        self.profile = profile

    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        return self.wrapped.act(scaffold_view_observation(observation, self.profile))

    def act_with_usage(self, observation: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        return self.wrapped.act_with_usage(scaffold_view_observation(observation, self.profile))


def _agent_profile(agent: Agent) -> str:
    metadata = getattr(agent, "metadata", {})
    profile = metadata.get("profile") if isinstance(metadata, dict) else None
    return profile if profile in {"tiny", "compact"} else "compact"


def _provenance(provider: str | None = None) -> dict[str, Any]:
    try:
        checkout = Path(__file__).resolve().parents[1]
        head = (
            subprocess.run(
                ["git", "-C", str(checkout), "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                check=False,
                timeout=2,
            ).stdout.strip()
            or None
        )
    except (OSError, subprocess.SubprocessError):
        head = None
    provenance: dict[str, Any] = {
        "recorder_version": RECORDER_VERSION,
        "contract_fingerprint": contract_fingerprint(),
        "git_head": head,
    }
    if provider:
        provenance["scaffold_fingerprint"] = scaffold_fingerprint(provider)
    return provenance


def canonicalize_state(value: Any) -> Any:
    """Normalize JSON-shaped state for cross-runtime replay comparison."""
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite replay state value is not allowed")
        rounded = round(value, CANONICAL_FLOAT_DECIMALS)
        return 0.0 if rounded == 0.0 else rounded
    if isinstance(value, dict):
        return {str(key): canonicalize_state(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [canonicalize_state(item) for item in value]
    if isinstance(value, (set, frozenset)):
        # Sets carry no order of their own (League.released_by is one), so the
        # replay digest sorts them into a stable sequence before hashing.
        return sorted((canonicalize_state(item) for item in value), key=repr)
    return value


def canonical_state(league: League) -> dict[str, Any]:
    """Return the normalized full simulator state used by replay fixtures."""
    payload = dataclasses.asdict(league)
    payload.pop("_action_results", None)
    normalized = canonicalize_state(payload)
    assert isinstance(normalized, dict)
    return normalized


def _canonical_state(league: League) -> dict[str, Any]:
    """Backward-compatible private alias for callers of the initial API."""
    return canonical_state(league)


def canonical_state_digest(league: League | dict[str, Any]) -> str:
    state = canonical_state(league) if isinstance(league, League) else canonicalize_state(league)
    encoded = json.dumps(state, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class _ReplayAgent(Agent):
    name = "replay"

    def __init__(self, rounds: list[dict[str, Any]]) -> None:
        self.rounds = rounds
        self.index = 0

    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        if self.index >= len(self.rounds):
            raise ValueError("replay fixture ran out of interaction rounds")
        actions = self.rounds[self.index].get("actions")
        self.index += 1
        if not isinstance(actions, list):
            raise ValueError("replay interaction round actions must be a list")
        return copy.deepcopy(actions)


def replay_fixture(fixture: dict[str, Any]) -> League:
    """Replay a fixture's recorded subject actions without any provider calls."""
    if fixture.get("schema") != REPLAY_SCHEMA:
        raise ValueError(f"unsupported replay schema: {fixture.get('schema')!r}")
    seed = fixture.get("seed")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError("replay fixture seed must be an integer")
    raw_config = fixture.get("config")
    if raw_config is None:
        raw_config = {}
    if not isinstance(raw_config, dict):
        raise ValueError("replay fixture config must be an object")
    allowed = {field.name for field in dataclasses.fields(EpisodeConfig)}
    config = EpisodeConfig(**{key: value for key, value in raw_config.items() if key in allowed})
    user_team_id = int(fixture.get("user_team_id", 0))
    decisions = fixture.get("decisions")
    if not isinstance(decisions, list):
        raise ValueError("replay fixture decisions must be a list")
    league = League.new(seed=seed, user_team_id=user_team_id)
    phases = list(PHASES) if config.include_midseason else [phase for phase in PHASES if phase != "midseason"]
    expected_windows = len(phases) * max(0, len(decisions) // len(phases)) if phases else 0
    if len(decisions) != expected_windows or len(decisions) % len(phases) != 0:
        raise ValueError("replay fixture does not contain complete season phase windows")
    cursor = 0
    seasons = len(decisions) // len(phases)
    for season_index in range(1, seasons + 1):
        for phase in phases:
            if phase == "midseason":
                league.prepare_midseason()
            if phase == "trade_deadline":
                league.prepare_trade_deadline()
            if phase == "draft":
                league.run_opponent_draft(before_user=True)
            record = decisions[cursor]
            cursor += 1
            if not isinstance(record, dict):
                raise ValueError(f"replay fixture decision {cursor} must be an object")
            if record.get("season") != season_index or record.get("phase") != phase:
                raise ValueError(f"replay fixture decision {cursor} is out of phase order")
            rounds = record.get("interaction_rounds")
            if rounds is None or rounds == []:
                rounds = [{"round": 0, "actions": record.get("actions", [])}]
            elif not isinstance(rounds, list):
                raise ValueError(f"replay fixture decision {cursor} interaction_rounds must be a list")
            if not all(isinstance(round_record, dict) for round_record in rounds):
                raise ValueError(f"replay fixture decision {cursor} interaction rounds must be objects")
            agent = _ReplayAgent(rounds)
            run_decision_point(league, agent, phase, config)
            if agent.index != len(rounds):
                raise ValueError(f"replay fixture contains unused rounds at decision {cursor}")
            if phase == "draft":
                league.run_opponent_draft(before_user=False)
            league.run_autopilot_opponents(phase)
        league.simulate_season()
    return league


def validate_replay_fixture(source: str | Path | dict[str, Any]) -> dict[str, Any]:
    """Replay and verify a fixture, returning a small validation summary."""
    if isinstance(source, (str, Path)):
        payload = json.loads(Path(source).read_text(encoding="utf-8"))
    else:
        payload = source
    if not isinstance(payload, dict):
        raise ValueError("replay fixture must be a JSON object")
    expected = payload.get("expected")
    if not isinstance(expected, dict) or not isinstance(expected.get("state_digest"), str):
        raise ValueError("replay fixture expected.state_digest is required")
    league = replay_fixture(payload)
    digest = canonical_state_digest(league)
    if digest != expected["state_digest"]:
        raise ValueError(f"replay final-state digest mismatch: expected {expected['state_digest']}, got {digest}")
    return {"valid": True, "schema": REPLAY_SCHEMA, "state_digest": digest, "decisions": len(payload["decisions"])}


def _actions_since(league: League, logged: int, team_id: int) -> list[dict[str, Any]]:
    """Actions this team submitted after the log reached ``logged`` entries.

    Sliced by index rather than scanned backwards, because the log interleaves
    opponent activity -- the draft records other teams' picks -- and a backwards
    scan would stop at the first one. Rejected actions are kept: a policy that
    tried an illegal trade still made that choice.
    """
    return [transaction.action for transaction in league.transactions[logged:] if transaction.team_id == team_id]
