# `sota-v3` design amendment 1 — allocation frozen, 2026-07-28

This is a no-spend, pre-data amendment. No provider or completion endpoint was
called, no private seeds were generated, and every execution, spend, and
publication authorization remains false. It supersedes the blocked design in
`sota-v3-statistical-design-audit-2026-07-28.md`.

## Why the previous design was blocked

The superseded audit powered the family for a **+40 point lift above**
`pick-trader` and found no qualifying allocation in a 9-20 seed by 1-3 repeat
grid. That finding was arithmetically correct and is not retracted. Two facts
about it drove this amendment.

**The block was structural, not budgetary.** Holding seeds at 20 and letting
repeats grow without bound drives per-episode noise to zero, which is the
best any amount of money can buy at that seed ceiling:

| Seeds | All-reject ceiling (base) | All-reject ceiling (sensitivity) |
|---:|---:|---:|
| 20 | 0.471 | 0.362 |
| 40 | 0.884 | 0.785 |
| 60 | 0.985 | 0.948 |

At 20 seeds the sensitivity ceiling is ~0.36. Raising the budget was never a
route to 0.80, because a candidate-minus-`pick-trader` lift retains its full
seed component: per-seed lift SD is `sqrt(3770.478 + 2850.170 / r)`, which
floors at `61.4` no matter how large `r` grows.

**The claim pointed away from the evidence.** In the frozen `sota-v2` panel
(`results/analysis/publication-panel-analysis.json`) every eligible model
*trailed* the reference:

- mean lift, all eight models: **-180 to -282** score points
- `seed_win_rate`: **0.0** for all eight — no model won a single seed
- `sign_flip_p_value`: `0.0078125` for all eight, exactly `2 / 2^8`

That panel did not fail for want of signal. It hit the exact test's resolution
floor: at eight seeds the smallest expressible two-sided p-value is `2/2^8 =
0.0078`, above the Holm step-one threshold of `0.05/10 = 0.005`. Powering
`sota-v3` for a +40 lift meant powering for a swing of roughly 250 points
against the only direct evidence available.

## What changed

| Item | Before | After |
|---|---|---|
| Primary claim | each model beats `pick-trader` | each model **trails** `pick-trader` |
| Planning effect | +40 | **-100** |
| Panel repeats | 3 | **1** |
| Evaluated seed grid | 9-20 | 9-16 |
| Selected allocation | none qualified | **15 seeds x 1 repeat** |
| Episodes/model | 60 (blocked at 0.2154) | **15 (sensitivity 0.8357)** |

Unchanged: alpha 0.05, Holm-Bonferroni over a fixed family of eight, the exact
two-sided enumeration sign-flip test, the seed as unit of inference, the 0.80
conservative-sensitivity familywise target, and the prohibition on model-to-model
tiers or ordinal ranking.

The planning effect of -100 is deliberately conservative against the -180 to
-282 observed. The `sota-v3` contract economics (#92) made bad contracts
expensive to unwind, which is precisely where the scripted reference was
earning its margin, so the v3 gap may compress. -100 leaves room for that.

The test remains **two-sided**. The sign of the planning effect is an
assumption used to size the panel, not a one-sided rejection region.

## Result

Ten thousand deterministic trials per allocation, simulation seed
`2026072800`, evaluated with the production exact sign-flip and Holm functions:

| Allocation | Episodes/model | Base power (95% CI) | Sensitivity power (95% CI) |
|---|---:|---:|---:|
| 12 x 1 | 12 | 0.8048 | 0.6146 |
| 13 x 1 | 13 | 0.8698 | 0.7000 |
| 14 x 1 | 14 | 0.9127 | 0.7749 |
| **15 x 1** | **15** | **0.9461 (0.9415-0.9504)** | **0.8357 (0.8283-0.8428)** |
| 16 x 1 | 16 | 0.9629 | 0.8727 |

Selection rule, fixed before scanning: the smallest episodes/model whose
sensitivity-power Wilson 95% **lower** bound is at least 0.80. `15 x 1` is the
first to qualify at `0.8283`.

Resolution is comfortable: `2 / 2^15 = 6.1035e-05`, well under Holm step one's
`0.05 / 8 = 0.00625`.

The one-repeat choice is visible in the scan rather than asserted. Twelve
episodes spent as `12 x 1` reach sensitivity power `0.6146`; eighteen episodes
spent as `9 x 2` reach only `0.4496`. More episodes, less power.

## What this does not authorize

Seed identity is **not** frozen. The 15-seed private panel must be generated
and its salted commitment hash committed under separate owner authorization
before any provider call. Also still open: authenticated exact-route and
privacy verification, the Luna reasoning-policy ambiguity, a frozen output
token cap and cost ceiling, and one accepted strict-fallback smoke per
registered model.

`preregistration_status` is `provisional-allocation-frozen` and
`panel_design_status` is `allocation-frozen-pending-authorization`. Both
execution gates test against the literal `frozen`, so both still lock provider
execution.

## Reproduction

```bash
python3 scripts/panel_power.py \
  --exact-reference-family \
  --family-size 8 \
  --delta -100 \
  --target-power 0.80 \
  --min-seeds 9 \
  --max-seeds 16 \
  --max-repeats 3 \
  --trials 10000 \
  --json

python3 -m pytest -q \
  tests/test_panel_power.py \
  tests/test_publication_analysis.py \
  tests/test_seed_panel_commitment.py \
  tests/test_sota_v3_preregistration.py
```
