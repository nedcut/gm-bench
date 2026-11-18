#!/usr/bin/env python3
"""The 2.1 behaviour diagnostic, on 2.2-draft pilot runs.

Replays each pilot ledger through the 2.2 engine (``AgenticEpisode22``; no
model calls, nothing written to the run), checks that every replayed final
score matches the run's own ``run.json``, and reports the measures of
``scripts/diagnose_v21_behavior.py`` per model, beside the same model's 2.1
figures from ``results/diagnostics/v21_behavior/behavior.json``.

The pilot plays public seeds, so nothing here is a panel result. The 2.1
figures are from the 32 private seeds; the two columns share a model and a
harness version, not seeds, so read a difference as a change in behaviour
only where it is large against the 2.1 spread. Two scripted policies are
played on the pilot's seeds under the 2.2 rules for scale.

Several run directories for one model (a pilot split to stay in budget) are
pooled.

Usage::

    python scripts/diagnose_v22_pilot.py ~/gmb-runs/v22-pilot/<run> [...] \\
        [--out results/diagnostics/v22_pilot/behavior.json]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "scripts"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import diagnose_v21_behavior as v21  # noqa: E402
import score_v3_candidates as candidates  # noqa: E402

from gm_bench.agentic.validate import EMPTY_PHASE_TOOLS  # noqa: E402
from gm_bench.v22 import scoring as score_v3  # noqa: E402
from gm_bench.v22.contract import BENCHMARK_VERSION  # noqa: E402
from gm_bench.v22.episode import AgenticEpisode22  # noqa: E402
from gm_bench.v22.rules import League22  # noqa: E402

OUT = ROOT / "results" / "diagnostics" / "v22_pilot" / "behavior.json"
BASELINE = ROOT / "results" / "diagnostics" / "v21_behavior" / "behavior.json"
SCRIPTED = ("pick-trader", "contend-preseason-1g")
FINAL_SEASON = v21.FINAL_SEASON


class _Probe(AgenticEpisode22):
    """``diagnose_v21_behavior._Probe``'s snapshots, on the 2.2 engine."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.phases: list[dict[str, Any]] = []
        self.calls: list[dict[str, Any]] = []
        self.roster_before_final_rollover: int | None = None
        super().__init__(*args, **kwargs)

    def _open_phase(self) -> None:
        super()._open_phase()
        if not self.phase_open:
            return
        league = self.league
        offers = league.current_offers
        self.phases.append(
            {
                "season": self.season_index,
                "phase": self.phase,
                "calls": [],
                "drafted": set(),
                "picks_at_open": len(league.user_team.draft_picks.get(self.season_index, [])),
                "live_offers": len(offers),
                "stale_offers": sum(1 for offer in offers.values() if v21._offer_stale(league, offer)),
            }
        )

    def _close_phase(self, ended_by: str) -> dict[str, Any]:
        phase = self.phases[-1]
        league, team = self.league, self.league.user_team
        phase["picks_at_close"] = len(team.draft_picks.get(self.season_index, []))
        phase["lineup"] = v21._lineup_snapshot(league, team, phase["drafted"] if self.phase == "draft" else None)
        if self.phase == "preseason" and self.season_index == FINAL_SEASON:
            phase["final_year_players"] = sum(1 for pid in team.roster if league.players[pid].contract_years == 1)
        if self.phase == "draft" and self.season_index == FINAL_SEASON:
            self.roster_before_final_rollover = len(team.roster)
        return super()._close_phase(ended_by)

    def _execute(self, name: str, arguments: Any) -> dict[str, Any]:
        args = arguments if isinstance(arguments, dict) else {}
        phase = self.phases[-1]
        roster = set(self.league.user_team.roster)
        reply = super()._execute(name, arguments)
        if name == "draft" and reply.get("ok"):
            phase["drafted"].update(set(self.league.user_team.roster) - roster)
        message = str(reply.get("message", ""))
        if not reply.get("ok"):
            message = v21._scrub_names(self.league, message)
        call = {
            "tool": name,
            "season": phase["season"],
            "phase": phase["phase"],
            "ok": bool(reply.get("ok")),
            "penalized": bool(reply.get("penalized")),
            "message": message,
            "years": args.get("years"),
            "gives_current_pick": self.season_index in (args.get("give_pick_seasons") or []),
            "whereabouts": None,
        }
        phase["calls"].append(call)
        self.calls.append(call)
        return reply


def measure_episode(episode_dir: Path, recorded: dict[str, Any]) -> dict[str, Any]:
    probe = _Probe.from_ledger(episode_dir / "ledger.jsonl", reopen=False)
    result = probe.result()
    if result.get("benchmark_version", BENCHMARK_VERSION) != BENCHMARK_VERSION:
        raise SystemExit(f"{episode_dir}: not a {BENCHMARK_VERSION} ledger")
    if abs(result["final_score"] - recorded["final_score"]) > 1e-6:
        raise SystemExit(f"{episode_dir}: replayed final score does not match run.json")
    phases = probe.phases
    if len(phases) != 4 * FINAL_SEASON:
        raise SystemExit(f"{episode_dir}: expected {4 * FINAL_SEASON} phases, replayed {len(phases)}")
    for phase in phases:
        phase["empty"] = {c["tool"] for c in phase["calls"]} <= EMPTY_PHASE_TOOLS
        phase["read_status"] = any(c["tool"] == "get_status" for c in phase["calls"])
    components = result["score_components"]
    terms = {g: sum(components[f"{name}_contribution"] for name in names) for g, names in v21.TERM_GROUPS.items()}
    terms["penalty"] = -components["protocol_penalty"]
    if abs(sum(terms.values()) - result["final_score"]) > 1e-3:
        raise SystemExit(f"{episode_dir}: score terms do not sum to the final score")
    return {
        "seed": result["seed"],
        "final_score": result["final_score"],
        "after_season_4": result["season_summaries"][FINAL_SEASON - 2]["score_after_season"],
        "terms": terms,
        "phases": phases,
        "calls": probe.calls,
        "roster_end": len(probe.league.user_team.roster),
        "roster_before_final_rollover": probe.roster_before_final_rollover,
    }


def _scripted(seeds: list[int]) -> dict[str, dict[str, float]]:
    scores = {
        name: {
            s: score_v3.score_team(lg, lg.user_team_id) for s in seeds for lg in [candidates.play(name, s, League22)]
        }
        for name in SCRIPTED
    }
    return {name: {str(seed): round(score, 3) for seed, score in by_seed.items()} for name, by_seed in scores.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("runs", nargs="+", type=Path, help="2.2-draft pilot run directories")
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    by_model: dict[str, list[dict[str, Any]]] = {}
    usage: dict[str, dict[str, float]] = {}
    sources = []
    for run_dir in (run.expanduser() for run in args.runs):
        run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        if run["contract"]["benchmark_version"] != BENCHMARK_VERSION or run["seasons"] != FINAL_SEASON:
            raise SystemExit(f"{run_dir}: not a {FINAL_SEASON}-season {BENCHMARK_VERSION} run")
        model = run["agent"].split(":", 1)[1].rsplit("/", 1)[-1]
        # Public-seed runs name episode directories by seed; --seeds-stdin runs by position.
        dirs = [run_dir / f"seed-{e['seed']}" for e in run["episodes"]]
        if not all(d.is_dir() for d in dirs):
            dirs = sorted(run_dir.glob("episode-*"))
        if len(dirs) != len(run["episodes"]):
            raise SystemExit(f"{run_dir}: {len(dirs)} episode directories, run.json has {len(run['episodes'])}")
        by_model.setdefault(model, []).extend(measure_episode(d, e) for d, e in zip(dirs, run["episodes"], strict=True))
        summary = run["agentic_summary"]
        block = usage.setdefault(model, {"episodes": 0, "api_equivalent_cost_usd": 0.0, "tool_calls": 0.0})
        block["episodes"] += len(dirs)
        block["api_equivalent_cost_usd"] += float(summary.get("api_equivalent_cost_usd") or 0.0)
        block["tool_calls"] += summary["mean_tool_calls_per_episode"] * len(dirs)
        sources.append(
            {
                "model": model,
                "run": run_dir.name,
                "harness": f"{run['harness']['name']} {run['harness'].get('version')}",
                "driver_commit": (run.get("driver") or {}).get("commit"),
                "agentic_fingerprint": run["contract"]["agentic_fingerprint"],
            }
        )
        print(f"{model:24s} {run_dir.name}: {len(dirs)} episodes replayed, scores match", file=sys.stderr)
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))["models"]
    seeds = sorted({e["seed"] for episodes in by_model.values() for e in episodes})
    scripted = _scripted(seeds)
    models = {}
    for model, episodes in by_model.items():
        summary = v21.model_summary(episodes)
        lifts = [e["final_score"] - scripted["pick-trader"][str(e["seed"])] for e in episodes]
        summary["seeds"] = [e["seed"] for e in episodes]
        summary["lift_over_pick_trader"] = {
            "mean": round(statistics.fmean(lifts), 2),
            "sd": round(statistics.stdev(lifts), 2) if len(lifts) > 1 else None,
        }
        summary["terms"] = {
            g: round(statistics.fmean(e["terms"][g] for e in episodes), 2) for g in episodes[0]["terms"]
        }
        cost = usage[model]
        summary["usage"] = {
            "api_equivalent_cost_usd": round(cost["api_equivalent_cost_usd"], 2),
            "api_equivalent_cost_per_episode": round(cost["api_equivalent_cost_usd"] / cost["episodes"], 2),
            "tool_calls_per_episode": round(cost["tool_calls"] / cost["episodes"], 1),
        }
        models[model] = {"pilot_2_2": summary, "panel_2_1": baseline.get(model)}
    report = {
        "contract": BENCHMARK_VERSION,
        "note": (
            "Public-seed pilot, not a panel. pilot_2_2 and panel_2_1 share a model and harness version, not "
            "seeds. The contract is an unpinned draft, so these are not publishable rows."
        ),
        "sources": sources,
        "seeds": seeds,
        "scripted_2_2": {
            name: {
                "mean_score": round(statistics.fmean(by_seed.values()), 2),
                "lift_over_pick_trader": round(
                    statistics.fmean(by_seed[s] - scripted["pick-trader"][s] for s in by_seed), 2
                ),
            }
            for name, by_seed in scripted.items()
        },
        "models": models,
        "penalized_rejections": v21.penalized_clusters({m: b["pilot_2_2"] for m, b in models.items()}),
    }
    for model, block in models.items():
        new, old = block["pilot_2_2"], block["panel_2_1"]
        for label, s in (("2.2 pilot", new), ("2.1 panel", old)):
            if s is None:
                continue
            e, r, h = s["empty_phases"], s["end_of_run"], s["status_habit"]
            print(
                f"{model:22s} {label}  n={s['episodes']:2d} score {s['mean_final_score']:6.1f}  empty {e['rate']:.3f}  "
                f"no status {h['rate_ended_without_status_read']:.2f}  end roster {r['roster_at_end']:5.2f}  "
                f"penalized/ep {s['rejections']['penalized_per_episode']:.2f}  "
                f"draft gap {s['lineups']['mean_gap_to_default_at_draft_close']:+.2f}"
            )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
