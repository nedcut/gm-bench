"""Tests for scripts/panel_power.py.

The variance decomposition and the power calculation are the two pieces that
cannot be checked by reading them, so both are validated against an independent
method: the decomposition against synthetic data with known components, and the
power function against Monte Carlo simulation of the test it is predicting.
"""

from __future__ import annotations

import importlib.util
import json
import math
import random
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "panel_power", Path(__file__).resolve().parents[1] / "scripts" / "panel_power.py"
)
assert _SPEC and _SPEC.loader
panel_power = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(panel_power)


def _synthetic_cells(
    *,
    models: int,
    seeds: int,
    repeats: int,
    sd_seed: float,
    sd_interaction: float,
    sd_noise: float,
    rng: random.Random,
) -> dict[tuple[str, int], list[float]]:
    """Build a balanced panel with known seed, interaction, and noise components."""
    seed_effect = {s: rng.gauss(0.0, sd_seed) for s in range(seeds)}
    cells: dict[tuple[str, int], list[float]] = {}
    for m in range(models):
        model_effect = rng.gauss(0.0, 30.0)
        for s in range(seeds):
            interaction = rng.gauss(0.0, sd_interaction) if sd_interaction else 0.0
            base = 200.0 + model_effect + seed_effect[s] + interaction
            cells[(f"m{m}", s)] = [base + rng.gauss(0.0, sd_noise) for _ in range(repeats)]
    return cells


# --- variance decomposition -------------------------------------------------


def test_decompose_recovers_known_components() -> None:
    """Method-of-moments estimates should land near the generating parameters."""
    rng = random.Random(20260726)
    cells = _synthetic_cells(models=8, seeds=40, repeats=4, sd_seed=25.0, sd_interaction=15.0, sd_noise=50.0, rng=rng)
    got = panel_power.decompose(cells)
    assert math.sqrt(got["var_noise"]) == pytest.approx(50.0, rel=0.10)
    assert math.sqrt(got["var_interaction"]) == pytest.approx(15.0, rel=0.35)
    assert math.sqrt(got["var_seed"]) == pytest.approx(25.0, rel=0.40)


def test_absent_interaction_is_clamped_to_zero_not_negative() -> None:
    """A component that is not distinguishable from zero must report as zero."""
    rng = random.Random(7)
    cells = _synthetic_cells(models=6, seeds=10, repeats=3, sd_seed=20.0, sd_interaction=0.0, sd_noise=45.0, rng=rng)
    got = panel_power.decompose(cells)
    assert got["var_interaction"] == 0.0
    assert math.sqrt(got["var_noise"]) == pytest.approx(45.0, rel=0.15)


def test_unbalanced_panel_is_refused() -> None:
    """Cells with differing repeat counts must be refused, not averaged over."""
    cells = {("a", 1): [1.0, 2.0], ("a", 2): [1.0], ("b", 1): [1.0, 2.0], ("b", 2): [3.0, 4.0]}
    with pytest.raises(SystemExit, match="unbalanced"):
        panel_power.decompose(cells)


# --- the allocation claim ---------------------------------------------------


def test_more_seeds_never_loses_at_fixed_budget() -> None:
    """The claim the tool exists to make, checked across the whole split grid."""
    rows = [
        (seeds, repeats, panel_power.paired_se(2500.0, 200.0, seeds, repeats))
        for seeds, repeats in panel_power.allocations(48)
    ]
    widest = min(rows, key=lambda row: row[1])
    assert widest[1] == 1
    # Standard error is monotonically non-increasing as seeds replace repeats.
    by_seeds = sorted(rows, key=lambda row: row[0])
    ses = [row[2] for row in by_seeds]
    assert ses == sorted(ses, reverse=True)


def test_with_zero_interaction_the_split_does_not_change_standard_error() -> None:
    """Without interaction, only degrees of freedom differ -- worth stating explicitly.

    This is the regime the committed panel is actually in, so the tool must not
    be read as promising an SE improvement it cannot deliver there.
    """
    a = panel_power.paired_se(2500.0, 0.0, seeds=24, repeats=1)
    b = panel_power.paired_se(2500.0, 0.0, seeds=8, repeats=3)
    assert a == pytest.approx(b)
    # ...but power still improves, purely from degrees of freedom.
    wide = panel_power.power(40.0, a, df=23, alpha=0.05)
    narrow = panel_power.power(40.0, b, df=7, alpha=0.05)
    assert wide > narrow


# --- power, checked against simulation --------------------------------------


@pytest.mark.parametrize("delta,seeds", [(40.0, 24), (25.0, 16), (60.0, 12)])
def test_power_agrees_with_monte_carlo(delta: float, seeds: int) -> None:
    """Validate the analytic power against simulating the paired t-test itself.

    The analytic form uses a normal approximation to the noncentral t evaluated
    at the exact t critical value, so it should track simulation closely and err
    on the conservative side.
    """
    sd_diff = 75.0
    se = sd_diff / math.sqrt(seeds)
    analytic = panel_power.power(delta, se, df=seeds - 1, alpha=0.05)

    rng = random.Random(4242)
    crit = panel_power.t_critical(0.05, seeds - 1)
    trials, rejected = 20000, 0
    for _ in range(trials):
        draws = [rng.gauss(delta, sd_diff) for _ in range(seeds)]
        mean = sum(draws) / seeds
        var = sum((d - mean) ** 2 for d in draws) / (seeds - 1)
        t = mean / math.sqrt(var / seeds)
        if abs(t) > crit:
            rejected += 1
    simulated = rejected / trials

    assert analytic == pytest.approx(simulated, abs=0.05)
    assert analytic <= simulated + 0.02, "analytic power should not overstate simulated power"


def test_t_critical_inverts_the_significance_test() -> None:
    """The critical value must round-trip through the p-value function it gates."""
    for df in (5, 7, 23, 47):
        crit = panel_power.t_critical(0.05, df)
        assert panel_power.t_two_sided_p(crit, df) == pytest.approx(0.05, abs=1e-6)
    # Textbook value: two-sided 5% at df=7.
    assert panel_power.t_critical(0.05, 7) == pytest.approx(2.364624, abs=1e-4)


def test_power_rises_with_seeds_and_effect_size() -> None:
    """Both levers must move power in the expected direction."""
    base = panel_power.power(40.0, panel_power.paired_se(2500.0, 100.0, 12, 1), df=11, alpha=0.05)
    more_seeds = panel_power.power(40.0, panel_power.paired_se(2500.0, 100.0, 48, 1), df=47, alpha=0.05)
    bigger = panel_power.power(80.0, panel_power.paired_se(2500.0, 100.0, 12, 1), df=11, alpha=0.05)
    assert more_seeds > base
    assert bigger > base


# --- multiple-comparison correction -----------------------------------------


def test_comparison_alpha_matches_model_tiers_first_step() -> None:
    """Holm/Bonferroni planning alpha is alpha / C(models, 2), matching model_tiers."""
    assert panel_power.n_pairs(8) == 28
    assert panel_power.comparison_alpha(0.05, "none", 28) == 0.05
    assert panel_power.comparison_alpha(0.05, "holm", 28) == pytest.approx(0.05 / 28)
    assert panel_power.comparison_alpha(0.05, "bonferroni", 28) == pytest.approx(0.05 / 28)


def test_holm_correction_lowers_reported_power() -> None:
    """Sizing under Holm must not reuse the optimistic single-test power figures."""
    rng = random.Random(11)
    cells = _synthetic_cells(models=8, seeds=8, repeats=3, sd_seed=13.0, sd_interaction=0.0, sd_noise=53.0, rng=rng)
    plain = panel_power.build_report(cells, budget=24, delta=40.0, alpha=0.05, correction="none")
    holm = panel_power.build_report(cells, budget=24, delta=40.0, alpha=0.05, correction="holm")
    assert holm["pairs"] == 28
    assert holm["test_alpha"] == pytest.approx(0.05 / 28)
    assert holm["recommended"]["power"] < plain["recommended"]["power"]
    assert holm["recommended"]["min_detectable_delta"] > plain["recommended"]["min_detectable_delta"]


def test_render_warns_when_correction_is_none() -> None:
    """Default single-test output must point operators at --correction holm."""
    rng = random.Random(3)
    cells = _synthetic_cells(models=4, seeds=4, repeats=2, sd_seed=10.0, sd_interaction=0.0, sd_noise=40.0, rng=rng)
    text = panel_power.render(panel_power.build_report(cells, budget=8, delta=40.0, alpha=0.05))
    assert "--correction holm" in text
    assert "single pairwise test" in text


# --- artifact loading discipline --------------------------------------------


def _write(tmp_path: Path, name: str, fingerprint: str, panel: str) -> None:
    """Write a minimal artifact carrying a given contract fingerprint and panel."""
    (tmp_path / f"{name}.json").write_text(
        json.dumps(
            {
                "run_info": {
                    "model": name,
                    "benchmark_contract": {"contract_fingerprint": fingerprint},
                    "seed_panel": {"sha256": panel},
                },
                "candidate": {"episodes": [{"seed": 1, "final_score": 1.0}]},
            }
        )
    )


def test_refuses_to_pool_across_contracts(tmp_path: Path) -> None:
    """Scores from different simulators are not comparable at any sample size."""
    _write(tmp_path, "old", "aaaaaaaaaaaaaaaa", "same-panel")
    _write(tmp_path, "new", "bbbbbbbbbbbbbbbb", "same-panel")
    with pytest.raises(SystemExit, match="across benchmark contracts"):
        panel_power.load_cells(tmp_path)


def test_refuses_to_pool_across_seed_panels(tmp_path: Path) -> None:
    """Public and private panels must never be silently pooled."""
    _write(tmp_path, "public", "aaaaaaaaaaaaaaaa", "panel-one")
    _write(tmp_path, "private", "aaaaaaaaaaaaaaaa", "panel-two")
    with pytest.raises(SystemExit, match="across seed panels"):
        panel_power.load_cells(tmp_path)


def test_committed_panel_reports_the_expected_shape() -> None:
    """Guard the real artifacts against a silent change in panel geometry."""
    cells, _ = panel_power.load_cells(panel_power.RESULTS_DIR)
    got = panel_power.decompose(cells)
    assert got["models"] == 8
    assert got["seeds"] == 8
    assert got["repeats"] == 3
    # Within-seed sampling noise dominates seed difficulty on this panel.
    assert got["var_noise"] > got["var_seed"]


def test_committed_reference_lifts_recover_one_candidate_variance() -> None:
    cells, context = panel_power.load_reference_lift_cells(panel_power.RESULTS_DIR)
    got = panel_power.decompose(cells)

    assert context["reference_agent"] == "pick-trader"
    assert got["models"] == 8
    assert got["seeds"] == 8
    assert got["repeats"] == 3
    assert got["var_noise"] == pytest.approx(2850.1698028541664)
    assert got["var_interaction"] == 0.0
    assert got["var_seed"] == pytest.approx(3770.478398572821)


def test_exact_reference_simulation_carries_shared_seed_covariance() -> None:
    result = panel_power.simulate_exact_reference_family_power(
        var_noise=0.0,
        var_interaction=0.0,
        var_seed=10_000.0,
        seeds=9,
        repeats=1,
        delta=40.0,
        family_size=8,
        alpha=0.05,
        trials=200,
    )

    # With no model-specific variance, all eight contrasts receive the same
    # per-seed lift vector and therefore always reject or fail together.
    assert result["marginal_rejection_power"] == result["familywise_all_reject_power"]


def test_exact_reference_simulation_is_deterministic_and_selects_by_sensitivity() -> None:
    cells = _synthetic_cells(
        models=8,
        seeds=8,
        repeats=3,
        sd_seed=5.0,
        sd_interaction=0.0,
        sd_noise=10.0,
        rng=random.Random(88),
    )
    first = panel_power.build_exact_reference_report(
        cells,
        delta=100.0,
        min_seeds=9,
        max_seeds=10,
        max_repeats=2,
        trials=100,
    )
    second = panel_power.build_exact_reference_report(
        cells,
        delta=100.0,
        min_seeds=9,
        max_seeds=10,
        max_repeats=2,
        trials=100,
    )

    assert first == second
    assert first["recommended"]["seeds"] == 9
    assert first["recommended"]["repeats"] == 1
    assert first["recommended"]["episodes_per_model"] == 9
    assert first["selection_rule"].startswith("smallest episodes/model")


def test_incomplete_cross_product_is_refused() -> None:
    """A uniform repeat count across present cells is not balance.

    A model missing one seed entirely passes the repeat-count check, but the
    decomposition indexes the full cross-product -- so without an explicit
    guard this raised KeyError instead of the clean refusal the function
    otherwise promises.
    """
    cells = {("a", 1): [1.0, 2.0], ("a", 2): [3.0, 4.0], ("b", 1): [5.0, 6.0]}
    with pytest.raises(SystemExit, match="every model must have every seed"):
        panel_power.decompose(cells)
