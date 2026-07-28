# `sota-v3` statistical-design audit — blocked, 2026-07-28

This is a no-spend, pre-data design result. No provider or completion endpoint
was called, no private seeds were generated, and every execution and
publication authorization remains false. The initial 17-seed x 3-repeat freeze
draft was invalid and is superseded by this corrected audit.

## Claim and test

The intended fixed family contains eight predeclared
model-plus-compact-scaffold systems. Each primary contrast is the seed-paired
mean lift over deterministic `pick-trader`; the seed is the unit of inference.
Each model uses the analyzer's exact two-sided sign-flip test, with
Holm-Bonferroni across the eight contrasts at alpha 0.05. No model-to-model
tiers or ordinal ranking are supported.

The planning effect is +40 GM-Bench score points above `pick-trader`. Power is
the probability that **all eight** Holm-adjusted contrasts reject when every
true lift is +40. The predeclared target is 0.80 familywise-all-reject power.

## Corrections made during review

Two defects invalidated the earlier optimistic result:

1. The meet-in-the-middle exact sign-flip implementation counted assignments
   on the open complement interval's boundaries. For example, `[4, -4]`
   returned an impossible p-value of 1.5 instead of 1.0. The corrected
   implementation uses `bisect_right` at the lower boundary and `bisect_left`
   at the upper boundary, and now matches exhaustive enumeration in
   deterministic integer fuzz, zero-observed-statistic, and tied-boundary
   tests.
2. Candidate-minus-`pick-trader` lifts still contain a residual common seed
   component. The earlier simulation omitted it as if pairing had cancelled it
   twice. The corrected simulation includes the estimated shared lift-seed
   variance in every model/reference contrast.

## Evidence and covariance model

The committed frozen-v2 artifacts contain 8 models x 8 seeds x 3 repeats.
Decomposition of candidate-minus-`pick-trader` lifts gives:

- residual shared seed variance: `3770.478399` (SD `61.404221`);
- within-seed noise variance: `2850.169803` (SD `53.386982`);
- model-by-seed interaction variance: `0.0`, method-of-moments clamped.

The Monte Carlo model uses compound symmetry: for each simulated seed, one
normal residual lift-seed draw is shared by all eight models. Model-by-seed
interaction and repeat-averaged noise are independent by model. This carries
the fitted cross-model covariance instead of incorrectly simulating eight
independent tests. It is a disclosed planning assumption based on only eight
historical seeds, not a claim that the unseen v3 covariance is known.

Sensitivity multiplies both shared seed variance and noise variance by 1.25,
and imposes an interaction-variance floor equal to 10% of historical noise
variance.

## Corrected result: no qualifying allocation

Every allocation from 9–20 seeds and 1–3 repeats was evaluated with 10,000
deterministic normal-parametric trials using the production exact sign-flip and
Holm implementations. Simulation seed: `2026072800`.

The selection rule was fixed before scanning: choose the smallest
episodes/model whose sensitivity-power Wilson 95% lower bound is at least
0.80. **No tested allocation qualifies.**

| Allocation | Episodes/model | Base familywise power (95% CI) | Sensitivity power (95% CI) |
|---|---:|---:|---:|
| 16 x 3 | 48 | 0.2316 (0.2234–0.2400) | 0.1351 (0.1285–0.1419) |
| 17 x 3 | 51 | 0.2586 (0.2501–0.2673) | 0.1503 (0.1434–0.1574) |
| 18 x 3 | 54 | 0.2921 (0.2833–0.3011) | 0.1787 (0.1713–0.1863) |
| 19 x 3 | 57 | 0.3090 (0.3000–0.3181) | 0.1938 (0.1862–0.2017) |
| **20 x 3** | **60** | **0.3486 (0.3393–0.3580)** | **0.2154 (0.2075–0.2236)** |

Twenty seeds are mechanically sufficient for exact-test resolution
(`2 / 2^20 = 0.0000019073486328125`, below Holm step one's `0.05 / 8 =
0.00625`), but resolution is not power. Even the best tested row's sensitivity
upper confidence bound is far below 0.80.

The panel allocation and private seed identity therefore remain blocked. A
pre-data amendment must change at least one of the seed ceiling, target claim,
target effect, or power criterion and then rerun this design analysis. No
private seeds should be generated or committed before that decision.

## Reproduction

```bash
python3 scripts/panel_power.py \
  --exact-reference-family \
  --family-size 8 \
  --delta 40 \
  --target-power 0.80 \
  --min-seeds 9 \
  --max-seeds 20 \
  --max-repeats 3 \
  --trials 10000 \
  --json

python3 -m pytest -q \
  tests/test_panel_power.py \
  tests/test_publication_analysis.py \
  tests/test_seed_panel_commitment.py \
  tests/test_sota_v3_preregistration.py
```
