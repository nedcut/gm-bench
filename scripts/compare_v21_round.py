"""Compare a model's 2.1 panel run with its published 2.0 run, seed by seed.

The analysis pre-registered in ``docs/bench_v2_1_spec.md`` ("First paid
round"). Each pair is a 2.0 raw run directory and the 2.1 run of the same
model on the same private panel. Episodes pair by position, and the seeds
must match. For each model:

- the 2.1 lift against ``pick-trader`` played under the 2.1 rules
  (``gm_bench.v21.runner``) on the same seeds;
- the 2.0 lift against ``pick-trader`` under score-v1 (the 1.0 runner) on
  the same seeds, and the replayed score-v2 E lift on the full panel from
  ``results/diagnostics/score_deep_dive/panels.json``;
- failed decisions, illegal moves and tool calls per episode, both runs.

Works on a 2.1 run still in progress: it reads each finished episode's
``result.json``. Prints and writes aggregates only; no seed and no
per-episode score leaves this script.

    python scripts/compare_v21_round.py \\
        --pair ~/gmb-runs/<2.0 run> ~/gmb-runs/<2.1 run> [--pair ...] [--out round.json]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from itertools import combinations
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "scripts"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from score_v2 import paired  # noqa: E402

from gm_bench.agents import AGENTS  # noqa: E402
from gm_bench.runner import run_episode as run_v1  # noqa: E402
from gm_bench.v21.runner import run_episode as run_v21  # noqa: E402

PANELS = ROOT / "results" / "diagnostics" / "score_deep_dive" / "panels.json"


def _episodes(run_dir: Path) -> list[dict[str, Any]]:
    run_json = run_dir / "run.json"
    if run_json.exists():
        return json.loads(run_json.read_text(encoding="utf-8"))["episodes"]
    finished = sorted(run_dir.glob("episode-*/result.json"))
    return [json.loads(path.read_text(encoding="utf-8")) for path in finished]


def _per_episode(episodes: list[dict[str, Any]], key: str) -> float:
    if key == "tool_calls":
        return statistics.mean(e["agentic"]["tool_calls"] for e in episodes)
    return statistics.mean(float(e[key]) for e in episodes)


def compare_pair(old_dir: Path, new_dir: Path, e_lifts: dict[str, float]) -> dict[str, Any]:
    old, new = _episodes(old_dir), _episodes(new_dir)
    if not new:
        raise SystemExit(f"{new_dir}: no finished episodes")
    old = old[: len(new)]
    if [e["seed"] for e in old] != [e["seed"] for e in new]:
        raise SystemExit(f"{new_dir}: seeds do not match {old_dir} position by position")
    contract = json.loads((new_dir / "episode-00" / "ledger.jsonl").read_text(encoding="utf-8").splitlines()[0])
    if contract.get("benchmark_version") != "gm-bench-2.1":
        raise SystemExit(f"{new_dir}: not a 2.1 run")
    pick_trader = AGENTS["pick-trader"]
    lift_21 = [e["final_score"] - run_v21(pick_trader(), int(e["seed"]))["final_score"] for e in new]
    lift_20 = [e["final_score"] - run_v1(pick_trader(), int(e["seed"])).final_score for e in old]
    return {
        "model": new[0]["agent"],
        "run_2_0": old_dir.name,
        "run_2_1": new_dir.name,
        "episodes": len(new),
        "lift_2_1": paired(lift_21),
        "lift_2_0_score_v1": paired(lift_20),
        "lift_2_0_score_v2_e_full_panel": e_lifts.get(old_dir.name),
        "lift_change": paired([a - b for a, b in zip(lift_21, lift_20)]),
        "per_episode": {
            key: {"2.0": round(_per_episode(old, key), 3), "2.1": round(_per_episode(new, key), 3)}
            for key in ("failed_decisions", "illegal_actions", "tool_calls")
        },
    }


def kendall_tau(a: list[float], b: list[float]) -> float | None:
    pairs = list(combinations(range(len(a)), 2))
    if not pairs:
        return None
    return sum(1 if (a[i] - a[j]) * (b[i] - b[j]) > 0 else -1 for i, j in pairs) / len(pairs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pair", nargs=2, type=Path, action="append", required=True, metavar=("RUN_2_0", "RUN_2_1"))
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    e_lifts = json.loads(PANELS.read_text(encoding="utf-8"))["candidates"]["E"]["lifts"] if PANELS.exists() else {}
    rows = [compare_pair(old.expanduser(), new.expanduser(), e_lifts) for old, new in args.pair]
    new_lifts = [row["lift_2_1"]["mean"] for row in rows]
    report = {
        "rows": rows,
        "kendall_tau_vs_2_0_score_v1": kendall_tau(new_lifts, [row["lift_2_0_score_v1"]["mean"] for row in rows]),
        "kendall_tau_vs_2_0_score_v2_e": (
            kendall_tau(new_lifts, [row["lift_2_0_score_v2_e_full_panel"] for row in rows])
            if all(row["lift_2_0_score_v2_e_full_panel"] is not None for row in rows)
            else None
        ),
        "sign_conflicts": [
            row["model"]
            for row in rows
            if (row["lift_2_1"]["ci95"][0] > 0 and row["lift_2_0_score_v1"]["mean"] < 0)
            or (row["lift_2_1"]["ci95"][1] < 0 and row["lift_2_0_score_v1"]["mean"] > 0)
        ],
    }
    for row in rows:
        new, old = row["lift_2_1"], row["lift_2_0_score_v1"]
        print(
            f"{row['model'][:42]:42s} n={row['episodes']:2d}  2.1 lift {new['mean']:+7.1f} (se {new['se']:.1f}, "
            f"p {new['sign_flip_p']}, MDE {new['mde80']:.1f})  2.0 v1 {old['mean']:+7.1f}  "
            f"2.0 E {row['lift_2_0_score_v2_e_full_panel']}"
        )
    print(
        f"Kendall tau vs 2.0 v1: {report['kendall_tau_vs_2_0_score_v1']}  vs 2.0 E: "
        f"{report['kendall_tau_vs_2_0_score_v2_e']}  sign conflicts: {report['sign_conflicts'] or 'none'}"
    )
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
