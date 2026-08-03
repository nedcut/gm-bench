# `sota-v3` design amendment 2 — ten-model cohort, 2026-08-03

This is a no-spend, pre-data amendment. No provider or completion endpoint was
called, no private seeds were generated, and every execution, spend, and
publication authorization remains false. It supersedes the cohort and
allocation frozen in `sota-v3-design-amendment-2026-07-28.md`; everything not
restated here carries forward unchanged from that record.

## Why the cohort changed

This is an owner-directed cohort update made while `evidence_state` is still
`pre-data-no-v3-model-smokes-or-panel-results`, so no observed v3 score could
have influenced it.

**The OpenAI anchor moves from GPT-5.6 Luna Pro to plain GPT-5.6 Luna.** The
2026-07-28 registry preserved a substitution to the Pro variant made when the
plain Luna route was unhealthy. At the 2026-08-03 catalog snapshot the plain
route is healthy (status 0, 99.3% uptime over 30 minutes), and the Pro variant
carried an unresolved inconsistency between its public description
(`reasoning.mode=pro`) and the structured catalog (reasoning optional,
supports `none`). Restoring the plain route removes that ambiguity from the
registry; the corresponding `unresolved_decisions` item is dropped as
resolved-by-substitution.

**Two open-weight anchors join the family.** DeepSeek V4 Flash 0731 and
Tencent Hy3, both on first-party FP8 routes. Both routes are healthy at the
snapshot, neither has mandatory reasoning, and both are pinned under the
cohort-wide disabled-reasoning policy. The cohort balance moves from 4/4 to 4
frontier-proprietary / 6 open-weight.

**Thinking Machines Inkling Small was evaluated for the tenth slot and is
ineligible at this snapshot.** The frozen lane runs every model with
`OPENROUTER_JSON_MODE=true` (the adapter sends
`response_format={"type":"json_object"}`) and
`OPENROUTER_REQUIRE_PARAMETERS=true`, so OpenRouter only routes to endpoints
that advertise `response_format`. Neither of inkling-small's catalog routes
advertises it, and the full-size inkling's only advertising route (DeepInfra)
is degraded at the snapshot while the registry requires a healthy pinned
route. The ineligibility is recorded here so a later route change can be
revisited only through another pre-data amendment. Moonshot Kimi K3 was also
evaluated and passed the route requirements but was declined on cost: at its
pinned first-party rate it would have been the most expensive model in the
panel.

## Why the allocation changed

A family of ten tightens the Holm first-step threshold from `0.05/8 =
0.00625` to `0.05/10 = 0.005`, and the familywise all-reject event over ten
contrasts is strictly harder than over eight under the frozen
compound-symmetry covariance. The allocation was reselected with the identical
frozen machinery — same historical variance components, planning effect -100,
sensitivity multipliers, 9-16 seed by 1-3 repeat grid, 10,000 trials,
simulation seed 2026072800 — changing only `--family-size` from 8 to 10.

The previously selected 15 seeds x 1 repeat no longer qualifies at family
ten: its conservative-sensitivity familywise power is 0.8020 with Wilson 95%
CI [0.794074, 0.809694], and the predeclared rule requires the *lower bound*
to clear 0.80. The smallest qualifying allocation is:

| Item | Family of eight (superseded) | Family of ten (this amendment) |
|---|---|---|
| Holm first-step threshold | 0.00625 | 0.005 |
| Selected allocation | 15 seeds x 1 repeat | **16 seeds x 1 repeat** |
| Episodes per model | 15 | **16** |
| Base power (Wilson 95%) | 0.9461 [0.9415, 0.950357] | 0.9527 [0.948363, 0.95669] |
| Sensitivity power (Wilson 95%) | 0.8357 [0.828309, 0.842834] | 0.8488 [0.841645, 0.855688] |
| Minimum exact two-sided p | 6.103515625e-05 | 3.0517578125e-05 |
| Total panel episodes | 120 | 160 |

At 16 seeds the exact sign-flip resolution floor `2/2^16` sits far below the
0.005 Holm first step, so exact feasibility is preserved.

The pending private seed panel is now 16 seeds. Its identity remains
unfrozen: `seed_panel.name` and `seed_panel.sha256` are null until the panel
is generated under separate owner authorization and only its salted hiding
commitment plus ordered execution hash are committed.

## Cost consequence

The regenerated pre-smoke reservation
(`results/analysis/sota-v3-pre-smoke-cost-estimate.json`) for the 10-model,
16-seed panel plus required smokes is $89.85 unrounded, $107.81 with the 1.2x
contingency multiplier (previously $86.59 / $103.91). Both added models price
below the cohort median, and plain Luna is cheaper than Luna Pro at the pinned
base rates, so the cheaper substitution partly offsets the extra seed and the
two added smoke-plus-panel lanes. This remains a planning reservation, not an
authorization; the operator ceiling is still null and `spend_authorized` is
still false.

## Unchanged

- Directional primary claim: every registered model-plus-compact-scaffold
  system trails deterministic `pick-trader` on seed-paired mean lift.
- alpha 0.05, Holm-Bonferroni across the fixed registered family, exact
  two-sided enumeration sign-flip test, seed as the unit of inference.
- Planning effect -100 score points; 0.80 conservative-sensitivity
  familywise all-reject power target with the Wilson lower-bound rule.
- Contract fingerprint `a523bdfcebe47bbd`; no `_CONTRACT_SOURCES` file was
  touched.
- The provisional 4,096-token output ceiling, 3,072 cap-pressure trigger,
  and symmetric amendment rule.
- No model-to-model tiers or ordinal ranking.
- Every execution, spend, and publication authorization remains false, and
  route preflight, seed generation, smokes, panel, and publication each still
  require their own separate owner decisions.

## Reproduction

```bash
python3 scripts/panel_power.py \
  --exact-reference-family \
  --family-size 10 \
  --delta -100 \
  --target-power 0.80 \
  --min-seeds 9 \
  --max-seeds 16 \
  --max-repeats 3 \
  --trials 10000 \
  --json

python3 scripts/estimate_publication_cost.py \
  --models-config config/sota_v3_models.json \
  --lane-config config/sota_v3_lane.json \
  --pricing config/sota_v3_pricing_snapshot.json \
  --output results/analysis/sota-v3-pre-smoke-cost-estimate.json

python3 -m pytest -q \
  tests/test_panel_power.py \
  tests/test_publication_cost.py \
  tests/test_publication_analysis.py \
  tests/test_seed_panel_commitment.py \
  tests/test_sota_v3_preregistration.py \
  tests/test_sota_v3_route_catalog.py
```
