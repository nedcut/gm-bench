#!/usr/bin/env python3
"""Rank published model rows against each other using matched-seed pairing.

This is a diagnostic script, not part of the benchmark contract. It reads
committed leaderboard artifacts and rewrites nothing.

Why this exists
---------------
Every model in a panel runs the *same* seeds, and seed difficulty is a large
shared component of score variance -- some leagues are simply harder to manage
from than others. Comparing two models by whether their individual confidence
intervals overlap throws that pairing away and asks a much weaker question.
Non-overlapping intervals do imply a real difference, but overlapping intervals
do **not** imply the absence of one, and for a paired design the gap between
those two readings is large.

The harness already pairs candidate-vs-baseline (`paired.sign_flip_p_value`,
`paired.significant_at_95` appear in every artifact). This applies the same
method model-vs-model, which is the comparison a leaderboard actually makes.

What it reports
---------------
A partial order, not a ranking. Models that cannot be separated share a tier
letter; a model is placed above another only when the matched-seed evidence
supports it under the chosen multiple-comparison correction. "Not separable"
means exactly that -- not "equal".

Usage
-----
    python scripts/model_tiers.py
    python scripts/model_tiers.py --correction bonferroni --json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from itertools import combinations
from pathlib import Path
from statistics import mean, stdev
from typing import Any

RESULTS_DIR = Path(__file__).resolve().parents[1] / "results" / "leaderboard"


# --- statistics -------------------------------------------------------------
#
# Implemented here rather than pulled from scipy because the package declares no
# runtime dependencies and that is worth preserving for a diagnostic script.


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta function (Lentz's method)."""
    tiny = 1e-30
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for m in range(1, 201):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 3e-7:
            break
    return h


def _betai(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta function I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    front = math.exp(lbeta + a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def t_two_sided_p(t: float, df: int) -> float:
    """Two-sided p-value for a t statistic."""
    if df <= 0:
        return float("nan")
    if t == 0.0:
        return 1.0
    return _betai(df / 2.0, 0.5, df / (df + t * t))


def sign_test_p(diffs: list[float]) -> float:
    """Two-sided exact binomial p-value on the signs of paired differences."""
    nonzero = [d for d in diffs if d != 0]
    n = len(nonzero)
    if n == 0:
        return 1.0
    wins = sum(1 for d in nonzero if d > 0)
    extreme = max(wins, n - wins)
    tail = sum(math.comb(n, i) for i in range(extreme, n + 1))
    return min(1.0, 2.0 * tail / (2**n))


# --- artifact loading -------------------------------------------------------


def load_rows(results_dir: Path) -> tuple[dict[str, dict[int, float]], dict[str, Any]]:
    """Return per-seed mean scores per model, plus the shared run context.

    Rows are only comparable under an identical benchmark contract and seed
    panel. Mixing contracts would compare scores produced by different
    simulators, so a mismatch is refused rather than averaged over.
    """
    rows: dict[str, dict[int, float]] = {}
    fingerprints: dict[str, str] = {}
    panels: dict[str, str] = {}

    for path in sorted(results_dir.glob("*.json")):
        payload = json.loads(path.read_text())
        candidate = payload.get("candidate")
        run_info = payload.get("run_info", {})
        if not candidate or not candidate.get("episodes"):
            continue
        name = run_info.get("model") or path.stem
        by_seed: dict[int, list[float]] = {}
        for episode in candidate["episodes"]:
            by_seed.setdefault(int(episode["seed"]), []).append(float(episode["final_score"]))
        rows[name] = {seed: mean(scores) for seed, scores in by_seed.items()}
        contract = run_info.get("benchmark_contract", {})
        fingerprints[name] = contract.get("contract_fingerprint", "unknown")
        panels[name] = run_info.get("seed_panel", {}).get("sha256", "unknown")

    if not rows:
        raise SystemExit(f"no leaderboard artifacts with per-seed episodes found in {results_dir}")

    distinct_contracts = set(fingerprints.values())
    distinct_panels = set(panels.values())
    if len(distinct_contracts) > 1:
        raise SystemExit(
            "refusing to compare rows across benchmark contracts: "
            + ", ".join(f"{name}={fp}" for name, fp in sorted(fingerprints.items()))
        )
    if len(distinct_panels) > 1:
        raise SystemExit(
            "refusing to compare rows across seed panels: "
            + ", ".join(f"{name}={sha[:12]}" for name, sha in sorted(panels.items()))
        )

    context = {
        "contract_fingerprint": distinct_contracts.pop(),
        "seed_panel_sha256": distinct_panels.pop(),
    }
    return rows, context


# --- comparison -------------------------------------------------------------


def compare(rows: dict[str, dict[int, float]], correction: str) -> tuple[list[dict[str, Any]], float]:
    names = sorted(rows, key=lambda n: -mean(rows[n].values()))
    pairs = list(combinations(names, 2))
    results: list[dict[str, Any]] = []

    for high, low in pairs:
        seeds = sorted(set(rows[high]) & set(rows[low]))
        diffs = [rows[high][s] - rows[low][s] for s in seeds]
        n = len(diffs)
        if n < 3:
            continue
        diff_mean = mean(diffs)
        diff_sd = stdev(diffs)
        t = diff_mean / (diff_sd / math.sqrt(n)) if diff_sd else math.inf
        results.append(
            {
                "high": high,
                "low": low,
                "n_seeds": n,
                "mean_diff": round(diff_mean, 3),
                "paired_sd": round(diff_sd, 3),
                "t": round(t, 3),
                "p": t_two_sided_p(t, n - 1),
                "sign_p": sign_test_p(diffs),
                "seeds_won": sum(1 for d in diffs if d > 0),
            }
        )

    alpha = 0.05
    count = len(results)
    if correction == "bonferroni":
        for row in results:
            row["p_adj"] = min(1.0, row["p"] * count)
    elif correction == "holm":
        # Step-down: sort ascending, scale by remaining tests, enforce monotonicity.
        order = sorted(range(count), key=lambda i: results[i]["p"])
        running = 0.0
        for rank, idx in enumerate(order):
            adjusted = min(1.0, results[idx]["p"] * (count - rank))
            running = max(running, adjusted)
            results[idx]["p_adj"] = running
    else:
        for row in results:
            row["p_adj"] = row["p"]

    for row in results:
        row["separated"] = row["p_adj"] < alpha
        row["p"] = round(row["p"], 5)
        row["p_adj"] = round(row["p_adj"], 5)
        row["sign_p"] = round(row["sign_p"], 5)

    return results, alpha


def _maximal_cliques(nodes: list[str], adjacency: dict[str, set[str]]) -> list[set[str]]:
    """Bron-Kerbosch with pivoting. Cliques are mutually-inseparable groups."""
    cliques: list[set[str]] = []

    def expand(r: set[str], p: set[str], x: set[str]) -> None:
        if not p and not x:
            cliques.append(set(r))
            return
        pivot = max(p | x, key=lambda v: len(adjacency[v]))
        for v in list(p - adjacency[pivot]):
            expand(r | {v}, p & adjacency[v], x & adjacency[v])
            p = p - {v}
            x = x | {v}

    expand(set(), set(nodes), set())
    return cliques


def assign_tiers(names: list[str], results: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Compact letter display: models sharing a letter are not separable.

    Each maximal clique in the "not separable" graph becomes one tier. A model
    can carry more than one letter -- that is not a defect, it means the
    evidence genuinely places it in an overlap between groups.
    """
    adjacency: dict[str, set[str]] = {n: set() for n in names}
    separated = {(r["high"], r["low"]) for r in results if r["separated"]}
    for a, b in combinations(names, 2):
        if (a, b) not in separated and (b, a) not in separated:
            adjacency[a].add(b)
            adjacency[b].add(a)

    cliques = _maximal_cliques(names, adjacency)
    cliques.sort(key=lambda c: (-max(names.index(m) for m in c), min(names.index(m) for m in c)))
    cliques.sort(key=lambda c: min(names.index(m) for m in c))

    letters: dict[str, list[str]] = {n: [] for n in names}
    for index, clique in enumerate(cliques):
        letter = chr(ord("A") + index)
        for member in clique:
            letters[member].append(letter)
    return letters


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    parser.add_argument(
        "--correction",
        choices=("holm", "bonferroni", "none"),
        default="holm",
        help="multiple-comparison correction across all model pairs (default: holm)",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    args = parser.parse_args()

    rows, context = load_rows(args.results_dir)
    names = sorted(rows, key=lambda n: -mean(rows[n].values()))
    results, alpha = compare(rows, args.correction)
    tiers = assign_tiers(names, results)

    if args.json:
        print(
            json.dumps(
                {
                    "context": context,
                    "correction": args.correction,
                    "alpha": alpha,
                    "models": [
                        {
                            "model": n,
                            "mean_score": round(mean(rows[n].values()), 3),
                            "n_seeds": len(rows[n]),
                            "tiers": tiers[n],
                        }
                        for n in names
                    ],
                    "pairs": results,
                },
                indent=2,
            )
        )
        return 0

    print(f"contract {context['contract_fingerprint']}  seed panel {context['seed_panel_sha256'][:12]}")
    print(f"correction: {args.correction}  alpha: {alpha}\n")
    print(f"{'model':32} {'mean':>9} {'seeds':>6}  tier")
    for name in names:
        print(f"{name:32} {mean(rows[name].values()):9.2f} {len(rows[name]):6d}  {''.join(tiers[name])}")

    separated = [r for r in results if r["separated"]]
    print(f"\n{len(separated)}/{len(results)} pairs separated at alpha={alpha} ({args.correction})\n")
    print(f"{'comparison':56} {'diff':>8} {'t':>7} {'p_adj':>8} {'won':>6}")
    for row in sorted(results, key=lambda r: -abs(r["t"])):
        if not row["separated"]:
            continue
        label = f"{row['high']} > {row['low']}"
        print(
            f"{label:56} {row['mean_diff']:8.2f} {row['t']:7.2f} "
            f"{row['p_adj']:8.5f} {row['seeds_won']:3d}/{row['n_seeds']:<2d}"
        )

    print("\nModels sharing a tier letter are not separable by this panel.")
    print("That is a statement about the evidence, not a claim that they are equal.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
