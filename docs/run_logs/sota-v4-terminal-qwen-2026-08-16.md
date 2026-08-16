# SOTA-v4 terminal Qwen record — 2026-08-16

This record closes the paid SOTA-v4 execution phase. It does not authorize a
panel, publication, or another model call.

## Outcome

The machine-scoped authorization admitted only
`openrouter-qwen3.8-max-alibaba` for infrastructure attempt 2 of 2. The exact
Alibaba route accepted the immediate authenticated, zero-completion route and
price preflight, then rejected the one completion request with HTTP 400:

> Reasoning is mandatory for this endpoint and cannot be disabled.

The frozen lane required `OPENROUTER_REASONING_ENABLED=false`. The response
therefore establishes route incompatibility rather than a benchmark result.
There was no generation, completed decision, episode, score, or raw result
artifact. No other model launched. The reservation ledger marks the Qwen cell
`excluded` at the two-attempt infrastructure limit.

## Accounting

The live account read observed a `$0.00` aggregate run delta after the final
request. Aggregate account usage is not authoritative per-call settlement, so
the guard conservatively absorbed the full second `$0.1832184` unknown-call
bound. Guard-reported SOTA-v4 spend is therefore `$0.3664368`, with no active
call reservation or telemetry block remaining.

The same free preflight sequence found that DeepSeek's live prompt and
completion prices exceeded the frozen planning snapshot. No DeepSeek
completion call was made.

## Local evidence inventory

The underlying runtime files remain local under
`data/publication/sota-v4-smokes/`. They are not committed because the project
keeps raw/checkpoint execution evidence outside the source release. The hashes
below bind this terminal record to the retained local files without exposing
private seeds, credentials, or account totals.

| Role | Local path | SHA-256 |
| --- | --- | --- |
| Attempt-1 aborted checkpoint | `checkpoints/failed-attempts/openrouter-qwen3.8-max-alibaba--4096--attempt-1.json` | `d292827ac210cb192e5572b7968a8603973a502512b1e0243628740f03c9ac20` |
| Attempt-2 aborted checkpoint | `checkpoints/openrouter-qwen3.8-max-alibaba--4096.json` | `fc9560ac3687e6b951d6435fc53741aae4dfcd61a6d15dce75c1dd54f30af6b7` |
| Settled spend guard | `openrouter-call-spend-guard.json` | `9efcd8e890e1680fba3ed31e2109ca32de3f2da93a8e9dfb182151070722f80e` |
| Terminal reservation ledger | `openrouter-reservations.json` | `b2ef2d5a3a7731330381f1b73d8324564e7d1a1d5af1457666469bd8b7baa4fc` |
| First reconciliation | `openrouter-spend-reconciliation.json` | `c120029458da571c96459bf74fc501a8517d87627ac8c9d7366cc6446238118d` |
| Final reconciliation | `openrouter-spend-reconciliation-2.json` | `76eed55c2fe1a1362e68e641ee1c4320f70604c846db7bef2da06e3d0a8a2ec1` |
| Run state | `run-state.json` | `f1f043348084502cec1555925ad223d50633db8b5c3169d34a492d989654947e` |

Both checkpoints contain zero episodes and zero completed decisions. The run
state names only Qwen in `launched_model_ids`. The final spend guard records
`reported_spend_usd=0.3664368` and `active_call_reservation_usd=0`.

## Protocol consequence

SOTA-v4 cannot satisfy its preregistered all-eight-smokes requirement under the
uniform reasoning-disabled policy. Qwen may not be rerun or replaced in place
after this observed outcome. SOTA-v4 remains terminal with spend, smoke, panel,
and publication authorization false. Any new cohort or reasoning policy must be
frozen prospectively under a successor contract before another completion call.
