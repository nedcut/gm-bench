#!/usr/bin/env python3
"""Estimate panel power and pick the seeds-versus-repeats split for a model panel.

A published panel spends a fixed number of episodes per model, because an
episode is an API bill. That budget can be spent on more *seeds* or on more
*repeats* per seed, and the two are not equivalent for the comparison a
leaderboard actually makes.

Write an episode score as

    score(model, seed, repeat) = mu + model + seed + (model x seed) + noise

A matched-seed paired contrast differences two models on the same seed, which
cancels the `seed` term outright -- that is the whole point of running every
model on one panel. What survives is the model-by-seed interaction and the
per-episode noise, so for `n` seeds at `r` repeats the paired mean difference
has variance

    Var(mean difference) = (2 * var_interaction + 2 * var_noise / r) / n

Now hold the episode budget `E = n * r` fixed and substitute `n = E / r`:

    Var = (2 * r * var_interaction + 2 * var_noise) / E

Only the first term depends on `r`, and it *increases* with `r`. So whenever
the interaction component is nonzero, `r = 1` with the widest possible seed
panel minimises the variance of every pairwise model contrast, at identical
cost. Repeats buy a better estimate of one seed; seeds buy independent draws of
the thing that actually varies between models.

That does not make repeats worthless -- they are the only way to measure
within-seed sampling noise, which is a reported quantity in its own right and
is what `within_seed_score_stddev` carries today. The recommendation this tool
prints is therefore an allocation for *discrimination*, and a panel that also
wants a noise estimate should keep repeats on a small subset of seeds rather
than across the whole panel.

Power figures default to a single pairwise two-sided test. The publication
tiering tool (`scripts/model_tiers.py`) defaults to Holm across every model
pair, which is a much harder bar: pass `--correction holm` (or `bonferroni`)
when sizing a panel for that analysis. Both corrections use the first-step /
Bonferroni threshold `alpha / C(models, 2)` for planning.

This reads committed artifacts and writes nothing. It is a planning tool: it
does not change a contract, a preset, or a published number, and running it
authorises no spend.

Usage:

    python3 scripts/panel_power.py
    python3 scripts/panel_power.py --budget 24 --delta 40 --json
    python3 scripts/panel_power.py --correction holm --budget 96
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from itertools import combinations
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from model_tiers import t_two_sided_p  # noqa: E402

RESULTS_DIR = Path(__file__).resolve().parents[1] / "results" / "leaderboard"


# --- distribution helpers ---------------------------------------------------


def normal_cdf(z: float) -> float:
    """Standard normal CDF, exact to double precision via erf."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def t_critical(alpha: float, df: int) -> float:
    """Two-sided critical value: the t with `t_two_sided_p(t, df) == alpha`.

    Found by bisection on `t_two_sided_p`, which is monotonically decreasing in
    |t|. Inverting the same function the significance tests use keeps the power
    calculation consistent with them rather than approximately consistent.
    """
    if df <= 0:
        return float("nan")
    low, high = 0.0, 1000.0
    for _ in range(200):
        mid = (low + high) / 2.0
        if t_two_sided_p(mid, df) > alpha:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


# --- variance decomposition -------------------------------------------------


def decompose(cells: dict[tuple[str, int], list[float]]) -> dict[str, float]:
    """Balanced two-way decomposition of episode scores into variance components.

    `cells` maps (model, seed) to that cell's repeat scores. Returns the noise,
    interaction, and seed components. Interaction and seed are method-of-moments
    estimates and are clamped at zero: a negative variance estimate means the
    component is not distinguishable from zero at this panel size, not that it
    is negative.
    """
    models = sorted({model for model, _ in cells})
    seeds = sorted({seed for _, seed in cells})
    # A uniform repeat count across the cells that *exist* is not balance: a
    # model missing one seed entirely still passes that check, and the mean
    # computations below index the full cross-product. Refuse explicitly rather
    # than crashing with a KeyError two lines later.
    missing = [(model, seed) for model in models for seed in seeds if (model, seed) not in cells]
    if missing:
        shown = ", ".join(f"{model}@seed{seed}" for model, seed in missing[:5])
        more = f" (+{len(missing) - 5} more)" if len(missing) > 5 else ""
        raise SystemExit(f"panel is unbalanced: every model must have every seed; missing {shown}{more}")
    counts = {len(values) for values in cells.values()}
    if len(counts) != 1:
        raise SystemExit("panel is unbalanced: every (model, seed) cell must have the same repeat count")
    repeats = counts.pop()
    n_models, n_seeds = len(models), len(seeds)
    if n_models < 2 or n_seeds < 2:
        raise SystemExit("need at least two models and two seeds to decompose variance")

    cell_mean = {key: sum(values) / len(values) for key, values in cells.items()}
    grand = sum(cell_mean.values()) / len(cell_mean)
    model_mean = {m: sum(cell_mean[(m, s)] for s in seeds) / n_seeds for m in models}
    seed_mean = {s: sum(cell_mean[(m, s)] for m in models) / n_models for s in seeds}

    # Within-cell (pure episode-to-episode) noise.
    if repeats > 1:
        ss_error = sum(sum((v - cell_mean[key]) ** 2 for v in values) for key, values in cells.items())
        var_noise = ss_error / (n_models * n_seeds * (repeats - 1))
    else:
        # With one repeat per cell the noise and interaction terms are not
        # separately identified; report noise as zero and let it fold into the
        # interaction estimate, which stays conservative for allocation.
        var_noise = 0.0

    ss_interaction = repeats * sum(
        (cell_mean[(m, s)] - model_mean[m] - seed_mean[s] + grand) ** 2 for m in models for s in seeds
    )
    ms_interaction = ss_interaction / ((n_models - 1) * (n_seeds - 1))
    var_interaction = max(0.0, (ms_interaction - var_noise) / repeats)

    ss_seed = n_models * repeats * sum((seed_mean[s] - grand) ** 2 for s in seeds)
    ms_seed = ss_seed / (n_seeds - 1)
    var_seed = max(0.0, (ms_seed - ms_interaction) / (n_models * repeats))

    return {
        "var_noise": var_noise,
        "var_interaction": var_interaction,
        "var_seed": var_seed,
        "models": n_models,
        "seeds": n_seeds,
        "repeats": repeats,
    }


def paired_se(var_noise: float, var_interaction: float, seeds: int, repeats: int) -> float:
    """Standard error of the mean paired difference between two models."""
    if seeds < 1 or repeats < 1:
        return float("inf")
    return math.sqrt((2.0 * var_interaction + 2.0 * var_noise / repeats) / seeds)


def power(delta: float, se: float, df: int, alpha: float) -> float:
    """Probability a true difference `delta` clears a two-sided test at `alpha`.

    Normal approximation to the noncentral t, evaluated at the exact t critical
    value for `df`. Slightly conservative at small df, which is the safe
    direction for a tool whose output gates spending.
    """
    if se <= 0 or df <= 0:
        return float("nan")
    crit = t_critical(alpha, df)
    ncp = abs(delta) / se
    return normal_cdf(ncp - crit) + normal_cdf(-ncp - crit)


def allocations(budget: int) -> list[tuple[int, int]]:
    """Every (seeds, repeats) split of a fixed per-model episode budget."""
    return [(budget // r, r) for r in range(1, budget + 1) if budget % r == 0 and budget // r >= 2]


def n_pairs(n_models: int) -> int:
    """Number of unordered model pairs in an all-pairs comparison."""
    return n_models * (n_models - 1) // 2


def comparison_alpha(alpha: float, correction: str, pairs: int) -> float:
    """Per-contrast alpha under the named multiple-comparison correction.

    Holm and Bonferroni share the same first-step threshold `alpha / pairs`.
    That is the right planning alpha when sizing for the full all-pairs
    analysis `model_tiers.py` runs by default. Later Holm steps are less
    stringent, so this is slightly conservative for easier pairs.
    """
    if correction == "none":
        return alpha
    if correction not in {"holm", "bonferroni"}:
        raise SystemExit(f"unknown correction {correction!r}; expected none, holm, or bonferroni")
    if pairs < 1:
        raise SystemExit("need at least one model pair for a multiple-comparison correction")
    return alpha / pairs


# --- artifact loading -------------------------------------------------------


def load_cells(results_dir: Path) -> tuple[dict[tuple[str, int], list[float]], dict[str, Any]]:
    """Load per-episode scores keyed by (model, seed), refusing to mix contracts.

    Mirrors the discipline in `model_tiers.load_rows`: scores from different
    simulators or different seed panels are not comparable at any sample size,
    so pooling them silently would be worse than refusing.
    """
    cells: dict[tuple[str, int], list[float]] = {}
    contracts: dict[str, str] = {}
    panels: dict[str, str] = {}
    for path in sorted(results_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text())
        except json.JSONDecodeError:
            print(f"skipping unparseable {path.name}", file=sys.stderr)
            continue
        run_info = payload.get("run_info") or {}
        model = run_info.get("model")
        if not model:
            continue
        candidate = payload.get("candidate") or payload
        episodes = candidate.get("episodes") or []
        if not episodes:
            continue
        contract = (run_info.get("benchmark_contract") or {}).get("contract_fingerprint")
        panel = (run_info.get("seed_panel") or {}).get("sha256")
        if contract:
            contracts[str(model)] = str(contract)
        if panel:
            panels[str(model)] = str(panel)
        for episode in episodes:
            seed = episode.get("seed")
            score = episode.get("final_score")
            if seed is None or score is None:
                continue
            cells.setdefault((str(model), int(seed)), []).append(float(score))

    if not cells:
        raise SystemExit(f"no usable episodes under {results_dir}")
    distinct_contracts = set(contracts.values())
    if len(distinct_contracts) > 1:
        raise SystemExit(
            "refusing to pool across benchmark contracts: "
            + ", ".join(f"{name}={sha[:12]}" for name, sha in sorted(contracts.items()))
        )
    distinct_panels = set(panels.values())
    if len(distinct_panels) > 1:
        raise SystemExit(
            "refusing to pool across seed panels: "
            + ", ".join(f"{name}={sha[:12]}" for name, sha in sorted(panels.items()))
        )
    context = {
        "contract_fingerprint": distinct_contracts.pop() if distinct_contracts else None,
        "seed_panel_sha256": distinct_panels.pop() if distinct_panels else None,
    }
    return cells, context


def observed_pair_gaps(cells: dict[tuple[str, int], list[float]]) -> list[float]:
    """Absolute mean gaps between every model pair, for effect-size context."""
    models = sorted({m for m, _ in cells})
    means = {
        m: sum(sum(v) / len(v) for (mm, _), v in cells.items() if mm == m) / len({s for mm, s in cells if mm == m})
        for m in models
    }
    return sorted((abs(means[a] - means[b]) for a, b in combinations(models, 2)), reverse=True)


# --- reporting --------------------------------------------------------------


def build_report(
    cells: dict[tuple[str, int], list[float]],
    budget: int,
    delta: float,
    alpha: float,
    *,
    correction: str = "none",
    pairs: int | None = None,
) -> dict[str, Any]:
    """Assemble the full allocation report for one budget and target effect size."""
    components = decompose(cells)
    var_noise = components["var_noise"]
    var_interaction = components["var_interaction"]
    pair_count = n_pairs(int(components["models"])) if pairs is None else pairs
    test_alpha = comparison_alpha(alpha, correction, pair_count)
    rows = []
    for seeds, repeats in allocations(budget):
        se = paired_se(var_noise, var_interaction, seeds, repeats)
        rows.append(
            {
                "seeds": seeds,
                "repeats": repeats,
                "paired_se": round(se, 3),
                "power": round(power(delta, se, seeds - 1, test_alpha), 4),
                "min_detectable_delta": round(t_critical(test_alpha, seeds - 1) * se, 2),
            }
        )
    best = max(rows, key=lambda row: (row["power"], -row["repeats"])) if rows else None
    return {
        "components": {
            "var_noise": round(var_noise, 3),
            "sd_noise": round(math.sqrt(var_noise), 3),
            "var_interaction": round(var_interaction, 3),
            "sd_interaction": round(math.sqrt(var_interaction), 3),
            "var_seed": round(components["var_seed"], 3),
            "sd_seed": round(math.sqrt(components["var_seed"]), 3),
        },
        "panel": {
            "models": components["models"],
            "seeds": components["seeds"],
            "repeats": components["repeats"],
        },
        "budget_per_model": budget,
        "target_delta": delta,
        "alpha": alpha,
        "correction": correction,
        "pairs": pair_count,
        "test_alpha": test_alpha,
        "allocations": rows,
        "recommended": best,
        "observed_pair_gaps": [round(g, 2) for g in observed_pair_gaps(cells)],
    }


def render(report: dict[str, Any]) -> str:
    """Format a report as the human-readable table printed by the CLI."""
    lines: list[str] = []
    panel = report["panel"]
    components = report["components"]
    lines.append(
        f"observed panel: {panel['models']} models x {panel['seeds']} seeds x {panel['repeats']} repeats"
        f"  ({panel['seeds'] * panel['repeats']} episodes/model)"
    )
    lines.append("")
    lines.append("variance components (score points)")
    lines.append(f"  seed difficulty      sd = {components['sd_seed']:8.2f}   cancelled by matched-seed pairing")
    lines.append(
        f"  model x seed         sd = {components['sd_interaction']:8.2f}   survives pairing, scales with seeds"
    )
    lines.append(
        f"  within-seed noise    sd = {components['sd_noise']:8.2f}   survives pairing, scales with seeds x repeats"
    )
    lines.append("")
    correction = report.get("correction", "none")
    test_alpha = report.get("test_alpha", report["alpha"])
    pairs = report.get("pairs")
    if correction == "none":
        alpha_note = f"two-sided alpha={report['alpha']} (single pairwise test)"
    else:
        alpha_note = f"two-sided alpha={report['alpha']}, {correction} over {pairs} pairs (test alpha={test_alpha:.6g})"
    lines.append(
        f"allocation of {report['budget_per_model']} episodes/model"
        f"   (power to detect {report['target_delta']:.0f} points, {alpha_note})"
    )
    lines.append(f"  {'seeds':>6} {'repeats':>8} {'paired SE':>10} {'min. detectable':>16} {'power':>8}")
    for row in report["allocations"]:
        marker = "  <-- best" if row is report["recommended"] else ""
        lines.append(
            f"  {row['seeds']:6} {row['repeats']:8} {row['paired_se']:10.2f}"
            f" {row['min_detectable_delta']:16.1f} {row['power']:8.3f}{marker}"
        )
    gaps = report["observed_pair_gaps"]
    if gaps:
        lines.append("")
        lines.append(
            f"observed pairwise gaps: max {gaps[0]:.1f}, median {gaps[len(gaps) // 2]:.1f}, min {gaps[-1]:.1f}"
        )
    lines.append("")
    if correction == "none":
        lines.append(
            "Powers above are for one pairwise test. scripts/model_tiers.py defaults to Holm "
            "across every model pair; re-run with --correction holm when sizing for that analysis."
        )
    lines.append("Repeats still measure within-seed sampling noise, which pairing cannot recover.")
    lines.append("Keep them on a subset of seeds if that estimate is wanted alongside discrimination.")
    return "\n".join(lines)


def main() -> int:
    """CLI entry point: load artifacts, decompose, and print the allocation table."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    parser.add_argument(
        "--budget",
        type=int,
        default=None,
        help="episodes per model to allocate (default: the observed panel's own budget)",
    )
    parser.add_argument("--delta", type=float, default=40.0, help="score difference to power for (default: 40)")
    parser.add_argument("--alpha", type=float, default=0.05, help="two-sided significance level (default: 0.05)")
    parser.add_argument(
        "--correction",
        choices=("none", "holm", "bonferroni"),
        default="none",
        help="multiple-comparison correction for power (default: none; use holm to match model_tiers.py)",
    )
    parser.add_argument(
        "--pairs",
        type=int,
        default=None,
        help="pair count for --correction (default: C(models, 2) from the loaded panel)",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    args = parser.parse_args()

    cells, context = load_cells(args.results_dir)
    components = decompose(cells)
    budget = args.budget or int(components["seeds"] * components["repeats"])
    report = build_report(
        cells,
        budget,
        args.delta,
        args.alpha,
        correction=args.correction,
        pairs=args.pairs,
    )
    report["context"] = context

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(render(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
