# SOTA-v5 paid smoke grant log — 2026-09-01

Owner-authorized single-attempt grants for the sixteen-model v6 smoke
sequence, issued in the frozen ascending-cost order. The
`paid_smoke_authorization` object in the four frozen config records is
rewritten in place per model, so this log carries the full grant and
consumption history; the authoritative per-attempt ledger (reservations,
spend, exclusions) lives in
`data/publication/sota-v5-smokes/openrouter-reservations.json`.

All runs: smoke preset, compact profile, one repeat, 4,096-token output
ceiling including reasoning, strict failure handling, zero repair attempts,
serialized calls, $100 operator ceiling.

| # | model_id | attempts | outcome |
| - | --- | --- | --- |
| 1 | openrouter-gpt-oss-20b-deepinfra | 2 | **accepted**. Attempt 1 failed on the env-precedence bug (provider defaults stomped the reasoning/JSON pins; two HTTP 400s, spend reconciled). A zero-call local checkpoint-provenance abort in between was voided, not counted (see `voided_attempts` in the ledger and the archiver fix commit). Attempt 2 clean: 4/4 decisions, 729 output tokens, $0.0009. |
| 2 | openrouter-nemotron-3-nano-30b-a3b-crusoe | 1 | **ineligible — model behavior**. One malformed midseason decision ("every action must be an object") plus one illegal trade under the registered strict JSON-mode condition. All 6 calls finished `stop`, zero truncation, max 93 output tokens/call, so this is not cap pressure or infrastructure. Model behavior never authorizes a rerun; the row is excluded from the panel with its artifact retained. |
| 3 | openrouter-deepseek-v4-flash-0731-together | 1 | **accepted**. Clean, 604 output tokens, $0.0048. |
| 4 | openrouter-glm-5.3-flash-cloudflare | 2 | **excluded — infrastructure attempt limit**. Both attempts: Cloudflare returned billed responses with no `choices` array (`api_error: 'choices'`), two consecutive calls each time; unknown spend reconciled after each. |
| 5 | openrouter-gpt-5.6-luna-openai | 1 | **accepted**. Clean on the flex tier, 17.2s API for 4 decisions, $0.0037. |
| 6 | openrouter-gemini-3.1-flash-lite-google-ai-studio | 1 | **accepted**. Clean on the flex tier, 4.4s API, $0.0041. |
| 7 | openrouter-minimax-m3-parasail | 2 | **excluded — infrastructure attempt limit**. Parasail HTTP 429 rate limiting on both attempts; unknown spend reconciled after each. |
| 8 | openrouter-qwen3.5-27b-siliconflow | 1 | **accepted**. Clean, $0.0083. |
| 9 | openrouter-gemini-3.7-flash-google-ai-studio | 1 | **accepted**. Mandatory-reasoning row at low effort: 3,071 reasoning tokens billed inside the ceiling, peak 1,706 output tokens/call against the 3,072 pressure threshold, zero truncation, $0.0182. |
| 10 | openrouter-glm-5-streamlake | 1 | **accepted**. Clean decisions; one illegal action scored as a 2.5 protocol penalty (scored behavior, not a gate failure). $0.0169. |
| 11 | openrouter-kimi-k2.5-siliconflow | 1 | **accepted** (int4 quantization caveat carries to publication copy). One illegal action penalty. $0.0183. |
| 12 | openrouter-qwen3.5-397b-a17b-parasail | 1 | **withdrawn by the 2026-09-01 route-and-cohort amendment**. Endpoint preflight refused twice on missing 30-minute uptime telemetry (free, no attempt consumed); once telemetry returned, attempt 1 hit Parasail HTTP 429 on two consecutive calls and its unknown spend was reconciled. The final-retry grant was staged and then voided unconsumed when the row was withdrawn. |
| 13 | openrouter-grok-4.3-xai | 1 | **accepted**. One illegal action penalty. $0.0337. |
| 14 | openrouter-gpt-5.4-mini-openai | 1 | **accepted**. Clean, $0.0218. |
| 15 | openrouter-claude-haiku-4.5-anthropic | 1 | **accepted**. All four decisions initially malformed but recovered in-round with zero repair attempts and zero failures; the frozen gate accepts recovered rounds as scored behavior. $0.0308. |
| 16 | openrouter-grok-4.6-xai | 1 | **accepted**. Frontier mandatory-reasoning row: 4,374 reasoning tokens billed at the completion rate inside the per-call ceiling (observed cost matches the within-cap assumption), peak 1,054 output tokens/call, zero truncation, $0.1110. |

Measured run-directory spend after the sixteenth model: $0.39 conservative
(reconciliations charge full pre-call bounds when telemetry is missing;
observed account deltas are lower). Ceiling $100.

The three excluded rows (nemotron behavior; glm-5.3-flash and minimax-m3
infrastructure) follow the 2026-08-31 amendment's rule: excluded from the
panel with evidence retained, no lane abort, Holm family stays 16.

## Route-and-cohort amendment rows (2026-09-01, after commit 612896e)

The 2026-09-01 route-and-cohort amendment
(docs/run_logs/sota-v5-v6-route-and-cohort-amendment-2026-09-01.md) withdrew
rows 2, 4, 7 and 12 above and registered four new cells with a fresh
two-attempt budget each. The unconsumed attempt-2 grant for the withdrawn
qwen3.5-397b Parasail row was voided in place.

| # | model_id | attempts | outcome |
| - | --- | --- | --- |
| 12' | openrouter-qwen3.8-flash-alibaba | 1 | **accepted**. Clean, 801 output tokens, no illegal actions, $0.0047. |
| 4' | openrouter-glm-5.3-flash-fireworks | 1 | **withdrawn by owner direction**. Attempt 1: Fireworks HTTP 429 on two consecutive calls (the model is the most-used on OpenRouter this week); unknown spend reconciled. The staged final-retry grant was voided unconsumed when the owner moved the row to DeepInfra fp8 (amendment addendum). |
| 4'' | openrouter-glm-5.3-flash-deepinfra | 1 | **accepted** (fp8 quantization caveat carries to publication copy). Mandatory-reasoning row at low effort: clean, no illegal actions, 2,073 output tokens across four decisions including reasoning, zero truncation, $0.0026. Sixteen of sixteen registered rows now hold accepted smokes. |
| 2' | openrouter-nemotron-3-super-120b-a12b-digitalocean | 1 | **accepted**. Clean decisions; one illegal action scored as a 2.5 penalty. $0.0075. |
| 7' | openrouter-minimax-m3-modelrun | 1 | **accepted** (fp4 quantization caveat carries to publication copy). Clean, no illegal actions, $0.0264. |

## Re-run under the fixed one-paid-call rule (2026-09-01, after PR #129 review)

Review of PR #129 found that `FailFastAgent` dropped `pays_for_calls`, so every
smoke above ran with the five-round query loop open; fourteen artifacts
record 5 to 7 calls for 4 decisions. All sixteen manifest entries were
invalidated (preserved under `invalidated_entries_2026_09_01`) and every
model re-granted one attempt in ascending-cost order in a fresh run
directory, `data/publication/sota-v5-smokes-v2`. Each accepted artifact below
records exactly four calls, one per phase.

| model_id | attempts | outcome |
| --- | --- | --- |
| openrouter-gpt-oss-20b-deepinfra | 2 | **accepted** on the final attempt after an eighteen-minute cool-down. Attempt 1: DeepInfra HTTP 429 on two consecutive calls (not billed; reconciled). |
| openrouter-glm-5.3-flash-deepinfra | 1 | **accepted** |
| openrouter-deepseek-v4-flash-0731-together | 1 | **accepted** |
| openrouter-qwen3.8-flash-alibaba | 1 | **accepted** |
| openrouter-gpt-5.6-luna-openai | 1 | **accepted** |
| openrouter-gemini-3.1-flash-lite-google-ai-studio | 1 | **accepted** |
| openrouter-nemotron-3-super-120b-a12b-digitalocean | 2 | **excluded — infrastructure attempt limit**. DigitalOcean HTTP 429 on two consecutive calls on both attempts, eighteen minutes apart; unknown spend reconciled after each. DigitalOcean is the only route for this identity that meets the frozen eligibility rule (DeepInfra bf16 advertises no structured_outputs), so the slot needs an owner decision. |
| openrouter-qwen3.5-27b-siliconflow | 1 | **accepted** |
| openrouter-gemini-3.7-flash-google-ai-studio | 1 | **accepted** (mandatory low reasoning inside the ceiling) |
| openrouter-glm-5-streamlake | 1 | **accepted** |
| openrouter-kimi-k2.5-siliconflow | 1 | **accepted** (int4 caveat) |
| openrouter-minimax-m3-modelrun | 1 | **accepted** (fp4 caveat) |
| openrouter-grok-4.3-xai | 1 | **accepted** |
| openrouter-gpt-5.4-mini-openai | 1 | **accepted** |
| openrouter-claude-haiku-4.5-anthropic | 1 | **accepted** |
| openrouter-grok-4.6-xai | 1 | **accepted** (frontier; mandatory low reasoning inside the ceiling) |

A driver bug on the third pass tried to re-grant an already-accepted row; the
grant gate refused before any call, consuming nothing.

| openrouter-nemotron-3.5-lightning-coreweave | 1 | **ineligible — model behavior**. Replacement identity for the excluded nemotron-3-super slot (amendment addendum 20:45Z). Exactly four calls, all finished `stop`, no truncation; one unrecoverable draft decision ("every action must be an object"), one repaired scout, one illegal trade. Model behavior never authorizes a rerun; the slot is open again. |
| openrouter-gpt-5.6-sol-openai | 1 | **accepted**. Replacement identity for slot 16 (amendment addendum 21:00Z). Exactly four calls, clean, no illegal actions. Sixteen of sixteen registered rows now hold accepted one-call smokes. |

## Route return to Fireworks (2026-09-02)

The DeepInfra fp8 route for z-ai/glm-5.3-flash fell under the 99.0% 24-hour
uptime floor and stopped publishing 30-minute telemetry on 2026-09-02, so the
row returned to Fireworks, the frozen rule's winner (amendment addendum,
evening of 2026-09-02). The accepted DeepInfra entry above is withdrawn with
its route and kept under `withdrawn_entries_2026_09_02` in the manifest. The
Fireworks cell is new in `data/publication/sota-v5-smokes-v2` with a fresh
two-attempt budget; its consumed 2026-09-01 attempt stays in the
`sota-v5-smokes` ledger.

| model_id | attempts | outcome |
| --- | --- | --- |
| openrouter-glm-5.3-flash-fireworks | granted, not yet run | Attempt 1 of 2 granted on the owner's 2026-09-02 instruction. |
