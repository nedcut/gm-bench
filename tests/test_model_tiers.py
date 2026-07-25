"""Tests for the paired model-tiering diagnostic.

The statistics in `scripts/model_tiers.py` are hand-rolled because the package
declares no runtime dependencies, so they are checked against values from
reference implementations rather than trusted by inspection.
"""

from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "model_tiers", Path(__file__).resolve().parents[1] / "scripts" / "model_tiers.py"
)
assert _SPEC and _SPEC.loader
model_tiers = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(model_tiers)


@pytest.mark.parametrize(
    ("t", "df", "expected"),
    [
        # Cross-checked against Simpson integration of the t density (agreement
        # to ~1e-9); see test_t_p_value_agrees_with_numerical_integration, which
        # re-derives these independently rather than trusting the constants.
        (2.0, 7, 0.085619327),
        (2.364624, 7, 0.050000017),  # the 5% two-sided critical value at 7 df
        (5.0, 7, 0.001565278),
        (1.0, 30, 0.325308616),
        (0.5, 100, 0.618173566),
    ],
)
def test_t_two_sided_p_matches_reference(t: float, df: int, expected: float) -> None:
    assert model_tiers.t_two_sided_p(t, df) == pytest.approx(expected, abs=1e-7)


def test_t_p_value_agrees_with_numerical_integration() -> None:
    """Validate the continued-fraction beta against a wholly different method.

    The incomplete beta function is the one piece here that cannot be checked by
    reading it, so it is checked against Simpson integration of the Student t
    density -- an implementation that shares no code path with it.
    """

    def t_pdf(x: float, df: int) -> float:
        norm = math.exp(math.lgamma((df + 1) / 2) - math.lgamma(df / 2)) / math.sqrt(df * math.pi)
        return norm * (1 + x * x / df) ** (-(df + 1) / 2)

    def two_sided_by_quadrature(t: float, df: int, steps: int = 20_000) -> float:
        lo, hi = t, t + 400.0
        h = (hi - lo) / steps
        total = 0.0
        for i in range(steps + 1):
            weight = 1 if i in (0, steps) else (4 if i % 2 else 2)
            total += weight * t_pdf(lo + i * h, df)
        return 2 * total * h / 3

    for t, df in ((0.75, 5), (2.0, 7), (3.4, 12), (1.1, 40)):
        assert model_tiers.t_two_sided_p(t, df) == pytest.approx(two_sided_by_quadrature(t, df), rel=1e-6)


def test_t_p_value_is_symmetric_and_bounded() -> None:
    for t in (0.1, 1.3, 4.7):
        assert model_tiers.t_two_sided_p(t, 9) == pytest.approx(model_tiers.t_two_sided_p(-t, 9))
    assert model_tiers.t_two_sided_p(0.0, 9) == 1.0
    assert 0.0 < model_tiers.t_two_sided_p(50.0, 9) < 1e-9


def test_sign_test_matches_exact_binomial() -> None:
    # 8 of 8 in one direction: 2 * (1/256) = 0.0078125
    assert model_tiers.sign_test_p([1.0] * 8) == pytest.approx(0.0078125)
    # 7 of 8: 2 * (8 + 1)/256
    assert model_tiers.sign_test_p([1.0] * 7 + [-1.0]) == pytest.approx(0.0703125)
    # Even split is maximally unsurprising.
    assert model_tiers.sign_test_p([1.0] * 4 + [-1.0] * 4) == pytest.approx(1.0)
    # Zero differences are dropped, not counted as wins for either side.
    assert model_tiers.sign_test_p([0.0, 0.0, 1.0, 1.0]) == pytest.approx(0.5)


def test_holm_is_never_more_conservative_than_bonferroni() -> None:
    """Holm dominates Bonferroni: it must reject at least as many hypotheses."""
    rows = {
        "a": {1: 300.0, 2: 310.0, 3: 305.0, 4: 295.0},
        "b": {1: 250.0, 2: 255.0, 3: 248.0, 4: 252.0},
        "c": {1: 200.0, 2: 190.0, 3: 205.0, 4: 195.0},
    }
    holm, _ = model_tiers.compare(rows, "holm")
    bonf, _ = model_tiers.compare(rows, "bonferroni")
    assert sum(r["separated"] for r in holm) >= sum(r["separated"] for r in bonf)


def test_pairing_detects_a_difference_marginal_intervals_would_hide() -> None:
    """The whole point: shared seed difficulty swamps a real paired effect.

    Both models swing over a ~200 point range across seeds, so their individual
    spreads overlap almost completely. But `a` beats `b` on every single seed by
    a consistent margin, which is only visible once the seeds are paired.
    """
    seeds = range(1, 13)
    seed_effect = {s: 100.0 * s for s in seeds}
    rows = {
        "a": {s: seed_effect[s] + 30.0 for s in seeds},
        "b": {s: seed_effect[s] for s in seeds},
    }
    results, _ = model_tiers.compare(rows, "none")
    (pair,) = results
    assert pair["high"] == "a"
    assert pair["seeds_won"] == 12
    assert pair["separated"]


def test_tiers_group_models_that_do_not_separate() -> None:
    names = ["a", "b", "c"]
    results = [
        {"high": "a", "low": "b", "separated": False},
        {"high": "a", "low": "c", "separated": True},
        {"high": "b", "low": "c", "separated": False},
    ]
    tiers = model_tiers.assign_tiers(names, results)
    # a and b share a group; b and c share a group; a and c must not.
    assert set(tiers["a"]) & set(tiers["b"])
    assert set(tiers["b"]) & set(tiers["c"])
    assert not (set(tiers["a"]) & set(tiers["c"]))


def test_refuses_to_mix_benchmark_contracts(tmp_path: Path) -> None:
    """Scores from different simulators are not comparable at any n."""

    def write(name: str, fingerprint: str) -> None:
        (tmp_path / f"{name}.json").write_text(
            json.dumps(
                {
                    "run_info": {
                        "model": name,
                        "benchmark_contract": {"contract_fingerprint": fingerprint},
                        "seed_panel": {"sha256": "same-panel"},
                    },
                    "candidate": {"episodes": [{"seed": 1, "final_score": 1.0}]},
                }
            )
        )

    write("old", "aaaaaaaaaaaaaaaa")
    write("new", "bbbbbbbbbbbbbbbb")
    with pytest.raises(SystemExit, match="across benchmark contracts"):
        model_tiers.load_rows(tmp_path)
