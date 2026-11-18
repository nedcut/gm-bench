"""Candidate end-of-run scores for GM-Bench 2.2, tested against later seasons.

score-v2 takes its end-state terms after the final rollover, when expiring
contracts have just left. The 2026-10-26 notebook entry found that this
over-credits extensions: a planner's end state was 43-55 points above
``pick-trader``'s, and over five more seasons it won no more. The 2.2 brief
will tell every model when the credit is counted, so the credit has to be
right first (``docs/bench_v2_2_spec.md``, phase 1).

Each candidate replaces only the end-state terms. The winning terms and the
penalty stay score-v2's. The yardstick is the one the notebook already uses:
hand the final league to a scripted manager for five more seasons, on the
same dice as ``pick-trader``'s final league on that seed, and score the
winning that follows with score-v2's winning weights. A well-priced end
state predicts that gap one for one.

Two stages:

- ``sides`` plays every policy on public seeds (and replays 2.1 model ledgers
  when run directories are given), and caches one feature record per final
  league under ``--cache`` (outside the repository; mode 0600).
- ``report`` reads the cache and writes the comparison. Model rows are
  reported as per-row means only, so no private seed or per-episode score
  leaves the cache.

    python scripts/score_v3_candidates.py sides --seeds 101-172 [RUN_DIR ...]
    python scripts/score_v3_candidates.py report --out results/diagnostics/score_v3/candidates.json
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import random
import statistics
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import ceiling_planner as planner  # noqa: E402
import ceiling_search  # noqa: E402

from gm_bench.agentic.validate import replayable_ledger  # noqa: E402
from gm_bench.agents import Agent  # noqa: E402
from gm_bench.models import pick_value  # noqa: E402
from gm_bench.protocol import PHASES  # noqa: E402
from gm_bench.scoring import score_components as score_components_v1  # noqa: E402
from gm_bench.v21.episode import AgenticEpisode21, ledger_benchmark_version  # noqa: E402
from gm_bench.v21.rules import League21  # noqa: E402
from gm_bench.v21.scoring import SCALE, score_components  # noqa: E402
from gm_bench.validity import CANARY_AGENTS  # noqa: E402

SEASONS = 5
EXTRA_SEASONS = 5
# The managers that play the later seasons. ``pick-trader`` and ``strategic`` share a
# preseason routine (at most eight signings a window); ``contend-1g`` signs and buys
# for strength at once, so it prices a thin roster differently.
MANAGERS = ("pick-trader", "strategic", "contend-1g")
# A fourth judge, reported alone and never part of the yardstick: the engine fills
# the roster to 21 first, then ``pick-trader`` manages. It does not share the
# eight-signing preseason limit the first two judges have.
EXTRA_JUDGES = ("filled:pick-trader",)
JUDGES = (*MANAGERS, *EXTRA_JUDGES)
# Roster sizes the engine-fill candidates fill to (0 would be score-v2).
FILL_TARGETS = (8, 10, 12, 14, 16, 18, 21)
REFERENCE = "pick-trader"
WINNING = ("season_wins", "expected_playoff_rounds", "expected_championships")
ROSTER_TERMS = ("total_assets", "young_assets", "current_strength", "roster_depth")
END_STATE = ("total_assets", "young_assets", "future_pick_assets", "cap_room", "current_strength", "roster_depth")
FIT_SEEDS = range(101, 125)
CHECK_SEEDS = range(125, 173)
DEFAULT_CACHE = Path("~/.cache/gm-bench-score-v3").expanduser()


# --------------------------------------------------------------------------
# Policies
# --------------------------------------------------------------------------


class Rundown(Agent):
    """A base policy that makes no extension in the final season (the Claude rows' pattern)."""

    def __init__(self, base: str) -> None:
        self.base = planner.policy_factory(base)()
        self.name = f"rundown:{base}"

    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        actions = self.base.act(observation)
        if int(observation["season"]) < SEASONS:
            return actions
        return [a for a in actions if a.get("type") != "extend_contract"] or [{"type": "noop"}]


class ExtendAll(Agent):
    """A base policy that also extends every eligible player in the final preseason.

    Each extension runs for the shortest term that outlasts the final
    rollover, at the published quote, while the payroll stays under the hard
    cap. This is the move the end-state terms are suspected of over-paying.
    """

    def __init__(self, base: str) -> None:
        self.base = planner.policy_factory(base)()
        self.name = f"extend-all:{base}"

    def act(self, observation: dict[str, Any]) -> list[dict[str, Any]]:
        actions = self.base.act(observation)
        if (
            int(observation["season"]) < SEASONS
            or observation["phase"] != "preseason"
            or int(observation.get("interaction_round", 0)) != 0
        ):
            return actions
        team = observation["team"]
        rules = observation["rules"]
        hard_cap = float(rules["salary_cap"]) + float(rules.get("hard_cap_buffer", 8.0))
        years = planner.contract_years_to_end(SEASONS, extension=True)
        # Players the base policy already extends, releases or trades away are left alone,
        # and its own signings and extensions come off the room first.
        taken = {a.get("player_id") for a in actions if a.get("type") in ("extend_contract", "release")}
        taken.update(pid for a in actions if a.get("type") == "trade" for pid in a.get("give_player_ids") or [])
        salaries = {p["id"]: float(p["salary"]) for p in team["roster"]}
        payroll = float(team["payroll"])
        for action in actions:
            if action.get("type") == "sign_free_agent":
                payroll += float(action.get("salary", 0.0))
            elif action.get("type") == "extend_contract":
                payroll += float(action.get("salary", 0.0)) - salaries.get(action.get("player_id"), 0.0)
        extra = []
        for player in sorted(team["roster"], key=lambda p: (-p["overall"], p["id"])):
            quotes = player.get("extension_quotes")
            if not quotes or player["id"] in taken:
                continue
            salary = float(quotes[str(years)])
            if payroll - player["salary"] + salary > hard_cap:
                continue
            extra.append({"type": "extend_contract", "player_id": player["id"], "years": years, "salary": salary})
            payroll += salary - player["salary"]
        return [a for a in actions if a.get("type") != "noop"] + extra or [{"type": "noop"}]


SCRIPTED = (
    "pick-trader",
    "strategic",
    "shrewd",
    "value",
    *(cls.name for cls in CANARY_AGENTS),
    "contend-1g",
    "contend-blind",
    "contend-preseason-1g",
    "contend-preseason-blind",
    "rundown:pick-trader",
    "rundown:contend-1g",
    "extend-all:pick-trader",
    "extend-all:strategic",
)


def make_agent(name: str) -> Agent:
    kind, _, base = name.partition(":")
    if kind == "rundown":
        return Rundown(base)
    if kind == "extend-all":
        return ExtendAll(base)
    canary = next((cls for cls in CANARY_AGENTS if cls.name == name), None)
    return canary() if canary is not None else planner.policy_factory(name)()


# --------------------------------------------------------------------------
# One final league -> one feature record
# --------------------------------------------------------------------------


class ProbeLeague(League21):
    """``League21`` that also records the user's roster terms just before each rollover.

    Reads only; every draw and every state change is ``League21``'s
    (``selfcheck`` compares final scores against a plain ``League21``).
    """

    def _age_and_contracts(self, rng):  # type: ignore[override]
        team = self.user_team
        before = list(team.roster)
        pre = score_components_v1(self, self.user_team_id)
        expired = super()._age_and_contracts(rng)
        left = set(expired)
        gone = [self.players[player_id] for player_id in before if player_id in left]
        self.probe = {
            "pre": {name: float(pre[name]) for name in (*ROSTER_TERMS, "cap_room")},
            "expired_assets": sum(p.asset_value for p in gone),
            "expired_young_assets": sum(p.asset_value for p in gone if p.age <= 24),
            "expired_count": len(gone),
        }
        return expired


class ProbeEpisode(AgenticEpisode21):
    """The 2.1 engine on the probe league, so a 2.1 ledger replays under 2.1's own rules."""

    def _open_phase(self) -> None:
        if not isinstance(self.league, ProbeLeague):
            self.league = ProbeLeague.new(seed=self.seed, user_team_id=self.user_team_id)
        super()._open_phase()


def _end_terms(league: Any) -> dict[str, float]:
    parts = score_components(league, league.user_team_id)
    out = {name: float(parts[name]) for name in END_STATE}
    out["end_state"] = sum(parts[f"{name}_contribution"] for name in END_STATE)
    return out


def _future(league: Any, manager: str) -> list[float]:
    """Winning value of each of the next seasons under ``manager`` (score-v2 winning weights)."""
    future = copy.deepcopy(league)
    kind, _, base = manager.partition(":")
    if kind == "filled":
        future._window_signing_appeal = {}
        future._opponent_signings(future.user_team, random.Random(f"{future.seed}:end-of-run-refill"))
        manager = base
    agent = planner.policy_factory(manager)()
    start = len(future.summaries)
    for _season in range(EXTRA_SEASONS):
        for index in range(len(PHASES)):
            ceiling_search.play_step(future, agent, index)
    values = []
    for summary in future.summaries[start:]:
        rounds, title = future.expected_playoffs[summary.season].get(future.user_team_id, (0.0, 0.0))
        values.append(summary.wins * SCALE.season_win + rounds * SCALE.playoff_round + title * SCALE.championship)
    return values


def _refill(league: Any, manager: str) -> dict[str, float]:
    """End-state terms after ``manager`` runs the next preseason (sign, extend, trade, dress)."""
    refilled = copy.deepcopy(league)
    ceiling_search.play_step(refilled, planner.policy_factory(manager)(), 0)
    return {**_end_terms(refilled), "roster": len(refilled.user_team.roster)}


def _refill_autopilot(league: Any) -> dict[str, float]:
    """End-state terms after the engine's own opponent routine fills the user's roster.

    ``League._opponent_signings`` is what every opponent gets after each
    phase: the best free agents by overall, one to three years at the
    published quote, up to 21 players and the cap plus 4, then one clear
    upgrade. It reads no agent policy, so it could be a contract rule.
    """
    refilled = copy.deepcopy(league)
    refilled._window_signing_appeal = {}
    refilled._opponent_signings(refilled.user_team, random.Random(f"{refilled.seed}:end-of-run-refill"))
    return {**_end_terms(refilled), "roster": len(refilled.user_team.roster)}


def _players(league: Any) -> list[list[float]]:
    """(asset value, age, contract years left) for each player on the user's roster."""
    return [
        [round(p.asset_value, 4), p.age, p.contract_years]
        for p in (league.players[player_id] for player_id in league.user_team.roster)
    ]


def _fill(league: Any, target: int) -> dict[str, Any]:
    """End-state terms after the engine fills the user's roster to ``target`` players.

    The first loop of ``League._opponent_signings`` with the roster size as a
    parameter: the best free agents by overall, at the published one-year
    quote for one year (the engine draws one to three), while the payroll
    stays within the cap plus 4. No upgrade signing afterwards, and no dice. It reads no agent policy, so it could be a contract rule.
    """
    filled = copy.deepcopy(league)
    filled._window_signing_appeal = {}
    team = filled.user_team
    needed = max(0, target - len(team.roster))
    candidates = sorted(
        (filled.players[i] for i in filled.free_agents if not filled._resign_blocked(team.id, i)),
        key=lambda player: player.overall,
        reverse=True,
    )
    for player in candidates[: needed * 2]:
        if needed <= 0:
            break
        salary = filled._signing_quote(player, 1, team)
        if filled._payroll(team) + salary <= filled.cap + 4.0:
            filled.free_agents.remove(player.id)
            team.roster.append(player.id)
            player.team_id = team.id
            player.salary = salary
            player.contract_years = 1
            player.contract_signed_season = filled.season
            needed -= 1
    return {**_end_terms(filled), "roster": len(team.roster), "players": _players(filled)}


def side(league: Any) -> dict[str, Any]:
    parts = score_components(league, league.user_team_id)
    team = league.user_team
    return {
        "winning": sum(parts[f"{name}_contribution"] for name in WINNING),
        "penalty": float(parts["protocol_penalty"]),
        "v2": sum(v for k, v in parts.items() if k.endswith("_contribution")) - float(parts["protocol_penalty"]),
        "end": _end_terms(league),
        "probe": league.probe,
        # The next draft's picks: score-v2 counts picks from the season after it.
        "next_draft_picks": len(team.draft_picks.get(league.season, [])),
        "next_draft_pick_value": pick_value(league.season, league.season),
        "roster": len(team.roster),
        "extensions_final_season": sum(
            1
            for t in league.transactions
            if t.team_id == league.user_team_id
            and t.accepted
            and t.action.get("type") == "extend_contract"
            and t.season == SEASONS
        ),
        "players": _players(league),
        "refill": {"autopilot": _refill_autopilot(league), **{m: _refill(league, m) for m in MANAGERS}},
        "fill": {str(target): _fill(league, target) for target in FILL_TARGETS},
        "future": {manager: _future(league, manager) for manager in JUDGES},
    }


def play(name: str, seed: int, cls: type = ProbeLeague) -> Any:
    league = cls.new(seed=seed)
    agent = make_agent(name)
    for index in range(len(ceiling_search.STEPS)):
        ceiling_search.play_step(league, agent, index)
    return league


def _scripted_job(job: tuple[str, int]) -> dict[str, Any]:
    name, seed = job
    return {"group": name, "seed": seed, **side(play(name, seed))}


def _ledger_job(job: tuple[str, str]) -> dict[str, Any] | None:
    label, ledger_path = job
    ledger = Path(ledger_path)
    if ledger_benchmark_version(ledger) != "gm-bench-2.1":
        raise SystemExit(f"{ledger}: not a 2.1 ledger")
    records = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
    records, _marked = replayable_ledger(records)
    with tempfile.TemporaryDirectory() as directory:
        clean = Path(directory) / "ledger.jsonl"
        clean.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
        episode = ProbeEpisode.from_ledger(clean, reopen=False)
    if not episode.done:
        return None
    if episode.seasons != SEASONS:
        raise SystemExit(f"{ledger.parent.name} of {label}: {episode.seasons} seasons, expected {SEASONS}")
    # The replay must be the game that was played: same score as the recorded result.
    recorded = json.loads((ledger.parent / "result.json").read_text(encoding="utf-8"))["final_score"]
    if abs(episode.result()["final_score"] - recorded) > 1e-6:
        raise SystemExit(f"{ledger.parent.name} of {label}: replay does not reproduce the recorded score")
    seed = int(records[0]["seed"])
    return {"group": label, "seed": seed, **side(episode.league), "reference": side(play(REFERENCE, seed))}


def write_private(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # A new 0600 file, then a rename: nobody holding the old file open sees the new contents.
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    os.replace(temporary, path)


def run_sides(seeds: list[int], run_dirs: list[Path], jobs: int, cache: Path) -> None:
    with ProcessPoolExecutor(max_workers=max(1, jobs)) as pool:
        work = [(name, seed) for name in SCRIPTED for seed in seeds]
        scripted = list(pool.map(_scripted_job, work, chunksize=2))
        write_private(cache / "scripted.json", scripted)
        print(f"scripted: {len(scripted)} final leagues", file=sys.stderr)
        for run_dir in run_dirs:
            run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            label = str(run.get("model") or run_dir.name).removesuffix("-v21").removesuffix("-panel-32x5")
            ledgers = sorted(run_dir.glob("episode-*/ledger.jsonl"))
            rows = [r for r in pool.map(_ledger_job, [(label, str(p)) for p in ledgers], chunksize=2) if r]
            write_private(cache / "models" / f"{run_dir.name}.json", rows)
            print(f"{label}: {len(rows)} of {len(ledgers)} episodes", file=sys.stderr)


def selfcheck(seeds: list[int]) -> None:
    """The probe changes nothing: same final score as a plain ``League21``."""
    for name in ("pick-trader", "contend-1g"):
        for seed in seeds:
            probed, plain = play(name, seed), play(name, seed, League21)
            a = score_components(probed, 0)
            b = score_components(plain, 0)
            if a != b:
                raise SystemExit(f"probe changed the game: {name} seed {seed}")
    print(f"selfcheck ok on seeds {seeds}")


# --------------------------------------------------------------------------
# Candidates
# --------------------------------------------------------------------------


def _roster_points(terms: dict[str, float]) -> float:
    return (
        terms["total_assets"] * SCALE.total_asset
        + terms["young_assets"] * SCALE.young_asset
        + terms["current_strength"] * SCALE.current_strength
        + terms["roster_depth"] * SCALE.roster_depth
    )


def _cap_points(cap_room: float) -> float:
    return max(SCALE.cap_score_min, min(SCALE.cap_score_max, cap_room * SCALE.cap_room))


def _pick_points(record: dict[str, Any]) -> float:
    return record["end"]["future_pick_assets"] * SCALE.future_pick_asset


def _next_pick_points(record: dict[str, Any]) -> float:
    return record["next_draft_picks"] * record["next_draft_pick_value"] * SCALE.future_pick_asset


def _continuation(record: dict[str, Any], manager: str, horizon: int) -> float:
    return sum(record["future"][manager][:horizon]) * EXTRA_SEASONS / horizon


CANDIDATES: dict[str, Any] = {
    # score-v2: the roster after the final rollover.
    "v2": lambda r: r["end"]["end_state"],
    # v2, also counting the next draft's picks, which score-v2 leaves out.
    "v2+next-pick": lambda r: r["end"]["end_state"] + _next_pick_points(r),
    # The roster as it stood when the last game was played, before contracts expired.
    "pre-expiry": lambda r: (
        _roster_points(r["probe"]["pre"])
        + _cap_points(r["probe"]["pre"]["cap_room"])
        + _pick_points(r)
        + _next_pick_points(r)
    ),
    # A scripted manager runs the next preseason first, then score-v2's terms.
    "refill:pick-trader": lambda r: r["refill"]["pick-trader"]["end_state"] + _next_pick_points(r),
    "refill:strategic": lambda r: r["refill"]["strategic"]["end_state"] + _next_pick_points(r),
    # The engine's own opponent signing routine fills the roster first.
    "refill:autopilot": lambda r: r["refill"]["autopilot"]["end_state"] + _next_pick_points(r),
    # The winning that follows under a scripted manager, scaled to five seasons.
    **{
        f"continue-{horizon}:{manager}": (lambda r, m=manager, h=horizon: _continuation(r, m, h))
        for manager in ("pick-trader", "strategic")
        for horizon in (1, 2, 3)
    },
    "refill:contend-1g": lambda r: r["refill"]["contend-1g"]["end_state"] + _next_pick_points(r),
}


def _term_weighted(state: dict[str, Any], record: dict[str, Any], kept: float) -> float:
    """``state``'s end-state points with a one-year contract's asset value counted at ``kept``.

    A player with one season left is gone before a second later season, so
    his asset value is discounted: the simplest contract-aware term.
    """
    lost_total = sum(value * (1.0 - kept) for value, _age, years in state["players"] if years <= 1)
    lost_young = sum(value * (1.0 - kept) for value, age, years in state["players"] if years <= 1 and age <= 24)
    return (
        state["end_state"] - lost_total * SCALE.total_asset - lost_young * SCALE.young_asset + _next_pick_points(record)
    )


# Round 2: the engine fills the roster to a given size, then score-v2's terms.
for _target in FILL_TARGETS:
    CANDIDATES[f"fill-{_target}"] = lambda r, t=str(_target): r["fill"][t]["end_state"] + _next_pick_points(r)
# Round 2: score-v2 plus the next draft's picks, a one-year contract counted at a fraction.
ONE_YEAR_KEPT = (0.9, 0.8, 0.7, 0.6, 0.5, 0.4)
for _kept in ONE_YEAR_KEPT:
    CANDIDATES[f"one-year@{_kept}"] = lambda r, k=_kept: _term_weighted({**r["end"], "players": r["players"]}, r, k)
for _target in (12, 16):
    CANDIDATES[f"fill-{_target}, one-year@0.5"] = lambda r, t=str(_target): _term_weighted(r["fill"][t], r, 0.5)

# Raw features a refit candidate weights (gap to pick-trader on the same seed).
REFIT_FEATURES = {
    "total_assets": lambda r: r["end"]["total_assets"],
    "young_assets": lambda r: r["end"]["young_assets"],
    "future_pick_assets": lambda r: r["end"]["future_pick_assets"],
    "next_draft_pick_assets": lambda r: r["next_draft_picks"] * r["next_draft_pick_value"],
    "cap_room": lambda r: r["end"]["cap_room"],
    "current_strength": lambda r: r["end"]["current_strength"],
    "roster_depth": lambda r: r["end"]["roster_depth"],
    "expired_assets": lambda r: r["probe"]["expired_assets"],
}


def least_squares(rows: list[list[float]], target: list[float]) -> list[float]:
    size = len(rows[0])
    gram = [[sum(row[i] * row[j] for row in rows) for j in range(size)] for i in range(size)]
    rhs = [sum(row[i] * y for row, y in zip(rows, target)) for i in range(size)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda r: abs(gram[r][column]))
        gram[column], gram[pivot] = gram[pivot], gram[column]
        rhs[column], rhs[pivot] = rhs[pivot], rhs[column]
        for row in range(column + 1, size):
            factor = gram[row][column] / gram[column][column]
            rhs[row] -= factor * rhs[column]
            for k in range(column, size):
                gram[row][k] -= factor * gram[column][k]
    solution = [0.0] * size
    for row in range(size - 1, -1, -1):
        rest = sum(gram[row][k] * solution[k] for k in range(row + 1, size))
        solution[row] = (rhs[row] - rest) / gram[row][row]
    return solution


def yardstick(record: dict[str, Any], managers: tuple[str, ...] = MANAGERS) -> float:
    return statistics.fmean(sum(record["future"][m]) for m in managers)


def mean_se(values: list[float]) -> dict[str, float]:
    se = statistics.stdev(values) / len(values) ** 0.5 if len(values) > 1 else 0.0
    return {"mean": round(statistics.fmean(values), 2), "se": round(se, 2), "n": len(values)}


def pairs(records: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """(side, pick-trader's side on the same seed) for every non-reference record."""
    reference = {r["seed"]: r for r in records if r["group"] == REFERENCE}
    out = []
    for record in records:
        if "reference" in record:
            out.append((record, record["reference"]))
        elif record["group"] != REFERENCE and record["seed"] in reference:
            out.append((record, reference[record["seed"]]))
    return out


def evaluate(
    pairs_: list[tuple[dict[str, Any], dict[str, Any]]], end: Any, judged_by: tuple[str, ...] = MANAGERS
) -> dict[str, Any]:
    """How well a candidate's end-state gap predicts the winning that follows."""
    groups: dict[str, dict[str, list[float]]] = {}
    for record, reference in pairs_:
        bucket = groups.setdefault(record["group"], {"end": [], "future": [], "lift": []})
        end_gap = end(record) - end(reference)
        bucket["end"].append(end_gap)
        bucket["future"].append(yardstick(record, judged_by) - yardstick(reference, judged_by))
        bucket["lift"].append(
            (record["winning"] - record["penalty"]) - (reference["winning"] - reference["penalty"]) + end_gap
        )
    all_end = [v for g in groups.values() for v in g["end"]]
    all_future = [v for g in groups.values() for v in g["future"]]
    intercept, slope = least_squares([[1.0, e] for e in all_end], all_future)
    rows = {}
    for name, g in groups.items():
        residual = [f - e for e, f in zip(g["end"], g["future"])]
        rows[name] = {
            "end_gap": mean_se(g["end"]),
            "future_gap": mean_se(g["future"]),
            "residual": mean_se(residual),
            "lift": mean_se(g["lift"]),
            "lift_paired_sd": round(statistics.stdev(g["lift"]), 2) if len(g["lift"]) > 1 else 0.0,
        }
    residual_means = [row["residual"]["mean"] for row in rows.values()]
    return {
        "judged_by": list(judged_by),
        "slope": round(slope, 3),
        "intercept": round(intercept, 2),
        "group_residual_rms": round((sum(v * v for v in residual_means) / len(residual_means)) ** 0.5, 2),
        "group_residual_max_abs": round(max(abs(v) for v in residual_means), 2),
        "mean_lift_paired_sd": round(statistics.fmean(row["lift_paired_sd"] for row in rows.values()), 2),
        "groups": rows,
    }


def kendall_tau(a: list[float], b: list[float]) -> float:
    concordant = sum(
        ((a[i] > a[j]) - (a[i] < a[j])) * ((b[i] > b[j]) - (b[i] < b[j]))
        for i in range(len(a))
        for j in range(i + 1, len(a))
    )
    return round(concordant / (len(a) * (len(a) - 1) / 2), 3)


def _judges(name: str) -> tuple[str, ...]:
    """A continuation candidate is judged by the other manager's seasons, never its own."""
    if name.startswith("continue-"):
        own = name.split(":", 1)[1]
        return tuple(m for m in MANAGERS if m != own)
    return MANAGERS


def run_report(cache: Path) -> dict[str, Any]:
    scripted = json.loads((cache / "scripted.json").read_text(encoding="utf-8"))
    fit = pairs([r for r in scripted if r["seed"] in FIT_SEEDS])
    check = pairs([r for r in scripted if r["seed"] in CHECK_SEEDS])
    models = []
    for path in sorted((cache / "models").glob("*.json")):
        models.extend(pairs(json.loads(path.read_text(encoding="utf-8"))))

    # The refit candidate: weights fitted on the fit seeds only, no intercept
    # (pick-trader's gap to itself is zero by construction).
    names = list(REFIT_FEATURES)
    design = [[REFIT_FEATURES[n](rec) - REFIT_FEATURES[n](ref) for n in names] for rec, ref in fit]
    weights = least_squares(design, [yardstick(rec) - yardstick(ref) for rec, ref in fit])
    candidates = dict(CANDIDATES)
    candidates["refit"] = lambda r: sum(w * REFIT_FEATURES[n](r) for n, w in zip(names, weights))

    report: dict[str, Any] = {
        "yardstick": (
            f"score-v2 winning value over the next {EXTRA_SEASONS} seasons, mean of three scripted managers "
            f"({', '.join(MANAGERS)}), as a gap to pick-trader's final league on the same seed and dice"
        ),
        "fit_seeds": [FIT_SEEDS[0], FIT_SEEDS[-1]],
        "check_seeds": [CHECK_SEEDS[0], CHECK_SEEDS[-1]],
        "scripted_policies": [name for name in SCRIPTED if name != REFERENCE],
        "refit_weights": {n: round(w, 4) for n, w in zip(names, weights)},
        "score_v2_weights": {
            "total_assets": SCALE.total_asset,
            "young_assets": SCALE.young_asset,
            "future_pick_assets": SCALE.future_pick_asset,
            "cap_room": SCALE.cap_room,
            "current_strength": SCALE.current_strength,
            "roster_depth": SCALE.roster_depth,
        },
        "candidates": {},
    }
    v2_model_lifts: list[float] = []
    for name, end in candidates.items():
        block: dict[str, Any] = {
            "fit": evaluate(fit, end, _judges(name)),
            "check": evaluate(check, end, _judges(name)),
        }
        samples = {"check": check, **({"models": models} if models else {})}
        block["by_judge"] = {
            label: {
                manager: {
                    key: value
                    for key, value in evaluate(sample, end, (manager,)).items()
                    if key in ("slope", "intercept", "group_residual_rms", "group_residual_max_abs")
                }
                for manager in JUDGES
                if manager in (*_judges(name), *EXTRA_JUDGES)
            }
            for label, sample in samples.items()
        }
        if models:
            block["models"] = evaluate(models, end, _judges(name))
            lifts = [row["lift"]["mean"] for row in block["models"]["groups"].values()]
            if name == "v2":
                v2_model_lifts = lifts
            block["models"]["kendall_tau_vs_v2"] = kendall_tau(v2_model_lifts, lifts)
        report["candidates"][name] = block
    # The one-parameter candidate, chosen on the fit seeds only: slope nearest one.
    report["one_year_kept_chosen_on_fit"] = min(
        ONE_YEAR_KEPT, key=lambda k: abs(report["candidates"][f"one-year@{k}"]["fit"]["slope"] - 1.0)
    )
    # What the players left behind look like, per group (context for the residuals).
    report["end_of_run"] = {
        label: {
            group: {
                "roster": mean_se([float(r["roster"]) for r, _ in sample if r["group"] == group]),
                "expired_players": mean_se(
                    [float(r["probe"]["expired_count"]) for r, _ in sample if r["group"] == group]
                ),
                "extensions_final_season": mean_se(
                    [float(r["extensions_final_season"]) for r, _ in sample if r["group"] == group]
                ),
                **{
                    f"roster_after_refill_{how}": mean_se(
                        [float(r["refill"][how]["roster"]) for r, _ in sample if r["group"] == group]
                    )
                    for how in ("pick-trader", "autopilot")
                },
            }
            for group in sorted({r["group"] for r, _ in sample})
        }
        for label, sample in (("check", check), ("models", models))
        if sample
    }
    return report


def print_report(report: dict[str, Any]) -> None:
    _print_summary(report)
    chosen = f"one-year@{report['one_year_kept_chosen_on_fit']}"
    shown = ("v2", "v2+next-pick", "refill:pick-trader", chosen)
    if "models" not in report["candidates"]["v2"]:
        return
    print(f"\n{'model row lift vs pick-trader':40s}" + "".join(f"{name:>22s}" for name in shown))
    for group in report["candidates"]["v2"]["models"]["groups"]:
        cells = "".join(
            f"{report['candidates'][name]['models']['groups'][group]['lift']['mean']:>+22.1f}" for name in shown
        )
        print(f"{group:40s}{cells}")
    taus = "".join(f"{report['candidates'][name]['models']['kendall_tau_vs_v2']:>22.3f}" for name in shown)
    print(f"{'Kendall tau vs v2':40s}{taus}")
    print("\njudged by one manager at a time (slope / residual rms over groups)")
    for name in ("v2", "v2+next-pick", "refill:pick-trader", "fill-8", chosen):
        for label, judges in report["candidates"][name]["by_judge"].items():
            cells = "  ".join(f"{m}: {b['slope']:.2f} / {b['group_residual_rms']:.1f}" for m, b in judges.items())
            print(f"  {name:20s} {label:7s} {cells}")


def _print_summary(report: dict[str, Any]) -> None:
    samples = [s for s in ("fit", "check", "models") if s in next(iter(report["candidates"].values()))]
    print(f"{'candidate':24s}" + "".join(f"  {s:>31s}" for s in samples))
    print(f"{'':24s}" + "  slope  rms  max|res|  liftSD" * len(samples))
    for name, block in report["candidates"].items():
        line = f"{name:24s}"
        for sample in samples:
            b = block[sample]
            line += (
                f"  {b['slope']:5.2f} {b['group_residual_rms']:5.1f} {b['group_residual_max_abs']:7.1f} "
                f"{b['mean_lift_paired_sd']:7.1f}"
            )
        print(line)


def parse_seeds(text: str) -> list[int]:
    low, _, high = text.partition("-")
    return list(range(int(low), int(high or low) + 1))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    sides = commands.add_parser("sides", help="play and replay; write the feature cache")
    sides.add_argument(
        "run_dirs", nargs="*", type=Path, help="2.1 raw run directories (private; cached, never printed)"
    )
    sides.add_argument("--seeds", default=f"{FIT_SEEDS[0]}-{CHECK_SEEDS[-1]}")
    sides.add_argument("--jobs", type=int, default=12)
    report = commands.add_parser("report", help="compare the candidates from the cache")
    report.add_argument("--out", type=Path)
    check = commands.add_parser("selfcheck", help="confirm the probe league changes no game")
    check.add_argument("--seeds", default="101-104")
    for command in (sides, report):
        command.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    args = parser.parse_args(argv)
    if args.command == "selfcheck":
        selfcheck(parse_seeds(args.seeds))
    elif args.command == "sides":
        run_sides(parse_seeds(args.seeds), [p.expanduser() for p in args.run_dirs], args.jobs, args.cache)
    else:
        result = run_report(args.cache)
        print_report(result)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
