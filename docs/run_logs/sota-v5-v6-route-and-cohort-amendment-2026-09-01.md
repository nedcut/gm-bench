# SOTA-v5 route-and-cohort amendment — 2026-09-01

Revision `2026-09-01-v6-route-and-cohort-amendment`, superseding
`2026-08-31-v6-execution-rules-amendment`. Owner-directed. Evidence state:
**post-smoke, pre-panel** — twelve registered rows hold accepted strict smokes
(docs/run_logs/sota-v5-smoke-grants-2026-09-01.md), no private-seed panel row
has run, and no seed was read.

## Why

The 2026-09-01 smoke sequence lost four of sixteen rows. Three were route
failures the panel does not measure. One, nemotron-3-nano, was withdrawn on
its own smoke behavior: a malformed decision, and malformed rate is a
reported panel outcome (docs/bench_v6_spec.md). That withdrawal is therefore
outcome-dependent and is stated as such; what was not outcome-dependent is
the choice of its replacement, made without any score or perceived quality.

| Row | What happened |
| --- | --- |
| z-ai/glm-5.3-flash on Cloudflare | Two attempts; every call returned a billed response with no `choices` array. Excluded at the infrastructure limit. |
| minimax/minimax-m3 on Parasail | Two attempts; HTTP 429 on every call. Excluded at the infrastructure limit. |
| qwen/qwen3.5-397b-a17b on Parasail | One attempt consumed by HTTP 429; the free endpoint preflight then refused twice on missing uptime telemetry during the same Parasail incident. |
| nvidia/nemotron-3-nano-30b-a3b on Crusoe | Completed, but one malformed decision under the registered strict JSON-mode condition (all calls finished `stop`, zero truncation). Ineligible on model behavior; the frozen policy forbids a behavior rerun. |

The owner chose to revise these four rows rather than run a twelve-row panel.

## What changed

| Slot | Before | After | Basis |
| --- | --- | --- | --- |
| glm-5.3-flash | Cloudflare | **Fireworks** (unquantized, $0.15/$0.50 per M) | Same identity. Next route under the frozen rule once Cloudflare is excluded. The stealth "Ox Alpha" leaderboard entry was publicly disclosed to be this model, making it the most-used model on OpenRouter the week ending 2026-08-31. |
| minimax-m3 | Parasail fp8 | **ModelRun fp4** ($0.75/$3.00 per M) | Same identity. The only other route meeting the frozen eligibility rule (structured_outputs, both uptime floors). fp4 is recorded as a measurement caveat, like kimi-k2.5's int4. |
| qwen3.5-397b-a17b | Parasail fp8 | **qwen/qwen3.8-flash** on Alibaba ($0.15/$0.47 per M) | Identity replaced: the vendor's current flash release (catalog date 2026-08-26); the only eligible route. |
| nemotron-3-nano-30b-a3b | Crusoe fp8 | **nvidia/nemotron-3-super-120b-a12b** on DigitalOcean ($0.30/$0.65 per M) | Identity replaced with the next size up in the same family; the only eligible route. |

Reasoning policy under the frozen per-model rule: glm-5.3-flash stays
mandatory-minimum at `low`; the other three advertise a disabled path and pin
reasoning off. All four routes advertise max_tokens, reasoning,
response_format and structured_outputs, publish both uptime figures above the
floors, and allow at least 4,096 completion tokens.

## Rule extension

`route_selection_rule.lane_infrastructure_exclusion`: a route that reached
the lane's two-attempt infrastructure limit is ineligible for re-registration
under any model identity. Without it the frozen metadata-only rule mechanically
re-selects Cloudflare for glm-5.3-flash and Parasail for minimax-m3, which
would re-register a burned route with a fresh attempt budget.

## What was considered and rejected

- **Free variants** (`nvidia/nemotron-3-ultra-550b-a55b:free` and others).
  The Nvidia free endpoint's terms state that use is logged "to improve NVIDIA
  products and services" and that the user consents to collection and use.
  The lane pins `OPENROUTER_DATA_COLLECTION=deny` so the private seed panel
  never reaches a retaining provider; a logging endpoint is incompatible. The
  Nvidia free endpoints also advertise no `response_format` and ran at about 4
  tokens per second with 57 s median latency, and free tiers share an
  account-wide request limit that reproduces the 429 failure mode.
- **Paid nemotron-3-ultra** ($0.50/$2.20 per M): eligible, but the owner chose
  Super as the cheaper middle option.
- **Adding models beyond sixteen** (tencent/hy3, xiaomi/mimo-v2.5,
  z-ai/glm-5.3): declined; the Holm family stays 16.
- **Ox Alpha**, **Hy4 preview**: stealth/preview aliases with no stable
  identity.

## Inputs to the identity revision, stated plainly

Used: owner direction; the route-failure ledger; OpenRouter adoption
rankings for the week ending 2026-08-31; public pricing and endpoint metadata;
the Ox Alpha disclosure.

Not used: any GM-Bench score, model output, or apparent quality from the
twelve accepted smokes. No kept row changes. No row was withdrawn for its
score; nemotron-3-nano was withdrawn for a reported behavior outcome (one
malformed decision under the frozen gate), which is the one outcome-dependent
step in this amendment.

This is a post-data cohort amendment and is labelled as such. The 2026-08-31
selection basis ("before any v5 or v6 model data") no longer describes the
four amended rows.

## Attempt accounting

The four amended rows are new cells (new experiment ids) with a fresh
two-attempt infrastructure budget. The withdrawn cells' attempts, spend, and
exclusions stay in `data/publication/sota-v5-smokes/openrouter-reservations.json`
and the grant log. The unconsumed final-retry grant for the withdrawn
qwen3.5-397b Parasail row is voided in place in all four config records.

## Unchanged

Contract fingerprint a600b7da0c302231; 4,096-token ceiling including
reasoning; zero repair attempts; strict failure handling; serialized calls;
$100 ceiling; the frozen 29-seed private panel commitment and owner
attestation; Holm family 16; pick-trader reference; panel and publication
authorization remain false.

## Follow-through

Regenerate exact-route acceptance evidence for all sixteen rows (free,
authenticated, zero completion calls), regenerate the panel cost estimate and
ascending run order, then grant and run strict smokes for the four new rows.

## Addendum 2026-09-01T19:40Z — glm-5.3-flash moves to DeepInfra fp8

Fireworks consumed one attempt on HTTP 429 (two consecutive calls). The owner
asked about the Z.AI first-party route at its 50% discount; it fails the
frozen rule twice (no `structured_outputs`; 24-hour uptime 98.1% against the
99.0% floor) and was rejected. The owner then chose **DeepInfra fp8** — the
same discounted rate ($0.075/$0.25 per M), every required parameter, uptime
99.1/99.4 — rather than spend the final Fireworks attempt.

This is an owner-directed deviation from the frozen ordering, which prefers
the unquantized Fireworks route, and is recorded as such in
`route_selection_rule.owner_directed_deviations`. Price is not an outcome
input and the model identity is unchanged. The fp8 quantization is a
measurement caveat like kimi-k2.5's int4 and minimax-m3's fp4. The Fireworks
cell's unused final attempt is voided; its consumed attempt stays in the
ledger.

## Addendum 2026-09-01T20:45Z — nemotron-3-super replaced by nemotron-3.5-lightning

After the PR #129 review, every smoke was re-run under the fixed
one-paid-call rule. nvidia/nemotron-3-super-120b-a12b hit DigitalOcean HTTP
429 on both attempts and is excluded at the frozen infrastructure limit.
DigitalOcean was its only route meeting the eligibility rule (DeepInfra bf16
advertises no `structured_outputs`), so the identity cannot be re-routed.

The owner asked for tencent/hy3; under the full rule it has no eligible route
(the Tencent first-party route lacks `structured_outputs`, the others lack
`response_format`), and neither does xiaomi/mimo-v2.5. The owner then chose
**nvidia/nemotron-3.5-lightning** on **CoreWeave bf16** ($0.10/$0.25 per M,
100% uptime), the only route for that identity meeting the rule and the
newest Nvidia release in the catalog (2026-08-11). It keeps the slot in the
same family as the frozen spec's nemotron-3-nano. Reasoning is optional and
is pinned off.

Inputs, as before: owner direction, the route-failure ledger, and public
catalog metadata. No score or model output from any smoke was used.

## Addendum 2026-09-01T21:00Z — slot 16 goes to gpt-5.6-sol

nvidia/nemotron-3.5-lightning completed its one-call smoke but is ineligible
on model behavior: one unrecoverable draft decision, with all four calls
finished cleanly and no truncation. Model behavior never authorizes a rerun,
so both Nvidia candidates for the slot have now failed the strict gate — one
on its route, one on its output.

The owner chose **openai/gpt-5.6-sol** on the **OpenAI flex** route
($1.00/$5.00 per M), the rule winner among its two eligible routes.
Reasoning is optional (the catalog advertises a `none` effort) and is pinned
off. This is the second withdrawal in this amendment based on a reported
behavior outcome; as before, the replacement identity was chosen from public
adoption and pricing metadata, never from any smoke score.
