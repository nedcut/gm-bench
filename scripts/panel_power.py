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
import random
import sys
from itertools import combinations
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from analyze_publication_panel import holm_adjust, sign_flip_p_value  # noqa: E402
from model_tiers import t_two_sided_p  # noqa: E402

RESULTS_DIR = Path(__file__).resolve().parents[1] / "results" / "leaderboard"
EXACT_REFERENCE_SIMULATION_SEED = 2026072800


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


def load_reference_lift_cells(
    results_dir: Path,
    *,
    reference_agent: str = "pick-trader",
) -> tuple[dict[tuple[str, int], list[float]], dict[str, Any]]:
    """Load candidate-minus-reference episode lifts from one frozen panel.

    The scripted reference is deterministic and has one score per seed.
    Subtracting it before decomposition estimates the one-candidate variance
    used by the focused reference-only v3 analysis, rather than the two-model
    variance used by the older all-pairs planning path.
    """
    cells: dict[tuple[str, int], list[float]] = {}
    contracts: set[str] = set()
    panels: set[str] = set()
    for path in sorted(results_dir.glob("*.json")):
        payload = json.loads(path.read_text())
        run_info = payload.get("run_info") or {}
        model = str(run_info.get("model") or "")
        if not model:
            continue
        matches = [row for row in payload.get("baselines") or [] if row.get("agent") == reference_agent]
        if len(matches) != 1:
            raise SystemExit(f"{path.name} must contain exactly one {reference_agent!r} reference")
        reference_by_seed = {int(row["seed"]): float(row["final_score"]) for row in matches[0].get("episodes") or []}
        if not reference_by_seed:
            raise SystemExit(f"{path.name} has no {reference_agent!r} reference episodes")
        for episode in (payload.get("candidate") or {}).get("episodes") or []:
            seed = int(episode["seed"])
            if seed not in reference_by_seed:
                raise SystemExit(f"{path.name} candidate seed {seed} is absent from {reference_agent!r}")
            cells.setdefault((model, seed), []).append(float(episode["final_score"]) - reference_by_seed[seed])
        contract = (run_info.get("benchmark_contract") or {}).get("contract_fingerprint")
        panel = (run_info.get("seed_panel") or {}).get("sha256")
        if contract:
            contracts.add(str(contract))
        if panel:
            panels.add(str(panel))
    if not cells:
        raise SystemExit(f"no usable candidate/reference episodes under {results_dir}")
    if len(contracts) > 1:
        raise SystemExit("refusing to pool reference lifts across benchmark contracts")
    if len(panels) > 1:
        raise SystemExit("refusing to pool reference lifts across seed panels")
    return cells, {
        "contract_fingerprint": next(iter(contracts), None),
        "seed_panel_sha256": next(iter(panels), None),
        "reference_agent": reference_agent,
    }


def _wilson_interval(successes: int, trials: int, *, z: float = 1.96) -> tuple[float, float]:
    proportion = successes / trials
    denominator = 1.0 + z * z / trials
    center = (proportion + z * z / (2.0 * trials)) / denominator
    half_width = z * math.sqrt(proportion * (1.0 - proportion) / trials + z * z / (4.0 * trials * trials)) / denominator
    return center - half_width, center + half_width


def simulate_exact_reference_family_power(
    *,
    var_noise: float,
    var_interaction: float,
    var_seed: float,
    seeds: int,
    repeats: int,
    delta: float,
    family_size: int,
    alpha: float,
    trials: int,
    simulation_seed: int = EXACT_REFERENCE_SIMULATION_SEED,
) -> dict[str, Any]:
    """Simulate the analyzer's exact sign-flip plus Holm procedure.

    Power is the probability that *all* eight predeclared reference contrasts
    reject when every true lift is ``delta``. This familywise-all-reject target
    is stricter than average per-model power and directly matches the intended
    claim that each registered model clears the reference.
    """
    if not 2 <= seeds <= 20:
        raise ValueError("exact reference simulation requires 2..20 seeds")
    if repeats < 1 or family_size < 1 or trials < 1:
        raise ValueError("repeats, family_size, and trials must be positive")
    independent_seed_level_sd = math.sqrt(var_interaction + var_noise / repeats)
    shared_seed_sd = math.sqrt(var_seed)
    rng = random.Random(simulation_seed + seeds * 10 + repeats)
    all_rejected = 0
    rejected_total = 0
    for _ in range(trials):
        # `cells` are already candidate-minus-reference lifts. Their estimated
        # seed component therefore remains in each primary contrast; it does
        # not cancel again. One shared draw per seed carries the fitted
        # compound-symmetry covariance across the eight model contrasts, while
        # model-by-seed interaction and repeat-averaged noise remain
        # model-specific.
        shared_seed_effects = [rng.gauss(0.0, shared_seed_sd) for _seed in range(seeds)]
        raw_p_values = {
            f"model-{index}": float(
                sign_flip_p_value(
                    [
                        delta + shared_seed_effect + rng.gauss(0.0, independent_seed_level_sd)
                        for shared_seed_effect in shared_seed_effects
                    ]
                )
            )
            for index in range(family_size)
        }
        adjusted = holm_adjust(raw_p_values, family_size=family_size)
        rejected = sum(value <= alpha for value in adjusted.values())
        rejected_total += rejected
        all_rejected += rejected == family_size
    lower, upper = _wilson_interval(all_rejected, trials)
    return {
        "seeds": seeds,
        "repeats": repeats,
        "episodes_per_model": seeds * repeats,
        "familywise_all_reject_power": round(all_rejected / trials, 6),
        "familywise_all_reject_power_ci95": [round(lower, 6), round(upper, 6)],
        "marginal_rejection_power": round(rejected_total / (trials * family_size), 6),
    }


def build_exact_reference_report(
    cells: dict[tuple[str, int], list[float]],
    *,
    delta: float = 40.0,
    alpha: float = 0.05,
    family_size: int = 8,
    target_power: float = 0.80,
    min_seeds: int = 9,
    max_seeds: int = 20,
    max_repeats: int = 3,
    trials: int = 10_000,
    noise_variance_multiplier: float = 1.25,
    seed_variance_multiplier: float = 1.25,
    interaction_variance_fraction: float = 0.10,
) -> dict[str, Any]:
    """Compare exact allocations and select the cheapest sensitivity-robust one."""
    components = decompose(cells)
    rows = []
    for seeds in range(min_seeds, max_seeds + 1):
        for repeats in range(1, max_repeats + 1):
            base = simulate_exact_reference_family_power(
                var_noise=components["var_noise"],
                var_interaction=components["var_interaction"],
                var_seed=components["var_seed"],
                seeds=seeds,
                repeats=repeats,
                delta=delta,
                family_size=family_size,
                alpha=alpha,
                trials=trials,
            )
            sensitivity = simulate_exact_reference_family_power(
                var_noise=components["var_noise"] * noise_variance_multiplier,
                var_interaction=max(
                    components["var_interaction"],
                    components["var_noise"] * interaction_variance_fraction,
                ),
                var_seed=components["var_seed"] * seed_variance_multiplier,
                seeds=seeds,
                repeats=repeats,
                delta=delta,
                family_size=family_size,
                alpha=alpha,
                trials=trials,
            )
            rows.append({**base, "sensitivity": sensitivity})
    qualifying = [row for row in rows if row["sensitivity"]["familywise_all_reject_power_ci95"][0] >= target_power]
    recommended = min(
        qualifying,
        key=lambda row: (row["episodes_per_model"], row["seeds"], row["repeats"]),
        default=None,
    )
    return {
        "method": "normal-parametric Monte Carlo evaluated by exact-enumeration-sign-flip plus Holm-Bonferroni",
        "simulation_seed": EXACT_REFERENCE_SIMULATION_SEED,
        "trials": trials,
        "historical_components": {
            "var_noise": round(components["var_noise"], 6),
            "sd_noise": round(math.sqrt(components["var_noise"]), 6),
            "var_interaction": round(components["var_interaction"], 6),
            "sd_interaction": round(math.sqrt(components["var_interaction"]), 6),
            "var_seed": round(components["var_seed"], 6),
            "sd_seed": round(math.sqrt(components["var_seed"]), 6),
        },
        "target_effect": delta,
        "target_effect_unit": "GM-Bench score points above pick-trader",
        "target_familywise_all_reject_power": target_power,
        "selection_rule": "smallest episodes/model whose sensitivity-power Wilson 95% lower bound is >= target",
        "sensitivity": {
            "noise_variance_multiplier": noise_variance_multiplier,
            "shared_seed_variance_multiplier": seed_variance_multiplier,
            "interaction_variance_floor_as_historical_noise_fraction": interaction_variance_fraction,
            "cross_model_covariance": (
                "compound symmetry: one shared residual lift-seed draw per seed; "
                "model-by-seed interaction and repeat-averaged noise are independent by model"
            ),
        },
        "family_size": family_size,
        "alpha": alpha,
        "allocations": rows,
        "recommended": recommended,
    }


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
    parser.add_argument(
        "--exact-reference-family",
        action="store_true",
        help="simulate the focused eight-model reference-only Holm family with the analyzer's exact test",
    )
    parser.add_argument("--family-size", type=int, default=8, help="registered reference-contrast family size")
    parser.add_argument("--target-power", type=float, default=0.80, help="required familywise all-reject power")
    parser.add_argument("--trials", type=int, default=10_000, help="deterministic Monte Carlo trials per allocation")
    parser.add_argument("--min-seeds", type=int, default=9)
    parser.add_argument("--max-seeds", type=int, default=20)
    parser.add_argument("--max-repeats", type=int, default=3)
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    args = parser.parse_args()

    if args.exact_reference_family:
        cells, context = load_reference_lift_cells(args.results_dir)
        report = build_exact_reference_report(
            cells,
            delta=args.delta,
            alpha=args.alpha,
            family_size=args.family_size,
            target_power=args.target_power,
            min_seeds=args.min_seeds,
            max_seeds=args.max_seeds,
            max_repeats=args.max_repeats,
            trials=args.trials,
        )
        report["context"] = context
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            recommended = report["recommended"]
            print(
                "exact reference-only design: "
                + (
                    f"{recommended['seeds']} seeds x {recommended['repeats']} repeats "
                    f"({recommended['episodes_per_model']} episodes/model), "
                    f"base power={recommended['familywise_all_reject_power']:.3f}; "
                    f"sensitivity power={recommended['sensitivity']['familywise_all_reject_power']:.3f} "
                    f"CI={recommended['sensitivity']['familywise_all_reject_power_ci95']}"
                    if recommended
                    else "no allocation clears the target power with its 95% simulation interval"
                )
            )
        return 0

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
