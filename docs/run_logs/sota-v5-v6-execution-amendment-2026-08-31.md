# `sota-v5` amendment — the v6 panel and execution rules, 2026-08-31

This is a no-spend, pre-data amendment. No provider key was used, no completion
endpoint was called, no model prompt was sent, no private seed or salt was read
or generated, and every spend, smoke, panel, and publication authorization
remains `false`. Every route, price, uptime, and reasoning value recorded here
came from the free unauthenticated OpenRouter model and endpoint listings
(`/api/v1/models` and `/api/v1/models/{id}/endpoints`) read on 2026-08-31.

It supersedes the cohort, route rule, seed allocation, reasoning policy, and
budget frozen in `sota-v5-preregistration-2026-08-16.md` and
`sota-v5-route-amendment-2026-08-16.md`. Everything not restated here carries
forward unchanged. The `sota-v5` registry has published no rows and observed no
`sota-v5` model data, so no result could have influenced any choice below — the
condition that makes an amendment legitimate rather than a rewrite.

Nothing in `results/analysis/sota-v5-*.json`, `config/sota_v2_*`,
`config/sota_v3_*`, or `config/sota_v4_*` is edited. The retired eight-model
route acceptance evidence and the retired pre-smoke cost estimate stay on disk
exactly as they were.

## Why the lane needed amending at all

The 2026-08-16 preregistration was written for a different benchmark. Between
then and now this branch rebuilt five simulator mechanics, rewrote the whole
observation render, and adopted the v6 execution rules. Four concrete
contradictions made a `sota-v5` panel cell ineligible under its own gate:

1. `shared_fixed_options` pinned `GM_BENCH_PROTOCOL_REPAIR_ATTEMPTS` to `"1"`,
   while `gm_bench/official.py` `SOTA_V5_POLICY.max_protocol_repair_attempts`
   is `0`. Every row the config described would have been refused at
   validation for having bought a paid retry.
2. The pinned `contract_fingerprint` was `247e12fe5a7d4f5b`, thirteen moves
   stale. The live fingerprint is `a600b7da0c302231`.
3. The registered cohort was eight models that are not the v6 panel.
4. The lane-wide `reasoning_policy: "disabled"` plus
   `mandatory_reasoning_action: "abort-sota-v5-and-repreregister"` would have
   aborted the lane on the frontier slot: the public catalog marks
   `x-ai/grok-4.6` mandatory-reasoning.

## The cohort is now the frozen v6 panel

The sixteen model identities are taken verbatim from `docs/bench_v6_spec.md`,
where they were settled from the vision contract and the feasibility study.
This amendment does not choose models. It registers the frozen panel and picks
one exact route per identity. `x-ai/grok-4.6` is the frontier slot.

The eight-model 2026-08-16 cohort is withdrawn in full. Its accepted route
evidence is retired rather than carried forward, because none of its routes is
registered here and the fingerprint it was collected under has moved.

## The route rule changed, and why that is not outcome-dependent

The frozen rule was "the policy-eligible exact route with the highest public
24-hour uptime". Applied to the v6 panel it selects premium `priority` and
`fast` service tiers — the same model identity at up to twice the price — and
pushes the cap-priced panel from **$109.51 to $162.84** with no measurement
benefit.

The rule now orders eligible routes by least-lossy advertised quantization
first, then lowest planning cost, then uptime, then tag. Quantization leads
because it changes the measured system; price follows because it does not.
Route price is a property of an endpoint, never of an observed result, so using
it to order routes *within an already-frozen model identity* cannot make the
selection outcome-dependent. Which model identities run was fixed in the v6
spec and is not reopened here.

Eligibility is unchanged in substance: healthy exact route, advertising
`max_tokens`, `reasoning`, `response_format` and `structured_outputs`, with at
least 4,096 completion tokens, plus a 99.0% 24-hour uptime floor.

Two routes carry caveats worth reading before the smoke:

- **`moonshotai/kimi-k2.5`** has exactly one eligible route above the uptime
  floor and it is `int4`-quantized. That is a measurement caveat for this row,
  recorded beside it, not a route failure.
- **Both Gemini rows** are pinned to Google AI Studio `flex` tiers, which trade
  queueing latency for price. Latency is reported, not scored, but confirm the
  tier answers at all during the smoke.

## Reasoning is now decided per model, not per lane

The public catalog's `reasoning` block answers the question directly for all
sixteen. Twelve advertise a disabled path and pin
`OPENROUTER_REASONING_ENABLED=false` with `OPENROUTER_REASONING_EFFORT` absent.
Four are marked `mandatory: true` and run at their lowest advertised effort with
reasoning tokens recorded beside the score, exactly as the v6 execution rules
say:

| Model | Advertised efforts | Pinned effort |
| --- | --- | --- |
| `x-ai/grok-4.6` | xhigh, high, medium, low | `low` |
| `google/gemini-3.7-flash` | high, medium, low | `low` |
| `z-ai/glm-5.3-flash` | max, high, low | `low` |
| `openai/gpt-oss-20b` | high, medium, low | `low` |

**Whether 4,096 output tokens is enough is a smoke-time question for exactly
those four rows**, and each is marked `verify-at-smoke-time` in the registry.
The v6 ceiling includes reasoning tokens, so a mandatory-reasoning row spends
part of the same 4,096 on reasoning it cannot use for the action list, and no
public metadata publishes a reasoning-token distribution at minimum effort. For
the twelve reasoning-disabled rows the whole ceiling reaches the reply and the
question is settled: every reasoning-disabled route in the v2/v3 smoke record
peaked at or below 604 output tokens per call.

A mandatory-reasoning row that cannot fit an action list under the ceiling is
now **excluded from the panel with its evidence retained**. It no longer aborts
the lane. Aborting was the right call when the whole point of the v3 cohort was
reasoning uniformity; under v6, mandatory-reasoning models are explicitly in
scope and the frontier slot is one of them.

## Seeds: 16 retired unused, 29 pending owner generation

The lane carried a 16-seed private commitment from `sota-v3` through `v4` and
`v5`. No panel ever ran and no seed or salt was ever read. The v6 panel is 29
paired seeds, so that commitment is the wrong width. It is **retired unused**:
its digests stay in `seed_panel.retired_commitment` so the retirement is
checkable, and it must not be reused, extended, or partially revealed.

`seed_panel.status` is `pending-authorized-generation`. Generating private seed
material and choosing its escrow is an owner action, so this amendment
deliberately does not do it, and panel execution stays blocked until it is done.
`v3_statistical_plan_issues` reports `seed panel identity is not frozen` for
exactly this reason; that is the gate working, not a defect.

Widening the Holm family from 8 to 16 tightens the first-step threshold from
`0.05/8 = 0.00625` to `0.05/16 = 0.003125`. The exact two-sided sign-flip floor
at 29 seeds is `2/2**29 = 3.73e-09`, which clears it by six orders of magnitude,
so the wider family costs nothing in feasibility. The narrower design's binding
constraint has moved: the v6 width is set by the 30-point minimum detectable
difference in `docs/bench_v6_spec.md`, which `docs/scoring_calibration.md`
measures at 26 points across 29 paired seeds.

The analyzer's exact-enumeration limit moved from 20 seeds to 30, in
`scripts/analyze_publication_panel.py` and the matching guard in
`gm_bench/publication.py`. That bound was inherited from the original
exhaustive loop; the current implementation is meet-in-the-middle, so 29 seeds
cost `2**15` sorted subset sums rather than `2**29` sign assignments. The test
stays exhaustive and exact either way — it is verified against brute-force
enumeration in `tests/test_publication_analysis.py`.

## Cost: the ~$75 / $100 plan holds, but not by the cap-priced number

The panel is 16 models x 29 seeds x 5 seasons x 4 phases = **9,280 paid calls**,
plus a 64-call smoke gate. With `GM_BENCH_PROTOCOL_REPAIR_ATTEMPTS=0` and one
paid call per decision phase, the protocol maximum is the same 9,344 calls: v6
buys no retry, so there is no multiplier between the plan and the worst case.

At today's public rates on the selected routes:

| quantity | USD |
| --- | ---: |
| input only, 8,000 tokens per decision | 35.70 |
| completion, per 1,000 output tokens across the panel | 18.02 |
| cap-priced panel (4,096 output on every call) | 109.51 |
| cap-priced panel + smoke gate | 110.26 |
| the same with the 1.2x contingency | 132.31 |
| at ~1,000-token replies (the reasoning-disabled smoke record) | ~54 |
| the same with every completion doubled | ~72 |

**The ~$75 base and $100 hard ceiling still hold, and with more margin than the
spec assumed** — the expected panel plans at about $54, and a 2x
completion-token overrun lands near $72. Both are under $100.

**The cap-priced planning maximum does not fit under the ceiling, and is not
meant to.** $110.26 assumes every one of 9,344 calls returns the full 4,096-token
ceiling, which no reasoning-disabled row in the smoke record comes close to. The
$100 ceiling is enforced by the runner's dynamic pre-call spend guard, the same
arrangement the 2026-08-16 protocol already used when its $10 smoke ceiling sat
below a $600 panel maximum. `tests/test_sota_v5_preregistration.py` pins the
relationship so it cannot drift silently.

The registry now freezes an **ascending-cost run order**. The cheapest thirteen
rows total $57.71 and finish before the ceiling is anywhere near in play; the
two most expensive rows (`grok-4.6` at $23.53 and `claude-haiku-4.5` at $16.52,
37% of the panel between them) are the last money committed, so a route, render,
or repair problem surfaces on cheap cells first.

`results/analysis/sota-v6-panel-cost-estimate.json` is a new artifact.
`results/analysis/sota-v5-pre-smoke-cost-estimate.json` is left untouched as
history; it quotes the pre-v6 $600 protocol maximum for the withdrawn cohort and
must not be read as current.

## What is unchanged

- Contract label `sota-v5`, provider OpenRouter, compact profile, `leaderboard`
  preset, one repeat per seed, `pick-trader` as the named reference.
- The 4,096-token output ceiling and the `fixed-safety-ceiling` output policy
  basis.
- Seed as the unit of inference; exact-enumeration sign-flip with
  Holm-Bonferroni at alpha 0.05; `reference-only` analysis mode; publish tiers,
  never ordinal ranks.
- Fail-closed authorization throughout. Route preflight is authorized; spend,
  smoke, panel, and publication are not.
- No `sota-v2`, `v3`, or `v4` evidence carries forward, and no published row is
  rewritten.

## What still blocks a paid call

1. Generate, commit, and freeze the new 29-seed private panel, then record the
   owner attestation.
2. Run the authenticated zero-completion route and privacy preflight over all
   sixteen routes and accept `exact_route_acceptance`. This needs an OpenRouter
   bearer token, so it is panel-time work.
3. Regenerate the final-fingerprint preflight evidence against
   `a600b7da0c302231`.
4. Accept one strict smoke per route, including the reasoning-headroom check on
   the four mandatory-reasoning rows.
5. Authorize spend, smoke execution, and panel execution explicitly.

## Reproduction

```bash
# free, unauthenticated metadata only
curl -s https://openrouter.ai/api/v1/models
curl -s https://openrouter.ai/api/v1/models/x-ai/grok-4.6/endpoints

python3 scripts/estimate_publication_cost.py \
  --models-config config/sota_v5_models.json \
  --lane-config config/sota_v5_lane.json \
  --pricing config/sota_v5_pricing_snapshot.json \
  --output results/analysis/sota-v6-panel-cost-estimate.json

python3 -m pytest -q \
  tests/test_publication_cost.py \
  tests/test_publication_analysis.py \
  tests/test_sota_v5_preregistration.py
```
