"""Bounded, offline draft counterfactuals. Experimental; never a benchmark lane."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import platform
import random
import statistics
from dataclasses import asdict
from pathlib import Path
from typing import Any

from gm_bench.agent_utils import public_asset_value
from gm_bench.agents import ValueAgent
from gm_bench.contract import benchmark_contract
from gm_bench.protocol import PHASES
from gm_bench.scoring import score_team
from gm_bench.simulator import League

CHECKPOINT_VERSION = "gm-counterfactual-checkpoint-v1"
COMPARISON_VERSION = "gm-counterfactual-comparison-v1"
POLICY = "value-one-batch-per-window-v1"
MAX_CANDIDATES = 12
MAX_HORIZON = 3
MAX_ROLLOUTS = 32
PUBLIC_SEEDS = range(1, 33)
LIMITATIONS = [
    "Values are relative to this candidate set and continuation policy, not an optimal-policy oracle.",
    "Uncertainty samples independent pseudorandom downstream streams conditional on one fixed checkpoint.",
    "Existing hidden attributes, generated draft classes and direct seed-keyed randomness stay fixed across rollouts.",
    "RNG audits cover League._rng only; offers, reservations, valuations and scout noise use unaudited fixed streams.",
    "Common stream seeds do not imply event-level common random numbers: branches can consume draws differently.",
    "Normal 95% intervals are descriptive Monte Carlo approximations, unreliable at small sample sizes.",
    "Horizon rows from the same rollout are correlated; seasons are never independent samples.",
    "Public development seeds support diagnostics only, not held-out benchmark or generalization claims.",
]


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _state_tree(value: Any) -> Any:
    # Preserve key types, list order and unordered sets without unsafe deserialization.
    if isinstance(value, dict):
        return {"map": sorted([[_state_tree(k), _state_tree(v)] for k, v in value.items()], key=canonical)}
    if isinstance(value, (set, frozenset)):
        return {"set": sorted([_state_tree(v) for v in value], key=canonical)}
    if isinstance(value, (tuple, list)):
        return [_state_tree(v) for v in value]
    return value


def state_digest(league: League) -> str:
    return digest(_state_tree(asdict(league)))


def provenance() -> dict[str, Any]:
    root = Path(__file__).parent
    files = ("counterfactual.py", "agents.py", "agent_utils.py")
    return {
        "benchmark_contract": benchmark_contract(),
        "implementation_sha256": digest({name: (root / name).read_text() for name in files}),
        "python": platform.python_version(),
        "continuation_policy": POLICY,
    }


def _integer(value: Any, low: int, high: int, name: str) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer in [{low}, {high}]")
    return value


def _prepare(league: League, phase: str) -> dict[str, Any]:
    if phase == "midseason":
        league.prepare_midseason()
    elif phase == "trade_deadline":
        league.prepare_trade_deadline()
    elif phase == "draft":
        league.run_opponent_draft(before_user=True)
    league.begin_decision_window()
    return league.observation(phase)


def _finish(league: League, phase: str) -> None:
    if phase == "draft":
        league.run_opponent_draft(before_user=False)
    league.run_autopilot_opponents(phase)


def _policy_window(league: League, phase: str) -> dict[str, Any]:
    observation = _prepare(league, phase)
    actions = ValueAgent().act(observation)
    results = [result.to_dict() for result in league.apply_actions(actions, phase)]
    _finish(league, phase)
    return {"season": observation["season"], "phase": phase, "actions": actions, "results": results}


def _checkpoint(seed: int, season: int) -> tuple[dict[str, Any], League]:
    _integer(seed, 1, 32, "public development seed")
    _integer(season, 1, 3, "checkpoint season")
    league = League.new(seed)
    history = []
    for year in range(1, season + 1):
        for phase in PHASES:
            if year == season and phase == "draft":
                observation = _prepare(league, phase)
                payload = {
                    "schema_version": CHECKPOINT_VERSION,
                    "track": "experimental-public-dev",
                    "family": "draft",
                    "seed": seed,
                    "season": season,
                    "phase": "draft",
                    "provenance": provenance(),
                    "prefix": history,
                    "observation": observation,
                    "state_sha256": state_digest(league),
                }
                payload["checkpoint_id"] = digest(payload)
                return payload, league
            history.append(_policy_window(league, phase))
        league.simulate_season()
    raise AssertionError("unreachable")


def make_checkpoint(seed: int, season: int = 1) -> dict[str, Any]:
    """Capture a public recipe at the first user draft pick of a bounded episode."""
    return _checkpoint(seed, season)[0]


def replay_checkpoint(checkpoint: dict[str, Any]) -> League:
    """Rebuild and compare the entire recipe, public view and full-state digest."""
    if not isinstance(checkpoint, dict):
        raise ValueError("checkpoint must be an object")
    expected, league = _checkpoint(checkpoint.get("seed"), checkpoint.get("season"))
    if canonical(checkpoint) != canonical(expected):
        raise ValueError("checkpoint replay mismatch (content, provenance, Python version or integrity)")
    return league


def read_json(path: str | Path) -> Any:
    path = Path(path)
    if path.stat().st_size > 32_000_000:
        raise ValueError("input exceeds the 32 MB limit")
    return json.loads(path.read_text(), parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def save_json(path: str | Path, payload: Any) -> None:
    Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")


def _validate_candidates(league: League, candidates: Any) -> list[dict[str, Any]]:
    if not isinstance(candidates, list) or not 2 <= len(candidates) <= MAX_CANDIDATES:
        raise ValueError(f"provide 2..{MAX_CANDIDATES} distinct draft actions")
    seen: set[int] = set()
    for action in candidates:
        if not isinstance(action, dict) or set(action) != {"type", "prospect_id"} or action["type"] != "draft":
            raise ValueError("only single draft actions with type and prospect_id are supported")
        pid = action["prospect_id"]
        if type(pid) is not int or pid in seen:
            raise ValueError("prospect IDs must be distinct integers")
        seen.add(pid)
        branch = copy.deepcopy(league)
        before_rng = branch.rng_state_offset
        results = branch.apply_actions([action], "draft")
        if len(results) != 1 or not results[0].accepted:
            raise ValueError(f"illegal candidate: {action}")
        if branch.rng_state_offset != before_rng:
            raise ValueError("draft candidate unexpectedly consumed a simulator RNG stream")
    return copy.deepcopy(candidates)


def enumerate_candidates(checkpoint: dict[str, Any], limit: int = 6) -> list[dict[str, Any]]:
    _integer(limit, 2, MAX_CANDIDATES, "candidate limit")
    league = replay_checkpoint(checkpoint)
    # Only published prospects enter the candidate pool. Stable ties by ID.
    prospects = checkpoint["observation"]["draft_class"]
    ranked = sorted(prospects, key=lambda player: (-public_asset_value(player), player["id"]))
    return _validate_candidates(league, [{"type": "draft", "prospect_id": p["id"]} for p in ranked[:limit]])


class _AuditedRandom(random.Random):
    def __init__(self, seed: str, record: dict[str, Any]):
        super().__init__(seed)
        self.record = record

    def random(self) -> float:
        self.record["random_calls"] += 1
        return super().random()

    def getrandbits(self, k: int) -> int:
        self.record["getrandbits_calls"] += 1
        self.record["requested_bits"] += k
        return super().getrandbits(k)


class _RolloutLeague(League):
    """Change only downstream stream seeding; keep latent state and seed-keyed mechanics fixed."""

    def _rng(self, namespace: str) -> random.Random:
        self.rng_state_offset += 1
        record = {
            "season": self.season,
            "namespace": namespace,
            "offset": self.rng_state_offset,
            "random_calls": 0,
            "getrandbits_calls": 0,
            "requested_bits": 0,
        }
        self.rng_audit.append(record)
        key = f"cf-v1:{self.seed}:{self.rollout_seed}:{self.season}:{self.rng_state_offset}:{namespace}"
        return _AuditedRandom(key, record)


def _branch(league: League, rollout_seed: int) -> _RolloutLeague:
    branch = _RolloutLeague(**{name: copy.deepcopy(getattr(league, name)) for name in League.__dataclass_fields__})
    branch.rollout_seed = rollout_seed
    branch.rng_audit = []
    return branch


def uncertainty(values: list[float]) -> dict[str, Any]:
    n = len(values)
    avg = statistics.mean(values)
    se = statistics.stdev(values) / math.sqrt(n) if n > 1 else None
    return {
        "n": n,
        "mean": avg,
        "standard_error": se,
        "normal_95_interval": [avg - 1.96 * se, avg + 1.96 * se] if se is not None else None,
    }


def compare(
    checkpoint: dict[str, Any],
    candidates: list[dict[str, Any]] | None = None,
    *,
    horizons: tuple[int, ...] = (1, 2, 3),
    rollout_seeds: tuple[int, ...] = (1001, 1002, 1003, 1004),
) -> dict[str, Any]:
    """Branch each legal candidate using matched policy and independently seeded whole rollouts."""
    if not horizons or len(horizons) > MAX_HORIZON:
        raise ValueError("provide 1..3 distinct horizons")
    for horizon in horizons:
        _integer(horizon, 1, MAX_HORIZON, "horizon")
    if len(set(horizons)) != len(horizons):
        raise ValueError("duplicate horizon")
    if not 1 <= len(rollout_seeds) <= MAX_ROLLOUTS:
        raise ValueError("provide 1..32 independent rollout seeds")
    for seed in rollout_seeds:
        _integer(seed, 1001, 1032, "public rollout seed")
    if len(set(rollout_seeds)) != len(rollout_seeds):
        raise ValueError("duplicate rollout seeds are not independent samples")
    league = replay_checkpoint(checkpoint)
    before = state_digest(league)
    actions = _validate_candidates(league, candidates if candidates is not None else enumerate_candidates(checkpoint))
    rows = []
    audits = []
    for candidate_index, action in enumerate(actions):
        for seed in rollout_seeds:
            branch = _branch(league, seed)
            initial_offset = branch.rng_state_offset
            result = branch.apply_actions([action], "draft")[0]
            if not result.accepted or initial_offset != branch.rng_state_offset:
                raise ValueError("candidate legality/RNG invariant violated")
            _finish(branch, "draft")
            start_summaries = len(branch.summaries)
            for horizon in range(1, max(horizons) + 1):
                if horizon > 1:
                    for phase in PHASES:
                        _policy_window(branch, phase)
                branch.simulate_season()
                if horizon in horizons:
                    rows.append(
                        {
                            "candidate_index": candidate_index,
                            "rollout_seed": seed,
                            "horizon": horizon,
                            "score": score_team(branch, branch.user_team_id),
                            "downstream_wins": sum(s.wins for s in branch.summaries[start_summaries:])
                            - league.user_team.wins,
                            "state_sha256": state_digest(branch),
                            "rng_streams": len(branch.rng_audit),
                        }
                    )
            audits.append({"candidate_index": candidate_index, "rollout_seed": seed, "streams": branch.rng_audit})
    summaries = []
    for index in range(len(actions)):
        for horizon in sorted(horizons):
            selected = [row for row in rows if row["candidate_index"] == index and row["horizon"] == horizon]
            reference = {
                row["rollout_seed"]: row for row in rows if row["candidate_index"] == 0 and row["horizon"] == horizon
            }
            summaries.append(
                {
                    "candidate_index": index,
                    "horizon": horizon,
                    "score": uncertainty([row["score"] for row in selected]),
                    "paired_score_delta_vs_candidate_0": uncertainty(
                        [row["score"] - reference[row["rollout_seed"]]["score"] for row in selected]
                    ),
                    "downstream_wins": uncertainty([row["downstream_wins"] for row in selected]),
                }
            )
    audit_equal = all(
        entry["streams"]
        == next(
            a["streams"] for a in audits if a["candidate_index"] == 0 and a["rollout_seed"] == entry["rollout_seed"]
        )
        for entry in audits
    )
    if state_digest(league) != before:
        raise AssertionError("checkpoint was mutated by branch simulation")
    payload = {
        "schema_version": COMPARISON_VERSION,
        "track": "experimental-public-dev",
        "checkpoint": copy.deepcopy(checkpoint),
        "candidates": actions,
        "horizons": sorted(horizons),
        "rollout_seeds": list(rollout_seeds),
        "continuation_policy": POLICY,
        "uncertainty_unit": "independent downstream rollout, conditional on checkpoint",
        "randomness": {
            "mode": "paired-stream-seeds",
            "event_level_crn_guaranteed": False,
            "primitive_consumption_equal": audit_equal,
        },
        "limitations": LIMITATIONS,
        "rows": rows,
        "summaries": summaries,
        "rng_audits": audits,
    }
    payload["comparison_id"] = digest(payload)
    return payload


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    capture = sub.add_parser("checkpoint", help="save a replayable public draft checkpoint")
    capture.add_argument("--seed", type=int, default=1)
    capture.add_argument("--season", type=int, default=1)
    capture.add_argument("--out", required=True)
    run = sub.add_parser("compare", help="export bounded draft branches and RNG audits")
    run.add_argument("checkpoint")
    run.add_argument("--candidates", help="JSON list of single draft actions; defaults to top public asset values")
    run.add_argument("--limit", type=int, default=6)
    run.add_argument("--horizons", type=int, nargs="+", default=[1, 2, 3])
    run.add_argument("--rollouts", type=int, default=8)
    run.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "checkpoint":
            payload = make_checkpoint(args.seed, args.season)
        else:
            _integer(args.rollouts, 1, MAX_ROLLOUTS, "rollouts")
            checkpoint = read_json(args.checkpoint)
            candidates = read_json(args.candidates) if args.candidates else enumerate_candidates(checkpoint, args.limit)
            payload = compare(
                checkpoint,
                candidates,
                horizons=tuple(args.horizons),
                rollout_seeds=tuple(range(1001, 1001 + args.rollouts)),
            )
        save_json(args.out, payload)
    except (ValueError, OSError, TypeError, KeyError) as exc:
        parser.error(str(exc))
    print(f"Saved {payload['schema_version']} to {args.out}")


if __name__ == "__main__":
    main()
