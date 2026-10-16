"""Rescore the published GM-Bench 2.0 panel rows under score-v2, for the site.

Each published 2.0 artifact (``results/agentic/*.json``) is score-v1. This
replays every episode of the raw run behind it (the replay
``agentic-validate`` does, through the frozen engine) and scores the final
league with score-v2's weights (``gm_bench/v21/scoring.py``): expected
playoff rounds and titles from the bracket odds, every season's own wins
(differenced from 2.0's running totals), and the unchanged end-state terms.
The games are 2.0's, so this is a rescore of the 2.0 rows, not a 2.1 run:
records still accumulate inside the simulation and the 2.0 draft is
unchanged.

For each row it writes ``results/agentic_score_v2/<artifact name>``:
per-episode score-v2 totals in the artifact's episode order (index and seed
group, no seed), and the predeclared ``pick-trader`` contrast in the same
shape as the artifact's ``reference`` block, computed by the same function
(``gm_bench.runner._paired_analysis``). The file names the artifact's
``raw_artifact_sha256``, so it is bound to the run it was computed from.
``lane.json`` there records pick-trader, random and every scripted bot
under score-v2 on the frozen panel, whose seeds every raw run carries (they
must all agree).

Nothing seed-level is written or printed. ``--check`` recomputes and
compares instead of writing.

    python scripts/rescore_agentic_v2.py --raw ~/gmb-runs/<run> ... [--check]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "scripts"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import score_deep_dive as deep_dive  # noqa: E402
import score_v2  # noqa: E402

from gm_bench.agentic.publication import (  # noqa: E402
    SIGN_FLIP_EXACT_MAX_SEEDS,
    SIGN_FLIP_P_BOUND,
    is_agentic_artifact,
    seed_groups,
)
from gm_bench.agentic.validate import _replay  # noqa: E402
from gm_bench.publication import canonical_sha256  # noqa: E402
from gm_bench.runner import _paired_analysis  # noqa: E402
from gm_bench.v21 import scoring as v2  # noqa: E402

ARTIFACTS = ROOT / "results" / "agentic"
OUTPUT = ROOT / "results" / "agentic_score_v2"
LANE_CONFIG = ROOT / "config" / "bench_v2_lane.json"
FORMAT = "gm-bench-agentic-score-v2-rescore-v1"
REFERENCE_AGENT, FLOOR_AGENT = "pick-trader", "random"
METHOD = (
    "Each 2.0 episode replayed from its ledger through the frozen 2.0 engine and scored with score-v2's weights: "
    "expected playoff rounds (last three seasons) and expected titles (all seasons) from the bracket odds the "
    "simulator used, every season's own wins, and the unchanged end-state terms. The games are 2.0's, so records "
    "accumulate in the simulation and the 2.0 draft is unchanged; this rescores the 2.0 rows and is not a 2.1 run."
)


def _check_weights() -> None:
    """The deep dive's candidate E must be score-v2, weight for weight."""
    expected = {
        "all_wins": v2.SCALE.season_win,
        "recent_wins": 0.0,
        "playoff_rounds": v2.SCALE.playoff_round,
        "championships": v2.SCALE.championship,
        "total_assets": v2.SCALE.total_asset,
        "young_assets": v2.SCALE.young_asset,
        "future_pick_assets": v2.SCALE.future_pick_asset,
        "cap_room": v2.SCALE.cap_room,
        "current_strength": v2.SCALE.current_strength,
        "roster_depth": v2.SCALE.roster_depth,
    }
    if deep_dive.WEIGHTS["E"] != expected:
        raise SystemExit(f"score_deep_dive candidate E {deep_dive.WEIGHTS['E']} is not score-v2 {expected}")


def _episode_job(ledger: str) -> dict[str, float]:
    episode, _marked = _replay(Path(ledger))
    raw = deep_dive.raw_terms(episode.league)
    return {"v1": raw["v1"], "v2": deep_dive.score(raw, "E"), "penalty": raw["protocol_penalty"]}


def _scripted_job(job: tuple[str, int]) -> float:
    name, seed = job
    return deep_dive.score(deep_dive.raw_terms(deep_dive.play(name, seed)), "E")


def _pool(jobs: int) -> ProcessPoolExecutor:
    return ProcessPoolExecutor(max_workers=max(1, jobs), initializer=score_v2.install_hooks)


def _artifacts_by_raw_sha() -> dict[str, Path]:
    found = {}
    for path in sorted(ARTIFACTS.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if is_agentic_artifact(payload) and payload.get("grade") == "panel":
            found[payload["publication"]["raw_artifact_sha256"]] = path
    return found


def _scripted_means(names: list[str], seeds: list[int], jobs: int) -> dict[str, list[float]]:
    work = [(name, seed) for name in names for seed in seeds]
    with _pool(jobs) as pool:
        flat = list(pool.map(_scripted_job, work))
    return {name: flat[i * len(seeds) : (i + 1) * len(seeds)] for i, name in enumerate(names)}


def rescore_run(run_dir: Path, artifact_path: Path, jobs: int) -> dict[str, Any]:
    raw = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    raw_episodes = raw["episodes"]
    ledgers = [str(run_dir / episode["harness_run"]["ledger_path"]) for episode in raw_episodes]
    with _pool(jobs) as pool:
        scored = list(pool.map(_episode_job, ledgers))
    published = artifact["episodes"]
    if len(published) != len(scored):
        raise SystemExit(f"{artifact_path.name}: {len(published)} published episodes, {len(scored)} in the raw run")
    for index, (row, result) in enumerate(zip(published, scored, strict=True)):
        if row["index"] != index or abs(round(result["v1"], 3) - row["final_score"]) > 1e-6:
            raise SystemExit(f"{artifact_path.name}: episode {index} does not replay to its published score-v1 total")
    seeds = [int(episode["seed"]) for episode in raw_episodes]
    groups = seed_groups(seeds)
    distinct = list(dict.fromkeys(seeds))
    scripted = _scripted_means([REFERENCE_AGENT, FLOOR_AGENT], distinct, jobs)
    candidate = {"episodes": [{"seed": s, "final_score": r["v2"]} for s, r in zip(seeds, scored, strict=True)]}
    reference = {
        "agent": REFERENCE_AGENT,
        "episodes": [{"seed": s, "final_score": v} for s, v in zip(distinct, scripted[REFERENCE_AGENT])],
    }
    paired = _paired_analysis(distinct, candidate, [reference])
    p_value = paired["sign_flip_p_value"]
    bounded = p_value == 0.0 and paired["num_seeds"] > SIGN_FLIP_EXACT_MAX_SEEDS
    return {
        "format": FORMAT,
        "artifact": artifact_path.name,
        "raw_artifact_sha256": artifact["publication"]["raw_artifact_sha256"],
        "scoring_version": v2.SCORING_VERSION,
        "scoring_scale_fingerprint": v2.scale_fingerprint(),
        "method": METHOD,
        "episodes": [
            {
                "index": index,
                "seed_group": groups[index],
                "final_score": round(result["v2"], 3),
                "strategy_score": round(result["v2"] + result["penalty"], 3),
                "protocol_penalty": round(result["penalty"], 3),
            }
            for index, result in enumerate(scored)
        ],
        "reference": {
            "agent": REFERENCE_AGENT,
            "mean_score": round(statistics.mean(scripted[REFERENCE_AGENT]), 3),
            "floor": {"agent": FLOOR_AGENT, "mean_score": round(statistics.mean(scripted[FLOOR_AGENT]), 3)},
            "seasons": raw["seasons"],
            "num_seeds": paired["num_seeds"],
            "paired_lift_mean": paired["paired_lift_mean"],
            "paired_lift_stddev": paired["paired_lift_stddev"],
            "paired_lift_ci95": paired["paired_lift_ci95"],
            "sign_flip_p_value": SIGN_FLIP_P_BOUND if bounded else p_value,
            **({"sign_flip_p_value_upper_bound": True} if bounded else {}),
            "significant_at_95": paired["significant_at_95"],
            "candidate_seed_win_rate": paired["candidate_seed_win_rate"],
            "per_seed": [],
        },
    }


def lane_block(seeds: list[int], jobs: int) -> dict[str, Any]:
    lane = json.loads(LANE_CONFIG.read_text(encoding="utf-8"))
    bots = list(lane["scripted_bot_scores"]["mean_scores"])
    means = _scripted_means(bots, seeds, jobs)
    return {
        "format": FORMAT,
        "scoring_version": v2.SCORING_VERSION,
        "scoring_scale_fingerprint": v2.scale_fingerprint(),
        "method": METHOD.replace("Each 2.0 episode replayed from its ledger", "Each scripted policy played"),
        "seasons": lane["scripted_bot_scores"]["seasons"],
        "num_seeds": len(seeds),
        "reference_scores": {name: round(statistics.mean(means[name]), 3) for name in (REFERENCE_AGENT, FLOOR_AGENT)},
        "scripted_bot_scores": {name: round(statistics.mean(values), 3) for name, values in means.items()},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--raw", nargs="+", type=Path, required=True, help="raw 2.0 run directories behind published rows"
    )
    parser.add_argument("--jobs", type=int, default=8)
    parser.add_argument("--check", action="store_true", help="recompute and compare with the committed files")
    args = parser.parse_args(argv)
    _check_weights()
    by_sha = _artifacts_by_raw_sha()
    outputs: dict[Path, dict[str, Any]] = {}
    panel_seeds: list[int] | None = None
    for run_dir in (path.expanduser() for path in args.raw):
        raw = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        artifact = by_sha.get(canonical_sha256(raw))
        if artifact is None:
            raise SystemExit(f"{run_dir}: no published panel artifact is bound to this raw run")
        outputs[OUTPUT / artifact.name] = rescore_run(run_dir, artifact, args.jobs)
        seeds = list(dict.fromkeys(int(s) for s in raw["seeds"]))
        if panel_seeds is not None and seeds != panel_seeds:
            raise SystemExit(f"{run_dir}: not the same frozen panel as the other runs")
        panel_seeds = seeds
        print(f"rescored {artifact.name}", flush=True)
    missing = sorted(path.name for path in by_sha.values() if OUTPUT / path.name not in outputs)
    if missing:
        raise SystemExit(f"published panel rows with no raw run given: {missing}")
    outputs[OUTPUT / "lane.json"] = lane_block(panel_seeds or [], args.jobs)
    stale = []
    for path, payload in outputs.items():
        text = json.dumps(payload, indent=2) + "\n"
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                stale.append(path.name)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    if stale:
        raise SystemExit(f"stale or missing: {stale}")
    print(("checked " if args.check else "wrote ") + f"{len(outputs)} files under {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
