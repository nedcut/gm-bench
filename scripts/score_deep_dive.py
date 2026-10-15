"""Stress-test the score-v2 proposal before it is pre-registered. No model calls.

Builds on ``scripts/score_v2.py`` (candidate ``C``, the proposal) and
``scripts/ceiling_search.py``. Every score here is assembled from a raw term
vector so the same episode can be rescored under other weights. Five
subcommands:

``panels``  replays raw 2.0 panel run directories and reports, per row, where
    the lift against ``pick-trader`` comes from (term by term) and how the
    row-level conclusions move when each weight is halved or raised by half.
    Per-episode term vectors are cached outside the repository
    (``--cache``, private seeds); only aggregates are printed or written.
``noise``  splits the paired spread between scripted policies into future
    dice (same initial league, redrawn dice) and the world itself.
``exploit``  points the fair planner at a candidate score and reports what it
    changes relative to ``pick-trader``, season by season, so a gain that
    comes from gaming a term rather than from winning shows up.
``continuation``  hands each final league (published rows and scripted
    policies) to ``pick-trader`` for five more seasons on the same dice and
    asks whether the end-state terms predict the winning value that follows,
    which is what they stand in for.
``reset``  prototypes the records fix (``docs/bench_v2_1_queue.md`` item 15)
    as a hook, plays the references and canaries under it and repeats the
    contract checks.

    python scripts/score_deep_dive.py panels ~/gmb-runs/<run> ... --out deep_panels.json
    python scripts/score_deep_dive.py noise --seeds 11-34 --draws 4
    python scripts/score_deep_dive.py exploit --seeds 101-124 --objective C
    python scripts/score_deep_dive.py reset --seeds 11-34
    python scripts/score_deep_dive.py continuation ~/gmb-runs/<run> ... --seeds 11-34
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from itertools import combinations
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "scripts"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import ceiling_search  # noqa: E402
import score_v2  # noqa: E402

from gm_bench.agentic.validate import _replay  # noqa: E402
from gm_bench.agents import AGENTS  # noqa: E402
from gm_bench.runner import _sign_flip_p_value  # noqa: E402
from gm_bench.scoring import ACTIVE_SCORE_SCALE, score_components, score_team  # noqa: E402
from gm_bench.simulator import League  # noqa: E402
from gm_bench.validity import CANARY_AGENTS  # noqa: E402

RECENT = score_v2.RECENT_SEASONS
SCALE = ACTIVE_SCORE_SCALE
# Raw terms of a score-v2 candidate, in report order. `all_wins` is unused by
# C (weight 0) and is E's replacement for `recent_wins`.
TERMS = (
    "recent_wins",
    "all_wins",
    "playoff_rounds",
    "championships",
    "total_assets",
    "young_assets",
    "future_pick_assets",
    "cap_room",
    "current_strength",
    "roster_depth",
)
WINNING_TERMS = ("recent_wins", "all_wins", "playoff_rounds", "championships")
# E's weight on every season's own wins: C's 1.67 times pick-trader's mean
# recent-to-all wins ratio on the canary seeds 11-34 (`reset` and `noise`
# print it), so pick-trader's mean contribution from wins is unchanged.
ALL_SEASON_WIN = 1.02
WEIGHTS: dict[str, dict[str, float]] = {
    "C": {
        "recent_wins": score_v2.PER_SEASON_RECENT_WIN,
        "all_wins": 0.0,
        "playoff_rounds": SCALE.playoff_round,
        "championships": SCALE.championship,
        "total_assets": SCALE.total_asset,
        "young_assets": SCALE.young_asset,
        "future_pick_assets": SCALE.future_pick_asset,
        "cap_room": SCALE.cap_room,
        "current_strength": SCALE.current_strength,
        "roster_depth": SCALE.roster_depth,
    },
}
WEIGHTS["E"] = {**WEIGHTS["C"], "recent_wins": 0.0, "all_wins": ALL_SEASON_WIN}
CANDIDATES = ("v1", "C", "D", "E")


# --------------------------------------------------------------------------
# Raw term vectors and scores
# --------------------------------------------------------------------------


def install_records_reset() -> None:
    """Zero every team's record when a season starts (queue item 15).

    The midseason leg opens every season, so resetting before it gives each
    season its own record. The lottery and the offseason market still see
    the previous season's full record, which is what they are meant to read.
    """
    if getattr(League, "_records_reset_hooked", False):
        return
    partial = League.simulate_partial_season

    def reset_then_play(self, fraction):
        for team in self.teams.values():
            team.wins = 0
            team.losses = 0
        self.records_reset = True
        return partial(self, fraction)

    League.simulate_partial_season = reset_then_play
    League._records_reset_hooked = True
    League._records_reset_original = partial


def uninstall_records_reset() -> None:
    """Undo ``install_records_reset`` (worker processes never need to)."""
    if getattr(League, "_records_reset_hooked", False):
        League.simulate_partial_season = League._records_reset_original
        League._records_reset_hooked = False


def season_wins(league: League) -> list[int]:
    if getattr(league, "records_reset", False):
        return [summary.wins for summary in league.summaries]
    return score_v2.per_season_wins(league)


def raw_terms(league: League) -> dict[str, float]:
    """Every quantity a candidate score weights, for the user team."""
    components = score_components(league, league.user_team_id)
    wins = season_wins(league)
    recent = league.summaries[-RECENT:]
    expected_playoffs: dict[int, tuple[float, float]] = league.expected_playoffs
    expected_wins: dict[int, float] = getattr(league, "expected_wins", {})
    return {
        "recent_wins": float(sum(wins[-RECENT:])),
        "all_wins": float(sum(wins)),
        "playoff_rounds": sum(expected_playoffs[s.season][0] for s in recent),
        "championships": sum(title for _rounds, title in expected_playoffs.values()),
        **{name: float(components[name]) for name in TERMS[4:]},
        "protocol_penalty": float(components["protocol_penalty"]),
        "expected_recent_wins": sum(expected_wins.get(s.season, 0.0) for s in recent),
        "season_wins": wins,
        "v1": score_team(league, league.user_team_id),
    }


def contributions(raw: dict[str, Any], weights: dict[str, float]) -> dict[str, float]:
    out = {name: raw[name] * weights[name] for name in TERMS}
    out["cap_room"] = max(SCALE.cap_score_min, min(SCALE.cap_score_max, out["cap_room"]))
    out["protocol_penalty"] = -raw["protocol_penalty"]
    return out


def score(raw: dict[str, Any], candidate: str | dict[str, float]) -> float:
    if candidate == "v1":
        return raw["v1"]
    if candidate == "D":
        return score(raw, "C") + (raw["expected_recent_wins"] - raw["recent_wins"]) * WEIGHTS["C"]["recent_wins"]
    weights = WEIGHTS[candidate] if isinstance(candidate, str) else candidate
    return sum(contributions(raw, weights).values())


def _init_worker(reset: bool) -> None:
    score_v2.install_hooks()
    if reset:
        install_records_reset()


def _pool(jobs: int, reset: bool = False) -> ProcessPoolExecutor:
    return ProcessPoolExecutor(max_workers=max(1, jobs), initializer=_init_worker, initargs=(reset,))


def play(name: str, seed: int, dice: int = 0) -> League:
    """Play a scripted policy; ``dice`` > 0 keeps the initial league and redraws every later draw."""
    league = League.new(seed=seed)
    if dice:
        league.seed = seed + 1_000_003 * dice
    agent = score_v2._agent_factory(name)()
    for index in range(len(ceiling_search.STEPS)):
        ceiling_search.play_step(league, agent, index)
    return league


def mean_se(values: list[float]) -> dict[str, float]:
    se = statistics.stdev(values) / math.sqrt(len(values)) if len(values) > 1 else 0.0
    return {"mean": round(statistics.mean(values), 3), "se": round(se, 3)}


def holm(p_values: list[float], alpha: float = 0.05) -> list[bool]:
    order = sorted(range(len(p_values)), key=lambda i: p_values[i])
    rejected = [False] * len(p_values)
    for rank, index in enumerate(order):
        if p_values[index] > alpha / (len(p_values) - rank):
            break
        rejected[index] = True
    return rejected


def kendall_tau(a: list[float], b: list[float]) -> float:
    pairs = list(combinations(range(len(a)), 2))
    agree = sum(1 if (a[i] - a[j]) * (b[i] - b[j]) > 0 else -1 for i, j in pairs)
    return agree / len(pairs)


# --------------------------------------------------------------------------
# panels: term decomposition and weight robustness
# --------------------------------------------------------------------------


def _panel_job(ledger: Path) -> dict[str, Any]:
    episode, _marked = _replay(ledger)
    seed = int(json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])["seed"])
    # Every episode must carry its recorded score, or the replay check would
    # silently cover fewer episodes than it reports.
    recorded = json.loads((ledger.parent / "result.json").read_text(encoding="utf-8"))["final_score"]
    model = raw_terms(episode.league)
    # Guard the term vector against the score it claims to rebuild.
    expected_c = score_v2.variant_scores(episode.league)["C"]
    if abs(score(model, "C") - expected_c) > 1e-6:
        raise AssertionError(f"{ledger}: term vector gives {score(model, 'C')}, variant C {expected_c}")
    return {"model": model, "reference": raw_terms(play("pick-trader", seed)), "recorded": recorded}


def run_ledgers(run_dir: Path) -> list[Path]:
    ledgers = sorted(run_dir.glob("episode-*/ledger.jsonl"))
    if not ledgers:
        raise SystemExit(f"{run_dir}: no episode-*/ledger.jsonl")
    return ledgers


def cache_file(cache: Path, run_dir: Path, ledgers: list[Path], kind: str) -> Path:
    """Key a cache entry by the run's resolved path and every ledger's size and mtime.

    Two runs with the same directory name, or a run whose ledgers changed,
    must not share an entry.
    """
    digest = hashlib.sha256(str(run_dir.resolve()).encode())
    for ledger in ledgers:
        stat = ledger.stat()
        digest.update(f"{ledger.relative_to(run_dir)}:{stat.st_size}:{stat.st_mtime_ns}".encode())
    return cache / f"{run_dir.name}.{kind}.{digest.hexdigest()[:16]}.json"


def write_private(path: Path, payload: Any) -> None:
    # Per-episode vectors derive from private seeds: owner-only directory and file.
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    os.chmod(path, 0o600)


def load_panel(run_dir: Path, jobs: int, cache: Path) -> dict[str, Any]:
    ledgers = run_ledgers(run_dir)
    cached = cache_file(cache, run_dir, ledgers, "panel")
    if cached.exists():
        return json.loads(cached.read_text(encoding="utf-8"))
    with _pool(jobs) as pool:
        rows = list(pool.map(_panel_job, ledgers))
    mismatches = sum(1 for row in rows if abs(row["recorded"] - round(row["model"]["v1"], 3)) > 1e-6)
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    panel = {"run": run_dir.name, "agent": run.get("agent"), "replay_mismatches": mismatches, "episodes": rows}
    write_private(cached, panel)
    return panel


def lifts(panel: dict[str, Any], candidate: str | dict[str, float]) -> list[float]:
    return [score(row["model"], candidate) - score(row["reference"], candidate) for row in panel["episodes"]]


def row_summary(panels: list[dict[str, Any]], candidate: str | dict[str, float]) -> dict[str, Any]:
    per_row = [lifts(panel, candidate) for panel in panels]
    means = [statistics.mean(values) for values in per_row]
    p_values = [_sign_flip_p_value(values) for values in per_row]
    return {"means": means, "p": p_values, "separable": holm(p_values)}


def decompose(panel: dict[str, Any]) -> dict[str, Any]:
    terms: dict[str, list[float]] = {}
    for row in panel["episodes"]:
        model, reference = contributions(row["model"], WEIGHTS["C"]), contributions(row["reference"], WEIGHTS["C"])
        for name in model:
            terms.setdefault(name, []).append(model[name] - reference[name])
    per_term = {name: mean_se(values) for name, values in terms.items() if name != "all_wins"}
    winning = [sum(terms[name][i] for name in WINNING_TERMS) for i in range(len(panel["episodes"]))]
    end_state = [
        sum(terms[name][i] for name in TERMS if name not in WINNING_TERMS) for i in range(len(panel["episodes"]))
    ]
    season_gap = [
        mean_se([row["model"]["season_wins"][s] - row["reference"]["season_wins"][s] for row in panel["episodes"]])
        for s in range(len(panel["episodes"][0]["model"]["season_wins"]))
    ]
    return {
        "terms": per_term,
        "winning": mean_se(winning),
        "end_state": mean_se(end_state),
        "season_win_gap": season_gap,
    }


def run_panels(run_dirs: list[Path], jobs: int, cache: Path) -> dict[str, Any]:
    panels = []
    for run_dir in run_dirs:
        panel = load_panel(run_dir, jobs, cache)
        if panel["replay_mismatches"]:
            raise SystemExit(f"{run_dir}: {panel['replay_mismatches']} replay mismatches")
        panels.append(panel)
        print(f"loaded {panel['run']} ({len(panel['episodes'])} episodes)", flush=True)

    # Run directory names: two rows can share an agent (one model on two harness versions).
    names = [panel["run"] for panel in panels]
    base = row_summary(panels, "C")
    robustness = []
    for term in TERMS:
        if WEIGHTS["C"][term] == 0.0:
            continue
        for factor in (0.5, 1.5):
            weights = {**WEIGHTS["C"], term: WEIGHTS["C"][term] * factor}
            summary = row_summary(panels, weights)
            robustness.append(
                {
                    "term": term,
                    "factor": factor,
                    "sign_flips": [
                        names[i] for i, (a, b) in enumerate(zip(base["means"], summary["means"])) if (a > 0) != (b > 0)
                    ],
                    "separability_changes": [
                        names[i] for i, (a, b) in enumerate(zip(base["separable"], summary["separable"])) if a != b
                    ],
                    "separable": sum(summary["separable"]),
                    "kendall_tau": round(kendall_tau(base["means"], summary["means"]), 3),
                    "max_lift_shift": round(max(abs(a - b) for a, b in zip(base["means"], summary["means"])), 2),
                }
            )
    candidates = {}
    for candidate in CANDIDATES:
        summary = row_summary(panels, candidate)
        mdes = [score_v2.paired(lifts(panel, candidate))["mde80"] for panel in panels]
        candidates[candidate] = {
            "separable": sum(summary["separable"]),
            "mean_mde80": round(statistics.mean(mdes), 2),
            "kendall_tau_vs_C": round(kendall_tau(base["means"], summary["means"]), 3),
            "lifts": {name: round(mean, 2) for name, mean in zip(names, summary["means"])},
        }
    return {
        "rows": [{"agent": name, **decompose(panel)} for name, panel in zip(names, panels)],
        "base_separable": sum(base["separable"]),
        "robustness": robustness,
        "candidates": candidates,
    }


def print_panels(report: dict[str, Any]) -> None:
    print("\nLift vs pick-trader under C, by term (mean):")
    for row in report["rows"]:
        terms = row["terms"]
        print(
            f"  {row['agent'][:40]:40s} winning {row['winning']['mean']:+7.1f}  end-state {row['end_state']['mean']:+7.1f}"
            + "  ".join(f" {name[:10]} {terms[name]['mean']:+6.1f}" for name in terms)
        )
        print("    season win gap: " + " ".join(f"{s['mean']:+.1f}" for s in row["season_win_gap"]))
    print(f"\nWeight robustness (C separable rows: {report['base_separable']}):")
    for row in report["robustness"]:
        print(
            f"  {row['term']:18s} x{row['factor']}: tau {row['kendall_tau']:+.3f}  separable {row['separable']}"
            f"  max shift {row['max_lift_shift']:5.1f}  sign flips {row['sign_flips'] or '-'}"
            f"  separability changes {row['separability_changes'] or '-'}"
        )
    print("\nCandidates:")
    for name, block in report["candidates"].items():
        print(
            f"  {name}: separable {block['separable']}  mean MDE {block['mean_mde80']}  tau vs C {block['kendall_tau_vs_C']}"
        )


# --------------------------------------------------------------------------
# noise: future dice versus the world
# --------------------------------------------------------------------------

NOISE_POLICIES = ("value", "shrewd", "strategic")


def _noise_job(job: tuple[str, int, int]) -> dict[str, Any]:
    name, seed, dice = job
    return raw_terms(play(name, seed, dice))


def run_noise(seeds: list[int], draws: int, jobs: int) -> dict[str, Any]:
    names = ("pick-trader", *NOISE_POLICIES)
    work = [(name, seed, dice) for name in names for seed in seeds for dice in range(draws + 1)]
    with _pool(jobs) as pool:
        flat = dict(zip(work, pool.map(_noise_job, work)))
    pt = [flat[("pick-trader", seed, 0)] for seed in seeds]
    ratio = statistics.mean(r["recent_wins"] for r in pt) / statistics.mean(r["all_wins"] for r in pt)
    report: dict[str, Any] = {
        "seeds": [seeds[0], seeds[-1]],
        "draws": draws,
        "recent_to_all_wins_ratio": round(ratio, 4),
        "pairs": {},
    }
    for name in NOISE_POLICIES:
        block = {}
        for candidate in CANDIDATES:
            # d[seed][dice]: paired difference against pick-trader with the same dice.
            diffs = [
                [
                    score(flat[(name, seed, dice)], candidate) - score(flat[("pick-trader", seed, dice)], candidate)
                    for dice in range(draws + 1)
                ]
                for seed in seeds
            ]
            within = statistics.mean(statistics.variance(row) for row in diffs)
            total = statistics.variance([row[0] for row in diffs])
            block[candidate] = {
                "paired_sd": round(math.sqrt(total), 2),
                "dice_sd": round(math.sqrt(within), 2),
                "dice_share": round(within / total, 3) if total else None,
                "mean_gap": round(statistics.mean(statistics.mean(row) for row in diffs), 2),
            }
        report["pairs"][f"{name} - pick-trader"] = block
    return report


def print_noise(report: dict[str, Any]) -> None:
    print(f"pick-trader recent/all wins ratio {report['recent_to_all_wins_ratio']}")
    for pair, block in report["pairs"].items():
        print(pair)
        for candidate, row in block.items():
            print(
                f"  {candidate:3s} paired SD {row['paired_sd']:6.2f}  dice SD {row['dice_sd']:6.2f}"
                f"  dice share {row['dice_share']}  mean gap {row['mean_gap']:+.1f}"
            )


# --------------------------------------------------------------------------
# exploit: let the fair planner optimize a candidate
# --------------------------------------------------------------------------


def _exploit_job(job: tuple[int, str, int]) -> dict[str, Any]:
    seed, objective, worlds = job
    ceiling_search.objective = lambda league, _luck_neutral: score(raw_terms(league), objective)
    started = time.perf_counter()
    found = ceiling_search.fair_search(seed, worlds, 0, generated=True)
    return {
        "seed": seed,
        "planner": raw_terms(found["league"]),
        "reference": raw_terms(play("pick-trader", seed)),
        "path": found["path"],
        "seconds": round(time.perf_counter() - started, 1),
    }


def run_exploit(seeds: list[int], objective: str, worlds: int, jobs: int) -> dict[str, Any]:
    with _pool(jobs) as pool:
        rows = list(pool.map(_exploit_job, [(seed, objective, worlds) for seed in seeds]))
    terms: dict[str, list[float]] = {}
    for row in rows:
        planner, reference = contributions(row["planner"], WEIGHTS["C"]), contributions(row["reference"], WEIGHTS["C"])
        for name in planner:
            terms.setdefault(name, []).append(planner[name] - reference[name])
    n_seasons = len(rows[0]["planner"]["season_wins"])
    return {
        "objective": objective,
        "seeds": [seeds[0], seeds[-1]],
        "worlds": worlds,
        "lift": {
            candidate: score_v2.paired(
                [score(r["planner"], candidate) - score(r["reference"], candidate) for r in rows]
            )
            for candidate in CANDIDATES
        },
        "term_gap_under_C": {name: mean_se(values) for name, values in terms.items() if name != "all_wins"},
        "season_win_gap": [
            mean_se([r["planner"]["season_wins"][s] - r["reference"]["season_wins"][s] for r in rows])
            for s in range(n_seasons)
        ],
        "expected_titles": {
            "planner": round(statistics.mean(r["planner"]["championships"] for r in rows), 3),
            "pick-trader": round(statistics.mean(r["reference"]["championships"] for r in rows), 3),
        },
        "per_seed": [
            {
                "seed": r["seed"],
                "lift": round(score(r["planner"], objective) - score(r["reference"], objective), 3),
                "season_wins": r["planner"]["season_wins"],
                "reference_season_wins": r["reference"]["season_wins"],
                "path": r["path"],
                "seconds": r["seconds"],
            }
            for r in rows
        ],
    }


def print_exploit(report: dict[str, Any]) -> None:
    print(f"fair planner optimizing {report['objective']} (worlds {report['worlds']}):")
    for candidate, stats in report["lift"].items():
        print(f"  lift under {candidate:3s}: {stats['mean']:+6.1f} (se {stats['se']}, ahead {stats['ahead']})")
    print("  term gap under C: " + "  ".join(f"{k} {v['mean']:+.1f}" for k, v in report["term_gap_under_C"].items()))
    print("  season win gap: " + " ".join(f"{s['mean']:+.2f}" for s in report["season_win_gap"]))
    print(f"  expected titles: {report['expected_titles']}")


# --------------------------------------------------------------------------
# reset: the records fix on the references and canaries
# --------------------------------------------------------------------------

REFERENCES = score_v2.REFERENCES


def _reset_job(job: tuple[str, int]) -> dict[str, Any]:
    name, seed = job
    return raw_terms(play(name, seed))


def contract_checks(scores: dict[str, list[dict[str, Any]]], candidate: str) -> dict[str, Any]:
    def contrast(winner: str, loser: str) -> dict[str, Any]:
        return score_v2.paired(
            [score(w, candidate) - score(lo, candidate) for w, lo in zip(scores[winner], scores[loser])]
        )

    asserted = []
    for winner, loser, margin in score_v2.ASSERTED:
        stats = contrast(winner, loser)
        asserted.append(
            {"pair": f"{winner} - {loser}", **stats, "ok": stats["mean"] >= margin and (stats["t"] or 0) >= 2}
        )
    for cls in CANARY_AGENTS:
        stats = contrast("value", cls.name)
        asserted.append(
            {
                "pair": f"value - {cls.name}",
                **stats,
                "ok": stats["mean"] >= score_v2.CANARY_MARGIN and (stats["t"] or 0) >= score_v2.CANARY_T,
            }
        )
    return {
        "means": {name: round(statistics.mean(score(r, candidate) for r in rows), 2) for name, rows in scores.items()},
        "pick_trader_sd": round(statistics.stdev(score(r, candidate) for r in scores["pick-trader"]), 2),
        "all_asserted_ok": all(row["ok"] for row in asserted),
        "asserted": asserted,
        "adjacent": {f"{w} - {lo}": contrast(w, lo) for w, lo in score_v2.ADJACENT},
    }


def run_reset(seeds: list[int], jobs: int) -> dict[str, Any]:
    names = [*REFERENCES, *(cls.name for cls in CANARY_AGENTS)]
    work = [(name, seed) for name in names for seed in seeds]
    report: dict[str, Any] = {"seeds": [seeds[0], seeds[-1]]}
    for label, reset in (("current", False), ("reset", True)):
        with _pool(jobs, reset) as pool:
            flat = list(pool.map(_reset_job, work))
        scores = {name: flat[i * len(seeds) : (i + 1) * len(seeds)] for i, name in enumerate(names)}
        pt = scores["pick-trader"]
        report[label] = {
            "pick_trader_mean_recent_wins": round(statistics.mean(r["recent_wins"] for r in pt), 2),
            "pick_trader_mean_all_wins": round(statistics.mean(r["all_wins"] for r in pt), 2),
            "candidates": {candidate: contract_checks(scores, candidate) for candidate in ("v1", "C", "E")},
        }
    return report


def print_reset(report: dict[str, Any]) -> None:
    for label in ("current", "reset"):
        block = report[label]
        print(
            f"\n== {label} records: pick-trader recent wins {block['pick_trader_mean_recent_wins']},"
            f" all wins {block['pick_trader_mean_all_wins']}"
        )
        for candidate, checks in block["candidates"].items():
            print(
                f" [{candidate}] asserted {'all pass' if checks['all_asserted_ok'] else 'FAIL'}  pick-trader SD {checks['pick_trader_sd']}"
            )
            print("   means: " + "  ".join(f"{k} {v:.1f}" for k, v in checks["means"].items()))
            for row in checks["asserted"]:
                if not row["ok"]:
                    print(f"   FAIL {row['pair']}: {row['mean']:+.1f} (t {row['t']})")
            for pair, row in checks["adjacent"].items():
                print(f"   {pair}: {row['mean']:+.1f} (t {row['t']})")


# --------------------------------------------------------------------------
# continuation: do end-state assets turn into later wins?
# --------------------------------------------------------------------------

# Raw end-state terms whose weights the continuation regression estimates.
END_STATE = ("total_assets", "young_assets", "future_pick_assets", "cap_room", "current_strength", "roster_depth")
EXTRA_SEASONS = 5


def continue_seasons(league: League, manager: str = "pick-trader", seasons: int = EXTRA_SEASONS) -> list[float]:
    """Hand the team to a scripted manager for more seasons; each season's winning value under C.

    Phases are all the step loop reads, and the dice are drawn on a fixed
    schedule, so two leagues on the same seed continue under the same dice.
    No scripted policy reads the episode length.
    """
    agent = AGENTS[manager]()
    start = len(league.summaries)
    for _ in range(seasons):
        for index in range(len(ceiling_search.PHASES)):
            ceiling_search.play_step(league, agent, index)
    wins = season_wins(league)[start:]
    weights = WEIGHTS["C"]
    values = []
    for own, summary in zip(wins, league.summaries[start:]):
        rounds, title = league.expected_playoffs[summary.season]
        values.append(
            own * weights["recent_wins"] + rounds * weights["playoff_rounds"] + title * weights["championships"]
        )
    return values


def _side(league: League, manager: str) -> dict[str, Any]:
    raw = raw_terms(league)
    return {"raw": raw, "future": continue_seasons(league, manager)}


def _continuation_panel_job(job: tuple[Path, str]) -> dict[str, Any]:
    ledger, manager = job
    episode, _marked = _replay(ledger)
    seed = int(json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])["seed"])
    return {"model": _side(episode.league, manager), "reference": _side(play("pick-trader", seed), manager)}


def _continuation_scripted_job(job: tuple[str, int, str]) -> dict[str, Any]:
    name, seed, manager = job
    return {"model": _side(play(name, seed), manager), "reference": _side(play("pick-trader", seed), manager)}


def load_continuation(run_dir: Path, manager: str, jobs: int, cache: Path) -> list[dict[str, Any]]:
    ledgers = run_ledgers(run_dir)
    cached = cache_file(cache, run_dir, ledgers, f"continuation-{manager}")
    if cached.exists():
        return json.loads(cached.read_text(encoding="utf-8"))
    with _pool(jobs) as pool:
        rows = list(pool.map(_continuation_panel_job, [(ledger, manager) for ledger in ledgers]))
    write_private(cached, rows)
    return rows


def end_state_value(raw: dict[str, Any]) -> float:
    parts = contributions(raw, WEIGHTS["C"])
    return sum(parts[name] for name in END_STATE)


def least_squares(rows: list[list[float]], target: list[float]) -> list[float]:
    """Ordinary least squares by the normal equations (a handful of columns)."""
    k = len(rows[0])
    a = [[sum(r[i] * r[j] for r in rows) for j in range(k)] for i in range(k)]
    b = [sum(r[i] * y for r, y in zip(rows, target)) for i in range(k)]
    for col in range(k):
        pivot = max(range(col, k), key=lambda r: abs(a[r][col]))
        a[col], a[pivot], b[col], b[pivot] = a[pivot], a[col], b[pivot], b[col]
        for r in range(k):
            if r != col and a[col][col]:
                factor = a[r][col] / a[col][col]
                a[r] = [x - factor * y for x, y in zip(a[r], a[col])]
                b[r] -= factor * b[col]
    return [b[i] / a[i][i] for i in range(k)]


def fit_with_se(design: list[list[float]], target: list[float], draws: int = 300) -> list[tuple[float, float]]:
    """Least-squares coefficients with pair-bootstrap standard errors."""
    import random

    estimate = least_squares(design, target)
    rng = random.Random("continuation-bootstrap")
    samples = []
    for _ in range(draws):
        picks = [rng.randrange(len(design)) for _ in design]
        samples.append(least_squares([design[i] for i in picks], [target[i] for i in picks]))
    return [(estimate[j], statistics.stdev(sample[j] for sample in samples)) for j in range(len(estimate))]


def future_gap(episode: dict[str, Any], horizon: int) -> float:
    return sum(episode["model"]["future"][:horizon]) - sum(episode["reference"]["future"][:horizon])


def end_gap(episode: dict[str, Any]) -> float:
    return end_state_value(episode["model"]["raw"]) - end_state_value(episode["reference"]["raw"])


def winning_value(raw: dict[str, Any]) -> float:
    parts = contributions(raw, WEIGHTS["C"])
    return sum(parts[name] for name in WINNING_TERMS)


def continuation_score(side: dict[str, Any], horizon: int) -> float:
    """C with its end-state terms replaced by the simulated winning value that follows."""
    return winning_value(side["raw"]) + sum(side["future"][:horizon]) - side["raw"]["protocol_penalty"]


def compare_continuation_scores(groups: list[tuple[str, list[dict[str, Any]]]]) -> dict[str, Any]:
    """Row lifts under C and under continuation scores, published rows only."""
    scorers = {
        "C": lambda side: score(side["raw"], "C"),
        **{f"F{h}": (lambda side, h=h: continuation_score(side, h)) for h in (3, EXTRA_SEASONS)},
    }
    out: dict[str, Any] = {}
    for label, fn in scorers.items():
        stats = [score_v2.paired([fn(e["model"]) - fn(e["reference"]) for e in episodes]) for _row, episodes in groups]
        separable = holm([row["sign_flip_p"] for row in stats])
        out[label] = {
            "separable": sum(separable),
            "mean_mde80": round(statistics.mean(row["mde80"] for row in stats), 2),
            "lifts": {row: round(st["mean"], 2) for (row, _e), st in zip(groups, stats)},
        }
    base = list(out["C"]["lifts"].values())
    for block in out.values():
        block["kendall_tau_vs_C"] = round(kendall_tau(base, list(block["lifts"].values())), 3)
    return out


def run_continuation(run_dirs: list[Path], seeds: list[int], manager: str, jobs: int, cache: Path) -> dict[str, Any]:
    groups: list[tuple[str, list[dict[str, Any]]]] = []
    for run_dir in run_dirs:
        groups.append((run_dir.name, load_continuation(run_dir, manager, jobs, cache)))
        print(f"continued {run_dir.name}", flush=True)
    published = list(groups)
    names = [n for n in (*score_v2.REFERENCES, *(cls.name for cls in CANARY_AGENTS)) if n != "pick-trader"]
    work = [(name, seed, manager) for name in names for seed in seeds]
    with _pool(jobs) as pool:
        flat = list(pool.map(_continuation_scripted_job, work))
    for i, name in enumerate(names):
        groups.append((name, flat[i * len(seeds) : (i + 1) * len(seeds)]))

    pairs = [e for _label, episodes in groups for e in episodes]
    # A term that never differs from pick-trader's (a full roster, say) has no
    # estimable weight; leave it out of the regression.
    columns = [n for n in END_STATE if any(e["model"]["raw"][n] != e["reference"]["raw"][n] for e in pairs)]
    design = [[1.0, *(e["model"]["raw"][n] - e["reference"]["raw"][n] for n in columns)] for e in pairs]
    fits: dict[str, Any] = {}
    for horizon in (3, EXTRA_SEASONS):
        target = [future_gap(e, horizon) for e in pairs]
        weights = fit_with_se(design, target)
        slope = fit_with_se([[1.0, end_gap(e)] for e in pairs], target)
        fits[f"{horizon}_seasons"] = {
            # Future winning value per point of C's end-state score: 1 means
            # C prices the end state as exactly this many seasons of winning.
            "slope": {"estimate": round(slope[1][0], 3), "se": round(slope[1][1], 3)},
            "slope_intercept": {"estimate": round(slope[0][0], 2), "se": round(slope[0][1], 2)},
            "implied_weights": {
                name: {"estimate": round(c, 4), "se": round(se, 4)}
                for name, (c, se) in zip(["intercept", *columns], weights)
            },
        }
    return {
        "manager": manager,
        "extra_seasons": EXTRA_SEASONS,
        "scripted_seeds": [seeds[0], seeds[-1]],
        "rows": [
            {
                "row": label,
                "end_state_gap": mean_se([end_gap(e) for e in episodes]),
                **{f"future_gap_{h}": mean_se([future_gap(e, h) for e in episodes]) for h in (3, EXTRA_SEASONS)},
            }
            for label, episodes in groups
        ],
        "c_weights": {name: WEIGHTS["C"][name] for name in END_STATE},
        "fits": fits,
        "pairs": len(pairs),
        "continuation_scores": compare_continuation_scores(published) if published else None,
    }


def print_continuation(report: dict[str, Any]) -> None:
    horizon = report["extra_seasons"]
    print(f"\nEnd-state gap under C vs winning value gap with both teams handed to {report['manager']}:")
    for row in report["rows"]:
        print(
            f"  {row['row'][:44]:44s} end-state {row['end_state_gap']['mean']:+7.1f}"
            f"   next 3 {row['future_gap_3']['mean']:+7.1f} (se {row['future_gap_3']['se']})"
            f"   next {horizon} {row[f'future_gap_{horizon}']['mean']:+7.1f}"
        )
    print(f"\nC weights: {report['c_weights']}")
    for label, fit in report["fits"].items():
        print(f"{label}: slope {fit['slope']} intercept {fit['slope_intercept']}")
        print("   implied: " + "  ".join(f"{k} {v['estimate']} ({v['se']})" for k, v in fit["implied_weights"].items()))
    for label, block in (report["continuation_scores"] or {}).items():
        print(
            f"{label:3s} separable {block['separable']:2d}  mean MDE {block['mean_mde80']:5.1f}  tau vs C"
            f" {block['kendall_tau_vs_C']:+.3f}  " + " ".join(f"{v:+.1f}" for v in block["lifts"].values())
        )


# --------------------------------------------------------------------------
# continuation21: the continuation check under the 2.1 rules
# --------------------------------------------------------------------------


def _league21_class(legacy_draft: bool):
    from gm_bench.v21.rules import League21

    if not legacy_draft:
        return League21

    class League21LegacyDraft(League21):
        """2.1 with 1.0's draft, which skips opponent slots behind an unused user pick."""

        run_opponent_draft = League.run_opponent_draft

    return League21LegacyDraft


def _play21(cls, name: str, seed: int) -> Any:
    league = cls.new(seed=seed)
    agent = score_v2._agent_factory(name)()
    for index in range(len(ceiling_search.STEPS)):
        ceiling_search.play_step(league, agent, index)
    return league


def _side21(league: Any, manager: str) -> dict[str, float]:
    from gm_bench.v21.scoring import SCALE
    from gm_bench.v21.scoring import score_components as v2_components

    parts = v2_components(league, league.user_team_id)
    end_state = sum(
        parts[f"{name}_contribution"]
        for name in (
            "total_assets",
            "young_assets",
            "future_pick_assets",
            "cap_room",
            "current_strength",
            "roster_depth",
        )
    )
    agent = AGENTS[manager]()
    start = len(league.summaries)
    for _ in range(EXTRA_SEASONS):
        for index in range(len(ceiling_search.PHASES)):
            ceiling_search.play_step(league, agent, index)
    future = 0.0
    for summary in league.summaries[start:]:
        rounds, title = league.expected_playoffs[summary.season].get(league.user_team_id, (0.0, 0.0))
        future += summary.wins * SCALE.season_win + rounds * SCALE.playoff_round + title * SCALE.championship
    return {"end_state": end_state, "future": future}


def _continuation21_job(job: tuple[str, int, str, bool]) -> dict[str, Any]:
    name, seed, manager, legacy = job
    cls = _league21_class(legacy)
    model, reference = _side21(_play21(cls, name, seed), manager), _side21(_play21(cls, "pick-trader", seed), manager)
    return {
        "name": name,
        "end_gap": model["end_state"] - reference["end_state"],
        "future_gap": model["future"] - reference["future"],
    }


def run_continuation21(seeds: list[int], manager: str, jobs: int) -> dict[str, Any]:
    names = [n for n in (*score_v2.REFERENCES, *(cls.name for cls in CANARY_AGENTS)) if n != "pick-trader"]
    report: dict[str, Any] = {"seeds": [seeds[0], seeds[-1]], "manager": manager, "extra_seasons": EXTRA_SEASONS}
    # Plain worker processes: League21 needs none of the score_v2 hooks.
    with ProcessPoolExecutor(max_workers=max(1, jobs)) as pool:
        for label, legacy in (("draft_fixed", False), ("legacy_draft", True)):
            work = [(name, seed, manager, legacy) for name in names for seed in seeds]
            rows = list(pool.map(_continuation21_job, work))
            fit = fit_with_se([[1.0, r["end_gap"]] for r in rows], [r["future_gap"] for r in rows])
            report[label] = {
                "slope": {"estimate": round(fit[1][0], 3), "se": round(fit[1][1], 3)},
                "intercept": {"estimate": round(fit[0][0], 2), "se": round(fit[0][1], 2)},
                "rows": {
                    name: {
                        "end_gap": mean_se([r["end_gap"] for r in rows if r["name"] == name]),
                        "future_gap": mean_se([r["future_gap"] for r in rows if r["name"] == name]),
                        "residual": mean_se([r["future_gap"] - r["end_gap"] for r in rows if r["name"] == name]),
                    }
                    for name in names
                },
            }
    return report


def print_continuation21(report: dict[str, Any]) -> None:
    for label in ("legacy_draft", "draft_fixed"):
        block = report[label]
        print(f"\n[{label}] slope {block['slope']} intercept {block['intercept']}")
        for name, row in block["rows"].items():
            print(
                f"  {name:18s} end {row['end_gap']['mean']:+7.1f}  next {report['extra_seasons']} "
                f"{row['future_gap']['mean']:+7.1f}  residual {row['residual']['mean']:+6.1f} (se {row['residual']['se']})"
            )


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    panels = sub.add_parser("panels")
    panels.add_argument("run_dirs", nargs="+", type=Path)
    panels.add_argument("--cache", type=Path, default=Path("~/.cache/gm-bench-deep-dive").expanduser())
    noise = sub.add_parser("noise")
    noise.add_argument("--seeds", default="11-34")
    noise.add_argument("--draws", type=int, default=4)
    exploit = sub.add_parser("exploit")
    exploit.add_argument("--seeds", default="101-124")
    exploit.add_argument("--objective", choices=("C", "E"), default="C")
    exploit.add_argument("--worlds", type=int, default=6)
    reset = sub.add_parser("reset")
    reset.add_argument("--seeds", default="11-34")
    continuation = sub.add_parser("continuation")
    continuation.add_argument("run_dirs", nargs="*", type=Path)
    continuation.add_argument("--seeds", default="11-34", help="public seeds for the scripted policies")
    continuation.add_argument("--manager", default="pick-trader", help="scripted policy that runs both teams")
    continuation.add_argument("--cache", type=Path, default=Path("~/.cache/gm-bench-deep-dive").expanduser())
    continuation21 = sub.add_parser("continuation21", help="the continuation check under the 2.1 rules")
    continuation21.add_argument("--seeds", default="11-58")
    continuation21.add_argument("--manager", default="pick-trader")
    for command in (panels, noise, exploit, reset, continuation, continuation21):
        command.add_argument("--jobs", type=int, default=12)
        command.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    if args.command == "panels":
        output = run_panels([d.expanduser() for d in args.run_dirs], args.jobs, args.cache)
        print_panels(output)
    elif args.command == "noise":
        output = run_noise(ceiling_search._parse_seeds(args.seeds), args.draws, args.jobs)
        print_noise(output)
    elif args.command == "exploit":
        output = run_exploit(ceiling_search._parse_seeds(args.seeds), args.objective, args.worlds, args.jobs)
        print_exploit(output)
    elif args.command == "continuation21":
        output = run_continuation21(ceiling_search._parse_seeds(args.seeds), args.manager, args.jobs)
        print_continuation21(output)
    elif args.command == "reset":
        output = run_reset(ceiling_search._parse_seeds(args.seeds), args.jobs)
        print_reset(output)
    else:
        output = run_continuation(
            [d.expanduser() for d in args.run_dirs],
            ceiling_search._parse_seeds(args.seeds),
            args.manager,
            args.jobs,
            args.cache,
        )
        print_continuation(output)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
