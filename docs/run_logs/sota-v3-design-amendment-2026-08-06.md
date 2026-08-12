# `sota-v3` design amendment 3 — eight-model reasoning-uniform cohort, 2026-08-06

This is a no-spend, pre-data amendment. No completion endpoint was called, no
model prompt was sent, no private seeds were regenerated, and every panel and
publication authorization remains false. It supersedes the cohort and family
size frozen in `sota-v3-design-amendment-2026-08-03.md`; everything not
restated here carries forward unchanged from that record.

The route-acceptance evidence artifact was regenerated for the reduced cohort
using `scripts/collect_sota_v3_route_evidence.py --apply-registry`, which reads
only OpenRouter metadata endpoints: `completion_calls` is 0 in the regenerated
artifact, as it was in the one it replaces.

## Why the cohort changed

This is an owner-directed cohort reduction made while `evidence_state` is still
`pre-data-no-v3-model-smokes-or-panel-results`. No v3 smoke or panel score
exists, so no observed result could have influenced which models were
withdrawn — the condition the output policy's "scores and apparent model
quality are never cap-selection inputs" clause exists to protect.

**Gemini 3.6 Flash and Grok 4.5 are withdrawn.** They were the only two
registered routes whose catalog marks reasoning mandatory. Every other model in
the family runs with `OPENROUTER_REASONING_ENABLED=false`, so the pair
reintroduced precisely the cross-model reasoning inconsistency that caused
Gemini and Grok to be excluded from the frozen `sota-v2` panel. Withdrawing
them makes the cohort uniformly reasoning-disabled, which:

- removes a known confound from the primary contrast, and makes v2 and v3 more
  comparable rather than less;
- resolves the protocol's pending
  `catalog-pinned-pending-strict-smoke-behavior-verification` reasoning policy
  outright, because there is no longer a mandatory-reasoning route whose smoke
  behavior needs verifying; and
- removes the only two routes whose `sota-v2` smoke telemetry came anywhere
  near the 3,072-token cap-pressure threshold (Grok 4.5 recorded 937 output
  tokens per call against 2,064 reasoning tokens, while every
  reasoning-disabled model peaked at or below 604 output tokens against the
  same 4,096-token cap).

**The cohort is no longer balanced.** It moves from 4 frontier-proprietary / 6
open-weight to 2 / 6, retaining OpenAI and Anthropic as the only
frontier-proprietary anchors. Reasoning uniformity was chosen over cohort
balance deliberately, and the resulting split is pinned in
`tests/test_sota_v3_route_catalog.py` so it cannot drift further without
another explicit decision. Any public presentation of the panel must describe
the family as predominantly open-weight.

**Zero-data-retention route count falls from 5 to 4**, because the withdrawn
Grok 4.5 route was pinned to `xai/zdr`. The privacy standard is unchanged: ZDR
remains preferred, not required, for a synthetic-data benchmark.

## Why the allocation did not change

A family of eight loosens the Holm first-step threshold from `0.05/10 = 0.005`
back to `0.05/8 = 0.00625`, and the familywise all-reject event over eight
contrasts is strictly easier than over ten. The allocation was re-evaluated
with the identical frozen machinery — same historical variance components,
planning effect -100, sensitivity multipliers, 9-16 seed by 1-3 repeat grid,
10,000 trials, simulation seed 2026072800 — changing only `--family-size` from
10 to 8.

Under the frozen selection rule ("smallest allocation whose conservative
sensitivity power Wilson 95% lower bound is at least 0.80"), the qualifying
allocation at family eight is **15 seeds x 1 repeat**: sensitivity power
0.8357, Wilson 95% CI [0.828309, 0.842834]. This exactly reproduces the
allocation frozen on 2026-07-28, when the family last had eight members — the
family grew 8 to 10, the allocation grew 15 to 16 to compensate, and shrinking
the family reverses it.

**The panel nonetheless retains 16 seeds x 1 repeat.** `seed_panel` was already
frozen pre-data with a published `sha256`, a `hiding_commitment_sha256`, and
its secret escrowed in the macOS Keychain under service
`gm-bench-sota-v3-private-panel`. Dropping to 15 seeds would require breaking
and re-issuing that commitment to save an estimated $4.53. Running one seed
above the rule's minimum is strictly more powerful and never less conservative,
whereas re-issuing a pre-data seed commitment weakens the strongest integrity
property the design has. At 16 seeds and family eight:

| quantity | value | Wilson 95% CI |
| --- | --- | --- |
| sensitivity familywise all-reject power | 0.8727 | [0.866024, 0.87909] |
| base familywise all-reject power | 0.9629 | [0.959014, 0.96643] |
| minimum exact two-sided sign-flip p | 3.0517578125e-05 | — |
| Holm first-step threshold at alpha 0.05 | 0.00625 | — |

The exact-test feasibility floor still holds with room to spare:
`2/2^16 = 3.05e-05 <= 0.05/8 = 0.00625`.

## Why the spend ceiling changed

Reserved worst-case cost falls from **$127.29 to $73.40** with the 1.2x
contingency, because the two withdrawn models were also the two most expensive
rows — both billed internal reasoning at the completion rate on top of output
tokens. The committed operator ceiling is lowered **$150.00 to $100.00**
accordingly. Projected actual spend is roughly $25-30.

The ceiling is deliberately set below the 8,192-token fallback branch, which
would reserve $116.26. A cap-pressure trigger is meant to stop the run for an
explicit owner spend decision, not to silently authorize a larger budget than
the one the plan was measured against. `tests/test_publication_cost.py` asserts
the reservation stays under the ceiling; `tests/test_sota_v3_preregistration.py`
asserts the fallback branch does not.

## The cap-pressure rule gains a terminal case

As frozen through 2026-08-05 the rule said to amend the cap "once" and re-smoke
the family, but never defined what happens if the amended cap trips the trigger
again — so the only written instruction, read literally, was to amend a second
time. `config/*.json` is outside `_CONTRACT_SOURCES`, so a second amendment
would cost nothing to make and leave no fingerprint trace.

The rule now states that the cap may be amended **at most once**, and that a
second trigger aborts `sota-v3` entirely: no panel is run, nothing is published
under this contract, and the lane must be re-preregistered from scratch with a
cap and ceiling costed for both branches. This is machine-checked by
`max_cap_amendments: 1` and
`on_second_trigger: "abort-sota-v3-and-repreregister"`.

## What is unchanged

- Contract fingerprint `a523bdfcebe47bbd`. This amendment touches only
  `config/*.json`, `docs/`, `results/analysis/`, and tests, none of which are
  fingerprint sources.
- alpha 0.05, Holm-Bonferroni across the fixed registered family.
- Exact two-sided enumeration sign-flip test, seed as the unit of inference.
- Planning effect -100 score points; directional trails-reference claim.
- The 4,096-token output cap and the 3,072-token cap-pressure trigger.
- The private 16-seed panel commitment and its Keychain escrow.
- Publish tiers, not ordinal ranks. No model-to-model ranking claim.
- Panel execution and publication authorization both remain false.

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

# the retained 16-seed allocation at family eight
python3 scripts/panel_power.py \
  --exact-reference-family --family-size 8 --delta -100 --target-power 0.80 \
  --min-seeds 16 --max-seeds 16 --max-repeats 1 --trials 10000 --json

python3 scripts/collect_sota_v3_route_evidence.py --apply-registry

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
