# SOTA-v5 route-and-cohort amendment — 2026-09-01

Revision `2026-09-01-v6-route-and-cohort-amendment`, superseding
`2026-08-31-v6-execution-rules-amendment`. Owner-directed. Evidence state:
**post-smoke, pre-panel** — twelve registered rows hold accepted strict smokes
(docs/run_logs/sota-v5-smoke-grants-2026-09-01.md), no private-seed panel row
has run, and no seed was read.

## Why

The 2026-09-01 smoke sequence lost four of sixteen rows, none for a reason the
panel is meant to measure:

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
twelve accepted smokes. No kept row changes. No withdrawn row was withdrawn
for its score.

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
