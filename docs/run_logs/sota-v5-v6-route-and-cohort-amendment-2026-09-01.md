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

## Addendum 2026-09-01T23:30Z — panel launch path rehearsed, two blockers fixed

A second review pass rehearsed the exact panel launch path with the four
authorization flags flipped on temporary copies of the configs (no provider
call, no config committed with a flipped flag). Two things would have stopped
the run after the owner's flip:

- The runner's panel phase accepted only the three pre-v6 `output_budget_status`
  values, so the v6 lane's `frozen-v6-output-ceiling-including-reasoning`
  would have locked the panel with "lane has not frozen the output-budget
  policy" even with every flag true. The accepted set now lives in
  `gm_bench.publication.FROZEN_OUTPUT_BUDGET_STATUSES` and includes the v6
  value. A regression test builds all sixteen panel cells from the committed
  configs with only the flag check and the seed check stubbed.
- Nothing launched the panel with the 29-seed escrow. The smoke launcher is
  seed-free for sota-v5 by design and still maps sota-v5 to the retired v3
  Keychain service. `scripts/run_sota_v5_panel_from_keychain.py` reads the
  service named by the lane's `seed_panel.secret_escrow`
  (`gm-bench-sota-v5-v6-private-panel`), verifies the escrowed order against
  the committed execution hash and the salted hiding commitment, refuses an
  inherited `GM_BENCH_PRIVATE_SEEDS`, hands the seeds to the runner only through
  the child environment, and defaults to a fresh run directory
  (`data/publication/sota-v5-panel`). It refuses a run directory that holds
  smoke state, because smoke and panel cells share reservation keys and the
  default `data/publication-runs` still carries an aborted attempt-1 smoke
  reservation for gpt-oss-20b from 2026-09-01T03:08Z.

The escrow was verified against the committed lane on 2026-09-01: count 29,
execution sha256 and hiding commitment both match. No seed value was printed.

### Launch procedure (owner action, not yet taken)

1. Flip `panel_execution_authorized` to `true` in all four config records
   (lane, model registry, publication protocol, pricing snapshot) in one
   commit that says so.
2. Run the free route preflight one more time
   (`scripts/run_publication_matrix.py --contract sota-v5 route-preflight`).
3. Rehearse: `scripts/run_sota_v5_panel_from_keychain.py --max-spend-usd 100 --dry-run`.
4. Launch: `scripts/run_sota_v5_panel_from_keychain.py --max-spend-usd 100`
   with `OPENROUTER_API_KEY` in the environment and `GM_BENCH_PRIVATE_SEEDS`
   unset. Cells run serialized in registry order; the pre-call spend guard
   and per-cell reservation stop the run before the $100 ceiling.
5. Watch with `scripts/run_publication_matrix.py --contract sota-v5 status --run-dir data/publication/sota-v5-panel --watch`.

Publication stays unauthorized until the panel completes and its artifacts
pass the publication gate.

## Addendum 2026-09-02 — launch steps 1 to 3 taken; DeepInfra telemetry gap

On the owner's instruction the first three launch steps were taken:

1. The launch-path fixes (v6 output-budget status, escrow launcher, frozen
   run-order enforcement, per-row repeats in the web view) were committed as
   7e50db4 and pushed to PR #129.
2. `panel_execution_authorized` was flipped to `true` in all four config
   records in commit 0c40a66. `publication_authorized` stays `false`. The
   preregistration test now asserts the authorized state and checks that
   withdrawing the registry's flag alone re-locks the panel.
3. The free authenticated route preflight ran against all sixteen routes
   (zero completion calls). Fifteen passed with matching provider, tag, and
   endpoint name. **openrouter-glm-5.3-flash-deepinfra failed** three times
   over several minutes with "matching endpoint has no finite numeric 30m
   uptime telemetry": the endpoints API returned `uptime_last_30m: null` for
   the DeepInfra fp8 endpoint (status 0, every other field unchanged) while
   every other glm-5.3-flash endpoint reported a number. The rule fails
   closed on missing telemetry, as it did for Parasail on 2026-09-01 before
   that telemetry returned.

Consequence for launch: the panel phase re-runs the same endpoint check on
each cell immediately before launching it and stops at the first failure.
glm-5.3-flash-deepinfra is the second cell in the frozen ascending-cost
order, so if the gap persists at launch time the run completes gpt-oss-20b
and then exits before spending on any other row. Nothing is consumed by
that exit. The owner should re-run the single-route preflight until it
passes, then proceed to the dry run and launch; a re-route is not
warranted on a telemetry gap alone and would be a further owner-directed
deviation.

Steps 4 and 5 (dry run, launch, watch) have not been taken.

## Addendum 2026-09-02 (evening) — glm-5.3-flash returns to Fireworks

The DeepInfra fp8 route did not recover. Across four single-route preflights
over about forty minutes the endpoints API kept returning
`uptime_last_30m: null` for it, and its 24-hour uptime read **97.6%**, under
the frozen 99.0% floor in `route_selection_rule.hard_eligibility`. The route
therefore fails hard eligibility on its own, independent of the telemetry
gap, and the row must move.

Applying the frozen ordering to the eligible glm-5.3-flash routes read on
2026-09-02 (status 0, structured_outputs, 24-hour uptime at or above 99.0%):

| Route | Quantization | Price per M | 24h uptime |
| --- | --- | --- | --- |
| **Fireworks** | unknown (unquantized) | $0.15/$0.50 | 99.14% |
| Friendli | unknown | $0.15/$0.50 | 99.10% |
| Reka | fp8 | $0.15/$0.50 | 99.34% |
| Modal | fp8 | $0.15/$0.50 | 99.07% |
| Phala | fp8 | $0.15/$0.50 | 99.23% |

Fireworks wins on the first tie-break that separates the unquantized pair
(highest 24-hour uptime). It consumed one smoke attempt on HTTP 429 on
2026-09-01, under the two-attempt limit, so the infrastructure exclusion does
not apply. The owner asked for Fireworks; the rule selects it independently,
so the 2026-09-01 owner-directed fp8 deviation is retired rather than
replaced by another one. This is a same-identity re-route: no model is
added, withdrawn, or reordered for any reason other than route eligibility,
and no score or model output informed it.

What changed:

- Registry: `openrouter-glm-5.3-flash-deepinfra` replaced by
  `openrouter-glm-5.3-flash-fireworks` (tag `fireworks`, $0.15/$0.50, no
  discount, reasoning mandatory-minimum at `low` as before). The deviation
  record is kept with a retirement note.
- Pricing snapshot: glm-5.3-flash rates doubled back to the undiscounted
  Fireworks rate. The row's DeepInfra runtime observation (17.6 s per
  decision) is dropped until the Fireworks smoke replaces it.
- Cost estimate, ascending run order, and protocol budget figures
  regenerated: cap-priced panel $129.71 (was $128.76), input-only $42.32,
  $21.34 per 1,000 completion tokens, planning at about $64 at 1,000-token
  replies. The Fireworks cell moves from second to fourth in run order.
- Route acceptance regenerated for all sixteen routes (authenticated, zero
  completion calls); the 21:15Z acceptance is preserved under a dated
  superseded name. Final readiness evidence regenerated (dry run plus
  authenticated preflight).
- Smoke manifest: the accepted DeepInfra entry moves to
  `withdrawn_entries_2026_09_02` with its artifact retained;
  `accepted_for_panel` drops to false until the Fireworks cell holds an
  accepted one-call smoke. The panel authorization flags stay true; the
  runner locks the panel on the missing entry alone.
- A single-attempt smoke grant is issued for the Fireworks cell (attempt 1
  of 2, fresh budget in `data/publication/sota-v5-smokes-v2`).

The other DeepInfra row, gpt-oss-20b bf16, is unaffected: 100% 30-minute and
99.96% 24-hour uptime at the same read.

### Smoke and readiness after the return (2026-09-03T01:08Z)

The Fireworks one-call smoke ran on the first attempt and was accepted:
exactly four calls, all finished cleanly, zero truncation, no illegal
actions, 887 reasoning tokens billed inside the 4,096-token ceiling, peak
487 output tokens per call, 4.6 s per decision, $0.0041. The manifest is
accepted for panel again with sixteen entries; the grant is recorded as
consumed in all four config records, and the runtime observation and cost
estimate are regenerated (runtime telemetry complete).

Readiness after the smoke: the free authenticated route preflight passed
all sixteen routes, and the escrow-backed panel dry run constructed all
sixteen cells in the frozen ascending order without a provider call or a
printed seed. Steps 4 and 5 (launch and watch) remain owner actions.

## Panel execution log and execution amendment — 2026-09-03 (UTC)

Launched 2026-09-03T01:22Z from the seed escrow at the $100 ceiling, cells
serialized in the frozen ascending order.

| Cell | Outcome |
| --- | --- |
| gpt-oss-20b (DeepInfra) | Completed 580/580 with zero truncation; 12 unrecoverable decisions, failure rate 2.07% against the 2.0% publication gate. **Ineligible on model behavior**, no rerun, artifact and ledger retained, $0.099. |
| deepseek-v4-flash (Together) | Attempt 1 aborted at seed 27 on two consecutive Together HTTP 429s (spend guard: no cost telemetry). Reconciled, fifteen-minute cool-down, attempt 2 resumed from the checkpoint and **completed**: 580/580, zero failures, zero truncation, $0.436. |
| qwen3.8-flash (Alibaba) | Both attempts aborted within the first seed on Alibaba HTTP 429 pairs, fifteen minutes apart. **Excluded at the infrastructure limit**. Alibaba was the only eligible route, so the identity cannot be re-routed. |
| glm-5.3-flash (Fireworks) | Pre-launch route check refused: OpenRouter flagged the endpoint unhealthy (status -2, 30-minute uptime 94.5%). No attempt consumed, no spend. **Deferred to the end of the order**; the only departure from the frozen order, and it moves a cell that costs nothing until it launches. |
| gpt-5.6-luna (OpenAI flex) | Attempt 1 aborted at seed 19 on two consecutive OpenAI HTTP 503s. Reconciled; retry pending under the amendment below. |

The runner stops the whole panel after an ineligible cell and refuses to
step past it on relaunch, while the frozen policy excludes the row and keeps
the lane alive. The remaining cells are therefore launched one at a time
with `--model-id` through the same escrow launcher; every gate applies
unchanged per cell.

### Execution amendment: bounded backoff on transient provider statuses

Four of the first four launched cells lost an infrastructure attempt to a
pair of consecutive transient statuses with no completion produced and
nothing billed. The two-attempt limit was written for dead routes; a
600-call cell meeting two transient statuses in a row is a near certainty
over a ten-hour run, and one row was already lost to it. On the owner's
decision the execution rules gain a bounded retry:

- Scope: `gm_bench/model_runs.py` (`TransientRetryAgent`), between the
  fail-fast breaker and the provider agent. It is outside every contract
  and scaffold fingerprint source; both fingerprints are unchanged
  (a600b7da0c302231, c582e126bbb6af10), so completed cells stay comparable.
- Trigger: HTTP 429, 502, 503, 504, or 529 reported by the adapter or by the
  spend guard's telemetry error. Nothing else is retried; a malformed reply
  is still model behavior.
- Bound: at most four retries per decision, backing off 20, 40, 80, 160
  seconds with up to 25% jitter. Exhausted retries fall through to the
  fail-fast breaker exactly as before.
- Spend: before each retry the unresolved reservation is charged in full as
  spent (the same conservative method as `reconcile-spend`) and the retry is
  recorded in the run directory's guard state. A retried request is not a
  second paid call: only the completed call's usage is returned, and the
  count of retries is surfaced beside it.
- Recorded in `rerun_policy.transient_status_backoff` in the publication
  protocol. Model behavior still never authorizes a rerun; the two-attempt
  infrastructure limit still applies to whole-cell failures.

Rows already excluded stay excluded. The chain resumes with the
gpt-5.6-luna retry (attempt 2 of 2, from seed 19), then the remaining
cells in order, then the deferred Fireworks cell.

## Addendum 2026-09-03T19:45Z — panel complete; eleven rows eligible

The chain ran to the end. The last cell (grok-4.6, attempt 2) settled at
19:42Z. No cell is active and nothing is reserved. Spend in artifacts is
$23.71; the spend guard's conservative figure, which charges every
reconciled or retried reservation in full, is $30.29. Both sit far under
the $100 ceiling.

| Cell | Outcome |
| --- | --- |
| gpt-5.6-luna (OpenAI flex) | Attempt 2 resumed from seed 19 at 03:59Z and **completed** at 04:09Z: 580/580, $0.43. |
| gemini-3.1-flash-lite | **Completed** on attempt 1 at 04:20Z, $0.46. |
| qwen3.5-27b (SiliconFlow) | **Completed** on attempt 1 at 05:24Z, $0.99. |
| gemini-3.7-flash | **Completed** on attempt 1 at 05:47Z, $1.88. |
| glm-5 (Streamlake) | Aborted at seed 25 of 29 on two consecutive malformed replies (`every action must be an object`). **Ineligible on model behavior**, no rerun, $1.42 in the artifact. |
| kimi-k2.5 (SiliconFlow) | **Completed** on attempt 1 at 07:24Z, $1.58. |
| minimax-m3 (Modelrun) | **Completed** on attempt 1 at 07:44Z, $2.10. |
| grok-4.3 (xAI) | **Completed** on attempt 1 at 07:52Z, $3.52. |
| gpt-5.4-mini (OpenAI) | **Completed** on attempt 1 at 08:08Z, $2.45. |
| claude-haiku-4.5 (Anthropic) | Aborted at seed 14 of 29 on two consecutive invalid-JSON replies with zero truncation (peak 918 output tokens per call; 260 malformed decisions across the 13 completed seeds). **Ineligible on model behavior**, no rerun, $1.78 in the artifact. |
| gpt-5.6-sol (OpenAI flex) | Both attempts (08:26Z and 08:43Z) aborted within seconds on two consecutive billed responses that carried no `choices` array (`api_error: 'choices'`; spend guard: no cost telemetry). Not a 429-class status, so the transient backoff did not apply. **Excluded at the infrastructure limit.** $0.23 absorbed conservatively across the two reconciliations. |
| grok-4.6 (xAI) | Attempt 1 started 08:44Z and aborted at 09:42Z at seed 13 of 29 during a local network outage: two consecutive read timeouts at the spend guard (`The read operation timed out`), then `No route to host` on the runner's usage poll, which crashed the runner before it logged the failure. Reconciled at 16:03Z, $0.26 absorbed. The attempt-2 relaunch at 16:03Z was refused by the route preflight (xAI zdr status -2, 30-minute uptime 91.1%) with no attempt consumed, so the deferred Fireworks cell ran first. Attempt 2 resumed from the checkpoint at 18:30Z and **completed** at 19:42Z: 580/580, $9.18 in the artifact. Twelve seeds come from attempt 1 and seventeen from attempt 2, the same resume rule deepseek-v4-flash and gpt-5.6-luna used. |
| glm-5.3-flash (Fireworks) | Launched last as deferred, 16:04Z. **Completed on attempt 1** at 18:29Z: 580/580, $0.60 in the artifact. The transient backoff fired 122 times on this cell (121 Fireworks HTTP 429, one 503; up to four retries on a single decision) and absorbed $2.30 of reservation conservatively. Without the amendment this cell would have lost both attempts in its first hour. |

Final tally: 11 complete and gate-passing, 3 ineligible on model behavior
(gpt-oss-20b, glm-5, claude-haiku-4.5), 2 excluded at the infrastructure
limit (qwen3.8-flash, gpt-5.6-sol). The Holm family stays at the registered
sixteen; the analysis applies the full family size when rows are missing.

Two observations, recorded and not acted on:

- gpt-5.6-sol's failure signature (billed response, no `choices`) is the
  one Cloudflare showed for glm-5.3-flash at smoke. The transient backoff
  deliberately does not cover it. Whether it should is a question for the
  next contract, not this one; widening the trigger list after seeing the
  outcome would be outcome-dependent.
- grok-4.6's attempt-1 record in `openrouter-reservations.json` still reads
  `active` with no finish time. The runner crashed on the usage poll during
  the outage before its failure-logging step, and the retry path appends a
  fresh attempt without closing a prior one left open that way. The attempt
  counter is correct (2 of 2) and the cell settled; only the history entry
  is unclosed.
- That attempt was lost to the operator's network, not the provider. The
  frozen two-attempt limit does not distinguish the two, so it counted.

Analysis is still refused: `analyze_publication_panel.py` requires
`publication_authorized: true` across the lane, registry, protocol, and
pricing snapshot, and all four remain `false`. It reports
`no-eligible-artifacts` until the owner flips them in one commit that says
so. Publication remains unauthorized.

## Addendum 2026-09-03T20:45Z — publication family rule amended after data: accounted-for rows, floor 8

This decision was taken by the owner on 2026-09-03 after seeing the panel
outcome above: eleven of sixteen registered rows eligible, three ineligible on
model behavior, two excluded at the infrastructure limit. It is a post-data
amendment and is recorded as one (`exclusion_policy.decided_after_data: true`
in the publication protocol). Nothing about how any row was run, scored, or
gated changes; both fingerprints are unchanged (a600b7da0c302231,
c582e126bbb6af10).

**The rule before.** `publication_ready` required all sixteen registered rows
to be eligible: `minimum_headline_models` was 16 in the lane, equal to the
family size. Under that rule the panel could not be published at all, because
the frozen rules forbid rerunning the three model-behavior rows and the two
infrastructure-limit rows have used both attempts.

**The rule now.** A registered row is "accounted for" when it is either
eligible (a passing artifact) or excluded under a rule that was frozen before
the panel ran, with its evidence retained and listed in a committed exclusion
register. Publication requires every registered row to be accounted for. A
registered row that is missing with no register entry still blocks
publication. The register is `config/sota_v5_panel_exclusions.json`; the rule
is `exclusion_policy` in `config/sota_v5_publication_protocol.json`; the lane's
`minimum_headline_models` is now 8 with a `minimum_headline_models_basis`
pointer to that policy.

**Why the family stays at sixteen.** Holm's adjustment divides alpha by the
number of hypotheses still open. Shrinking the family to the eleven rows that
happened to come back would make every remaining p-value easier to reject,
and which rows came back was decided by the data. The family therefore stays
at the registered sixteen and the analysis applies the full size when rows
are missing, as the 19:45Z addendum already stated.

**Where the floor of 8 comes from.** Eight is the cohort size the sota-v3
amendment 3 of 2026-08-06
(docs/run_logs/sota-v3-design-amendment-2026-08-06.md) accepted as
publishable, before any v5 or v6 model data existed. It is reused here as a
prior decision, not derived from the count of eligible rows; eleven clears it
with margin, and a panel that lost more than eight rows would still not
publish.

**Register entries.** Every entry names the frozen rule it was excluded under
and the retained checkpoint with its SHA-256. The two infrastructure-limit
cells have empty-episode checkpoints, hashed all the same.

| Row | Status | Frozen rule | Attempts | Decisions | Cost (USD) |
| --- | --- | --- | --- | --- | --- |
| gpt-oss-20b (DeepInfra) | ineligible-model-behavior | max_decision_failure_rate 0.02 (SOTA_V5_POLICY); measured 0.0207 | 1 | 580 | 0.0989 |
| claude-haiku-4.5 (Anthropic) | ineligible-model-behavior | fail-fast on two consecutive malformed replies; no rerun on model behavior | 1 | 260 | 1.7801 |
| glm-5 (Streamlake) | ineligible-model-behavior | fail-fast on two consecutive malformed replies; no rerun on model behavior | 1 | 480 | 1.4243 |
| qwen3.8-flash (Alibaba) | excluded-infrastructure-limit | rerun_policy two-attempt infrastructure limit | 2 | 0 | 0.0 |
| gpt-5.6-sol (OpenAI flex) | excluded-infrastructure-limit | rerun_policy two-attempt infrastructure limit | 2 | 0 | 0.0 |

The two infrastructure-limit rows carry zero in the artifact; the $0.23
absorbed by gpt-5.6-sol's reconciliations sits in the spend guard's
conservative ledger, not in a result artifact.

**What this addendum does not do.** `publication_authorized` stays `false` in
the lane, registry, protocol, and pricing snapshot. The analyzer and packager
do not yet read the register or the accounted-for rule; those changes land
separately, and the flags flip only after they do and the analysis artifacts
are produced under the amended rule.

## Addendum 2026-09-04T00:15Z — publication authorized; release built and verified

This closes the sota-v5 / v6-spec panel. The owner authorized publication on
2026-09-03 after the completed panel passed the amended accounted-for rule
(addendum 2026-09-03T20:45Z above). Everything below happened after the
analyzer and packager were taught the rule and after their verification
passed; the flags flipped last.

**Verification before the flip.** Contract fingerprint `a600b7da0c302231` and
OpenRouter scaffold `c582e126bbb6af10` reproduce from the working tree; no
file under `gm_bench/` or `schemas/` changed since the panel commit. The full
suite (1,116 tests) and `ruff` passed. The 29 escrowed seeds reproduce both
committed digests (execution hash and salted hiding commitment) and none of
them appears as a token in any tracked file. The tracked v2 row
`results/leaderboard/openrouter-gpt-5.6-luna-openai.json` and the v2 site
dataset are byte-identical to the panel commit. The exclusion register agrees
with `run-state.json` on every row's status, reason, attempts, decisions, and
cost.

**One more analyzer fix.** The dry run against authorized copies of the four
records found that the analyzer rejected the gpt-oss-20b raw artifact on the
frozen 0.02 decision-failure gate (as it should) and then, because any
rejection kept the status `partial`, refused to publish the accounted-for
family. A rejected artifact whose row the frozen register already excludes is
now that register's evidence rather than an unexplained rejection; a rejection
the register does not cover still keeps the analysis partial. Landed with a
regression test before the flip. With that fix the dry run returned
`status: complete`, `publication_ready: true`, eleven eligible, sixteen
accounted for, no missing rows, no config errors.

**The flip.** `publication_authorized` is `true` in the lane, registry,
protocol, and pricing snapshot in one commit that says so. The
preregistration test now pins the flags true with the decision recorded
beside it. The zero-spend rehearsal no longer requires the checked-in records
to be locked; it authorizes only its own in-memory copies.

**The analysis.** `results/analysis/publication-panel-analysis-v5.json` was
produced from the operator's raw artifacts with the verified escrow supplied
through the environment, exactly as the panel runner supplies it. It is
byte-identical to the pre-flip dry run and contains no seed value. Every
eligible model trails `pick-trader` (247.109). Ten of eleven headline rows
reject at Holm-adjusted alpha 0.05 against the family of sixteen;
gemini-3.7-flash (mean lift -23.4, Holm-adjusted p 0.221) does not. Within-seed
noise is unmeasured under the one-repeat lane and every row says so.

**The release.** `releases/sota-v5-publication-2026-09-03/` holds the manifest,
`SHA256SUMS.txt`, and a README. The archive
`gm-bench-sota-v5-publication-2026-09-03.zip` (24 entries: frozen configs and
smoke manifest, exclusion register, analysis, eleven redacted headline and
three redacted diagnostic artifacts, run-state and reservation metadata) was
built and then verified by the packager's verify mode, and its checksum
matches the committed sums. No raw artifact and no seed value is in it. The
archive is attached beside the checksums, not committed.

**Adjacent fix.** The v5 site study builder still read the top-level
`results/leaderboard/` directory after the packager moved the headline rows
under `results/leaderboard/sota-v5/`; it now reads the contract-scoped
directory. It writes only where asked. The public site stays on sota-v2;
putting this panel on the site is a separate decision.

**Still recorded, not fixed.** The luna row billed about $0.125 per million
prompt tokens against the $0.10 snapshot; the transient-retry counts live only
in the spend guard's ledger and not in the artifacts; the grok-4.6 attempt-1
reservation entry is still marked active in `openrouter-reservations.json`.
