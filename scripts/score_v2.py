"""Evaluate candidate score-v2 rules on existing evidence, at no model cost.

Every candidate keeps the simulation byte for byte and changes only how the
final league state is scored, so it can be applied exactly to any recorded
episode. Candidates, each built on the one before:

``v1``
    The published ``score-v1``.
``A``  expected playoffs
    Realized playoff rounds and championships are replaced by their exact
    expectation from the bracket and the playoff ratings the simulator used.
``B``  A + per-season recent wins
    ``recent_wins`` becomes wins in the last three seasons. Under v1 it sums
    the running win total after seasons 3, 4 and 5, because records never
    reset (``docs/bench_v2_1_queue.md`` item 15), weighting seasons
    3, 3, 3, 2, 1. Same weight (0.42), so the term shrinks.
``C``  B with the weight rescaled
    The per-season term is reweighted so ``pick-trader``'s mean contribution
    on the canary seeds (11-34) matches v1's (``PER_SEASON_RECENT_WIN``).
``D``  C with expected regular-season wins
    The user's regular-season wins in the last three seasons are replaced by
    the sum of its per-game win probabilities. Every game outcome is then out
    of the score; injury, development and market draws remain.

Two subcommands:

``baselines``  plays the scripted references and the validity canaries on
    public seeds and reports, per candidate, the contract's asserted
    orderings, the adjacent calibration contrasts and the across-seed spread.
``panels``  replays each episode ledger of raw 2.0 panel run directories
    through the frozen engine (the replay ``agentic-validate`` does), plays
    ``pick-trader`` on the same seed, and reports each row's paired lift
    against it per candidate. Run directories carry the
    private seeds; nothing seed-level is printed or written.

    python scripts/score_v2.py baselines --seeds 11-34
    python scripts/score_v2.py panels ~/gmb-runs/<run> ... --out rescore.json
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "scripts"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import ceiling_search  # noqa: E402

from gm_bench.agentic.validate import _replay  # noqa: E402
from gm_bench.agents import AGENTS, Agent  # noqa: E402
from gm_bench.runner import _sign_flip_p_value  # noqa: E402
from gm_bench.scoring import ACTIVE_SCORE_SCALE, score_team  # noqa: E402
from gm_bench.simulator import League  # noqa: E402
from gm_bench.validity import CANARY_AGENTS, CANARY_SEEDS  # noqa: E402

VARIANTS = ("v1", "A", "B", "C", "D")
# Logistic scale of a regular-season game in League._play_game.
GAME_LOGIT_SCALE = 7.5
RECENT_SEASONS = 3
# C's weight on per-season recent wins: v1's 0.42 times the ratio of
# pick-trader's mean cumulative term to its mean per-season term on the
# canary seeds 11-34 (`baselines --calibrate` prints the ratio).
PER_SEASON_RECENT_WIN = 1.67
MDE_Z = 1.959964 + 0.841621


# --------------------------------------------------------------------------
# Hooks and candidate scores
# --------------------------------------------------------------------------


def install_hooks() -> None:
    """Record expected playoff outcomes and expected wins on every League.

    Installed on the class so leagues built inside the frozen agentic engine
    are covered. Both hooks only read state before deferring to the original
    method with the same RNG, so the simulation is unchanged.
    """
    if getattr(League, "_score_v2_hooked", False):
        return
    simulate_playoffs = League._simulate_playoffs
    play_game = League._play_game

    def tracked_playoffs(self, teams, ratings, rng):
        odds = ceiling_search.bracket_odds(teams, ratings).get(self.user_team_id, (0.0, 0.0))
        expected = dict(getattr(self, "expected_playoffs", {}))
        expected[self.season] = odds
        self.expected_playoffs = expected
        return simulate_playoffs(self, teams, ratings, rng)

    def tracked_game(self, home, away, ratings, rng):
        if self.user_team_id in (home.id, away.id):
            p_home = 1.0 / (1.0 + math.exp(-(ratings[home.id] - ratings[away.id]) / GAME_LOGIT_SCALE))
            p_user = p_home if home.id == self.user_team_id else 1.0 - p_home
            expected = dict(getattr(self, "expected_wins", {}))
            expected[self.season] = expected.get(self.season, 0.0) + p_user
            self.expected_wins = expected
        return play_game(self, home, away, ratings, rng)

    League._simulate_playoffs = tracked_playoffs
    League._play_game = tracked_game
    League._score_v2_hooked = True


def per_season_wins(league: League) -> list[int]:
    """Each season's own wins, undoing the running total in the summaries."""
    totals = [summary.wins for summary in league.summaries]
    return [total - (totals[index - 1] if index else 0) for index, total in enumerate(totals)]


def variant_scores(league: League) -> dict[str, float]:
    scale = ACTIVE_SCORE_SCALE
    v1 = score_team(league, league.user_team_id)
    recent = league.summaries[-RECENT_SEASONS:]
    expected_playoffs: dict[int, tuple[float, float]] = getattr(league, "expected_playoffs", {})
    playoff_swap = (
        sum(expected_playoffs[s.season][0] - s.playoff_rounds for s in recent) * scale.playoff_round
        + (sum(title for _rounds, title in expected_playoffs.values()) - league.user_team.championships)
        * scale.championship
    )
    a = v1 + playoff_swap
    cumulative_term = sum(s.wins for s in recent) * scale.recent_win
    own_wins = sum(per_season_wins(league)[-RECENT_SEASONS:])
    b = a - cumulative_term + own_wins * scale.recent_win
    c = a - cumulative_term + own_wins * PER_SEASON_RECENT_WIN
    expected_wins: dict[int, float] = getattr(league, "expected_wins", {})
    expected_own = sum(expected_wins.get(s.season, 0.0) for s in recent)
    d = c + (expected_own - own_wins) * PER_SEASON_RECENT_WIN
    return {"v1": v1, "A": a, "B": b, "C": c, "D": d, "_cumulative_term": cumulative_term, "_own_wins": own_wins}


def play(agent: Agent, seed: int) -> League:
    league = League.new(seed=seed)
    for index in range(len(ceiling_search.STEPS)):
        ceiling_search.play_step(league, agent, index)
    return league


# --------------------------------------------------------------------------
# Statistics
# --------------------------------------------------------------------------


def paired(lifts: list[float]) -> dict[str, Any]:
    n = len(lifts)
    mean = statistics.mean(lifts)
    sd = statistics.stdev(lifts) if n > 1 else 0.0
    se = sd / math.sqrt(n) if n else 0.0
    return {
        "mean": round(mean, 3),
        "sd": round(sd, 3),
        "se": round(se, 3),
        "t": round(mean / se, 3) if se else None,
        "ci95": [round(mean - 1.96 * se, 3), round(mean + 1.96 * se, 3)],
        "sign_flip_p": _sign_flip_p_value(lifts),
        "ahead": sum(1 for lift in lifts if lift > 0),
        "mde80": round(MDE_Z * se, 3),
    }


def _p(value: float | None) -> str:
    # The runner's sign-flip test samples 20,000 flips beyond 20 seeds.
    if value is None:
        return "n/a"
    return "<0.0001" if value == 0.0 else f"{value:.4f}"


# --------------------------------------------------------------------------
# baselines
# --------------------------------------------------------------------------

REFERENCES = ("random", "value", "shrewd", "strategic", "pick-trader")
ASSERTED = (("pick-trader", "value", 0.0), ("shrewd", "value", 25.0))
ADJACENT = (("pick-trader", "strategic"), ("strategic", "shrewd"), ("pick-trader", "shrewd"))
CANARY_MARGIN = 25.0
CANARY_T = 2.0


def _agent_factory(name: str):
    if name in AGENTS:
        return AGENTS[name]
    return next(cls for cls in CANARY_AGENTS if cls.name == name)


def _baseline_job(job: tuple[str, int]) -> dict[str, float]:
    install_hooks()
    name, seed = job
    return variant_scores(play(_agent_factory(name)(), seed))


def run_baselines(seeds: list[int], jobs: int) -> dict[str, Any]:
    names = [*REFERENCES, *(cls.name for cls in CANARY_AGENTS)]
    work = [(name, seed) for name in names for seed in seeds]
    with ProcessPoolExecutor(max_workers=max(1, jobs)) as pool:
        flat = list(pool.map(_baseline_job, work))
    scores = {name: flat[i * len(seeds) : (i + 1) * len(seeds)] for i, name in enumerate(names)}

    pt = scores["pick-trader"]
    ratio = statistics.mean(r["_cumulative_term"] for r in pt) / statistics.mean(
        r["_own_wins"] * ACTIVE_SCORE_SCALE.recent_win for r in pt
    )
    report: dict[str, Any] = {
        "seeds": [seeds[0], seeds[-1]] if seeds == list(range(seeds[0], seeds[-1] + 1)) else seeds,
        "calibration_ratio": round(ratio, 4),
        "calibrated_weight": round(ACTIVE_SCORE_SCALE.recent_win * ratio, 4),
        "variants": {},
    }
    for variant in VARIANTS:
        means = {name: round(statistics.mean(r[variant] for r in rows), 3) for name, rows in scores.items()}
        sds = {
            name: round(statistics.stdev(r[variant] for r in rows), 3) if len(rows) > 1 else None
            for name, rows in scores.items()
        }

        def contrast(winner: str, loser: str) -> dict[str, Any]:
            return paired([w[variant] - lo[variant] for w, lo in zip(scores[winner], scores[loser])])

        asserted = []
        for winner, loser, margin in ASSERTED:
            stats = contrast(winner, loser)
            asserted.append(
                {
                    "winner": winner,
                    "loser": loser,
                    **stats,
                    "ok": stats["mean"] >= margin and (stats["t"] or 0.0) >= CANARY_T,
                }
            )
        for cls in CANARY_AGENTS:
            stats = contrast("value", cls.name)
            asserted.append(
                {
                    "winner": "value",
                    "loser": cls.name,
                    **stats,
                    "ok": stats["mean"] >= CANARY_MARGIN and (stats["t"] or 0.0) >= CANARY_T,
                }
            )
        report["variants"][variant] = {
            "means": means,
            "across_seed_sd": sds,
            "asserted": asserted,
            "all_asserted_ok": all(row["ok"] for row in asserted),
            "adjacent": {f"{w} - {lo}": contrast(w, lo) for w, lo in ADJACENT},
        }
    return report


def print_baselines(report: dict[str, Any]) -> None:
    print(
        f"calibration: pick-trader cumulative/per-season recent-wins ratio {report['calibration_ratio']}"
        f" -> weight {report['calibrated_weight']} (C uses {PER_SEASON_RECENT_WIN})"
    )
    for variant, block in report["variants"].items():
        means = block["means"]
        print(f"\n[{variant}] asserted orderings {'all pass' if block['all_asserted_ok'] else 'FAIL'}")
        print("  means: " + "  ".join(f"{name} {value:.1f}" for name, value in means.items()))
        print("  pick-trader across-seed SD:", block["across_seed_sd"]["pick-trader"])
        for row in block["asserted"]:
            print(
                f"  {row['winner']} - {row['loser']}: {row['mean']:+.1f} (t {row['t']}, sd {row['sd']})"
                f" {'ok' if row['ok'] else 'FAIL'}"
            )
        for name, row in block["adjacent"].items():
            print(f"  adjacent {name}: {row['mean']:+.1f} (t {row['t']}, sd {row['sd']}, MDE {row['mde80']})")


# --------------------------------------------------------------------------
# panels
# --------------------------------------------------------------------------


def _panel_job(ledger: Path) -> dict[str, Any]:
    install_hooks()
    episode, _marked = _replay(ledger)
    seed = int(json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])["seed"])
    reference = play(AGENTS["pick-trader"](), seed)
    # Every episode must carry its recorded score, or a clean replay check
    # would silently cover fewer episodes than it reports.
    recorded = json.loads((ledger.parent / "result.json").read_text(encoding="utf-8"))["final_score"]
    return {"model": variant_scores(episode.league), "reference": variant_scores(reference), "recorded": recorded}


def run_panel(run_dir: Path, jobs: int) -> dict[str, Any]:
    ledgers = sorted(run_dir.glob("episode-*/ledger.jsonl"))
    if not ledgers:
        raise SystemExit(f"{run_dir}: no episode-*/ledger.jsonl")
    with ProcessPoolExecutor(max_workers=max(1, jobs)) as pool:
        rows = list(pool.map(_panel_job, ledgers))
    mismatches = sum(1 for row in rows if abs(row["recorded"] - round(row["model"]["v1"], 3)) > 1e-6)
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    return {
        "run": run_dir.name,
        "agent": run.get("agent"),
        "episodes": len(rows),
        "replay_mismatches": mismatches,
        "variants": {
            variant: {
                "model_mean": round(statistics.mean(row["model"][variant] for row in rows), 3),
                "reference_mean": round(statistics.mean(row["reference"][variant] for row in rows), 3),
                "lift": paired([row["model"][variant] - row["reference"][variant] for row in rows]),
            }
            for variant in VARIANTS
        },
    }


def print_panel(result: dict[str, Any]) -> None:
    flag = f"  REPLAY MISMATCHES {result['replay_mismatches']}" if result["replay_mismatches"] else ""
    cells = "  ".join(
        f"{v} {b['lift']['mean']:+6.1f} p {_p(b['lift']['sign_flip_p']):>7s} MDE {b['lift']['mde80']:4.1f}"
        for v, b in result["variants"].items()
    )
    print(f"{result['run'][:44]:44s} {cells}{flag}", flush=True)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    base = sub.add_parser("baselines", help="scripted references and canaries on public seeds")
    base.add_argument("--seeds", default=f"{CANARY_SEEDS[0]}-{CANARY_SEEDS[-1]}")
    panels = sub.add_parser("panels", help="replay raw 2.0 panel run directories")
    panels.add_argument("run_dirs", nargs="+", type=Path)
    for command in (base, panels):
        command.add_argument("--jobs", type=int, default=8)
        command.add_argument("--out", type=Path, help="write aggregates here (never seeds or per-episode scores)")
    args = parser.parse_args(argv)

    if args.command == "baselines":
        output: Any = run_baselines(ceiling_search._parse_seeds(args.seeds), args.jobs)
        print_baselines(output)
    else:
        output = []
        for run_dir in args.run_dirs:
            result = run_panel(run_dir.expanduser(), args.jobs)
            output.append(result)
            print_panel(result)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
