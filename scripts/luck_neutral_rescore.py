"""Rescore 2.0 panel runs with playoff luck replaced by its expectation.

Diagnostic only: it never changes a published row. For each episode in a raw
run directory it replays ``ledger.jsonl`` through the frozen engine (the same
replay ``agentic-validate`` does) while recording, at each season's
playoffs, the user team's exact expected rounds won and title probability
given the playoff ratings the simulator used (see
``scripts/ceiling_search.py``). It then plays ``pick-trader`` on the same
seed and compares the two, both on the real score and on the luck-neutral
score, which swaps realized playoff rounds and championships for those
expectations.

Run directories hold the private panel seeds. This script reads them only
inside the process and never prints or writes a seed. Output is aggregate
only: published rows withhold per-seed scores, and so does this.

    python scripts/luck_neutral_rescore.py ~/gmb-runs/claude-sonnet-5-5-panel ...
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
from gm_bench.runner import _sign_flip_p_value  # noqa: E402
from gm_bench.scoring import score_team  # noqa: E402
from gm_bench.simulator import League  # noqa: E402

# Two-sided 5% test at 80% power, normal approximation.
MDE_Z = 1.959964 + 0.841621


def _track_playoffs() -> None:
    """Record expected playoff outcomes on every League in this process.

    The replay builds a plain League inside the frozen engine, so the hook is
    installed on the class rather than through ceiling_search.TrackedLeague.
    It only reads the bracket; the simulation is unchanged.
    """
    if getattr(League, "_luck_neutral_hooked", False):
        return
    original = League._simulate_playoffs

    def tracked(self, teams, ratings, rng):
        odds = ceiling_search.bracket_odds(teams, ratings).get(self.user_team_id, (0.0, 0.0))
        expected = dict(getattr(self, "expected_playoffs", {}))
        expected[self.season] = odds
        self.expected_playoffs = expected
        return original(self, teams, ratings, rng)

    League._simulate_playoffs = tracked
    League._luck_neutral_hooked = True


def _rescore_episode(ledger: Path) -> dict[str, Any]:
    _track_playoffs()
    episode, _marked = _replay(ledger)
    league = episode.league
    seed = int(json.loads(ledger.read_text(encoding="utf-8").splitlines()[0])["seed"])
    reference = League.new(seed=seed)
    ceiling_search.rollout(reference, 0)
    return {
        "score": score_team(league, league.user_team_id),
        "luck_neutral": ceiling_search.luck_neutral_score(league),
        "championships": league.user_team.championships,
        "expected_championships": sum(title for _rounds, title in league.expected_playoffs.values()),
        "reference": score_team(reference, reference.user_team_id),
        "reference_luck_neutral": ceiling_search.luck_neutral_score(reference),
        "reference_championships": reference.user_team.championships,
        "reference_expected_championships": sum(t for _r, t in reference.expected_playoffs.values()),
        "recorded_score": _recorded_score(ledger.parent),
    }


def _recorded_score(episode_dir: Path) -> float | None:
    result = episode_dir / "result.json"
    if not result.exists():
        return None
    return json.loads(result.read_text(encoding="utf-8")).get("final_score")


def _p(value: float | None) -> str:
    # The runner's sign-flip test samples 20,000 flips beyond 20 seeds.
    return "<0.0001" if value == 0.0 else f"{value:.4f}"


def _paired(lifts: list[float]) -> dict[str, Any]:
    n = len(lifts)
    sd = statistics.stdev(lifts)
    return {
        "mean": round(statistics.mean(lifts), 3),
        "sd": round(sd, 3),
        "se": round(sd / math.sqrt(n), 3),
        "ci95": [
            round(statistics.mean(lifts) - 1.96 * sd / math.sqrt(n), 3),
            round(statistics.mean(lifts) + 1.96 * sd / math.sqrt(n), 3),
        ],
        "sign_flip_p": _sign_flip_p_value(lifts),
        "ahead": sum(1 for lift in lifts if lift > 0),
        "mde80": round(MDE_Z * sd / math.sqrt(n), 3),
    }


def rescore_run(run_dir: Path, jobs: int) -> dict[str, Any]:
    ledgers = sorted(run_dir.glob("episode-*/ledger.jsonl"))
    if not ledgers:
        raise SystemExit(f"{run_dir}: no episode-*/ledger.jsonl")
    with ProcessPoolExecutor(max_workers=max(1, jobs)) as pool:
        rows = list(pool.map(_rescore_episode, ledgers))
    mismatched = [
        index
        for index, row in enumerate(rows)
        if row["recorded_score"] is not None and abs(row["recorded_score"] - round(row["score"], 3)) > 1e-6
    ]
    real = [row["score"] - row["reference"] for row in rows]
    neutral = [row["luck_neutral"] - row["reference_luck_neutral"] for row in rows]
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    return {
        "run": run_dir.name,
        "agent": run.get("agent"),
        "episodes": len(rows),
        "replay_mismatches": mismatched,
        "mean_score": round(statistics.mean(row["score"] for row in rows), 3),
        "mean_luck_neutral": round(statistics.mean(row["luck_neutral"] for row in rows), 3),
        "reference_mean": round(statistics.mean(row["reference"] for row in rows), 3),
        "reference_mean_luck_neutral": round(statistics.mean(row["reference_luck_neutral"] for row in rows), 3),
        "titles": sum(row["championships"] for row in rows),
        "expected_titles": round(sum(row["expected_championships"] for row in rows), 3),
        "reference_titles": sum(row["reference_championships"] for row in rows),
        "reference_expected_titles": round(sum(row["reference_expected_championships"] for row in rows), 3),
        "real": _paired(real),
        "luck_neutral": _paired(neutral),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_dirs", nargs="+", type=Path)
    parser.add_argument("--jobs", type=int, default=8)
    parser.add_argument("--out", type=Path, help="write per-run aggregates (no seeds, no per-episode scores) here")
    args = parser.parse_args(argv)

    results = []
    header = f"{'run':58s} {'real lift':>16s} {'p':>7s} {'MDE':>6s} | {'luck-neutral lift':>18s} {'p':>7s} {'MDE':>6s}"
    print(header)
    for run_dir in args.run_dirs:
        result = rescore_run(run_dir.expanduser(), args.jobs)
        results.append(result)
        real, neutral = result["real"], result["luck_neutral"]
        flag = f"  REPLAY MISMATCH {result['replay_mismatches']}" if result["replay_mismatches"] else ""
        print(
            f"{result['run'][:58]:58s} {real['mean']:+7.1f} (se {real['se']:4.1f}) {_p(real['sign_flip_p']):>7s}"
            f" {real['mde80']:6.1f} | {neutral['mean']:+8.1f} (se {neutral['se']:4.1f}) "
            f"{_p(neutral['sign_flip_p']):>7s} {neutral['mde80']:6.1f}{flag}",
            flush=True,
        )
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
