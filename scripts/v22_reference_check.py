"""Scripted policies under the 2.1 and the 2.2 draft rules, and a replay stress test.

Phase 3 of ``docs/bench_v2_2_spec.md``. Two questions, both answered without
a model call:

- ``policies``: does any scripted policy gain under 2.2 what it did not have
  under 2.1? Every policy from ``scripts/score_v3_candidates.py`` (the
  references, the validity canaries, the win-now family and the two
  end-of-run canaries) is played on public seeds under ``League21`` with
  score-v2 and under ``League22`` with score-v3, each against
  ``pick-trader`` under the same rules.
- ``ledgers``: does the 2.2 engine survive real model traffic? Finished 2.1
  ledgers are replayed through ``AgenticEpisode22``. The rules differ, so
  the games diverge and the scores mean nothing; the check is that every
  call is answered and every episode ends. Counts only are printed.

    python scripts/v22_reference_check.py policies --out results/diagnostics/v22_references/policies.json
    python scripts/v22_reference_check.py ledgers RUN_DIR [RUN_DIR ...]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import score_v3_candidates as candidates  # noqa: E402

from gm_bench.agentic.validate import replayable_ledger  # noqa: E402
from gm_bench.v21 import scoring as score_v2  # noqa: E402
from gm_bench.v21.rules import League21  # noqa: E402
from gm_bench.v22 import scoring as score_v3  # noqa: E402
from gm_bench.v22.episode import AgenticEpisode22  # noqa: E402
from gm_bench.v22.rules import League22  # noqa: E402

CONTRACTS = {"2.1": (League21, score_v2), "2.2-draft": (League22, score_v3)}
REFERENCE = "pick-trader"


def _policy_job(job: tuple[str, str, int]) -> dict[str, Any]:
    contract, name, seed = job
    league_class, scoring = CONTRACTS[contract]
    league = candidates.play(name, seed, league_class)
    return {
        "contract": contract,
        "policy": name,
        "seed": seed,
        "score": scoring.score_team(league, league.user_team_id),
        "illegal": league.illegal_actions,
    }


def run_policies(seeds: list[int], jobs: int) -> dict[str, Any]:
    work = [(contract, name, seed) for contract in CONTRACTS for name in candidates.SCRIPTED for seed in seeds]
    with ProcessPoolExecutor(max_workers=max(1, jobs)) as pool:
        rows = list(pool.map(_policy_job, work, chunksize=4))
    score = {(r["contract"], r["policy"], r["seed"]): r["score"] for r in rows}
    illegal = {(r["contract"], r["policy"], r["seed"]): r["illegal"] for r in rows}
    report: dict[str, Any] = {"seeds": [seeds[0], seeds[-1]], "reference": REFERENCE, "policies": {}}
    for name in candidates.SCRIPTED:
        block: dict[str, Any] = {}
        for contract in CONTRACTS:
            scores = [score[contract, name, seed] for seed in seeds]
            lifts = [score[contract, name, seed] - score[contract, REFERENCE, seed] for seed in seeds]
            block[contract] = {
                "mean_score": round(statistics.fmean(scores), 2),
                "lift": round(statistics.fmean(lifts), 2),
                "lift_se": round(statistics.stdev(lifts) / len(lifts) ** 0.5, 2),
                "illegal_actions_per_episode": round(statistics.fmean(illegal[contract, name, s] for s in seeds), 2),
            }
        block["lift_change"] = round(block["2.2-draft"]["lift"] - block["2.1"]["lift"], 2)
        report["policies"][name] = block
    return report


def _ledger_job(path: str) -> str:
    records = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    records, _marked = replayable_ledger(records)
    with tempfile.TemporaryDirectory() as directory:
        clean = Path(directory) / "ledger.jsonl"
        clean.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
        try:
            episode = AgenticEpisode22.from_ledger(clean, reopen=False)
        except Exception as exc:  # noqa: BLE001 - the point is to count every failure
            return f"error: {type(exc).__name__}"
    if not episode.done:
        return "unfinished"
    episode.result()
    return "ok"


def run_ledgers(run_dirs: list[Path], jobs: int) -> dict[str, int]:
    ledgers = [str(p) for run_dir in run_dirs for p in sorted(run_dir.glob("episode-*/ledger.jsonl"))]
    with ProcessPoolExecutor(max_workers=max(1, jobs)) as pool:
        outcomes = list(pool.map(_ledger_job, ledgers, chunksize=2))
    return {outcome: outcomes.count(outcome) for outcome in sorted(set(outcomes))}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    policies = commands.add_parser("policies")
    policies.add_argument("--seeds", default="101-172")
    policies.add_argument("--out", type=Path)
    ledgers = commands.add_parser("ledgers")
    ledgers.add_argument("run_dirs", nargs="+", type=Path)
    for command in (policies, ledgers):
        command.add_argument("--jobs", type=int, default=12)
    args = parser.parse_args(argv)
    if args.command == "ledgers":
        print(json.dumps(run_ledgers([p.expanduser() for p in args.run_dirs], args.jobs)))
        return 0
    report = run_policies(candidates.parse_seeds(args.seeds), args.jobs)
    print(f"{'policy':28s}{'2.1 lift':>10s}{'2.2 lift':>10s}{'change':>8s}{'illegal 2.1':>12s}{'2.2':>6s}")
    for name, block in report["policies"].items():
        a, b = block["2.1"], block["2.2-draft"]
        print(
            f"{name:28s}{a['lift']:>+10.1f}{b['lift']:>+10.1f}{block['lift_change']:>+8.1f}"
            f"{a['illegal_actions_per_episode']:>12.2f}{b['illegal_actions_per_episode']:>6.2f}"
        )
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
