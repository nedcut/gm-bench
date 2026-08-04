# sota-v3 lineup refresh — 2026-08-04

Supersedes the route state recorded in
[`sota-v3-route-preflight-2026-08-03.md`](sota-v3-route-preflight-2026-08-03.md),
which is left unedited as the historical record of that day's probe. Two of the
ten routes it describes are no longer in the lineup, and its closing claim that
all ten pass was true when written and is not a standing claim.

**Zero completion calls, zero spend.** No gate was granted or changed; every
paid authorization remains `false`.

## Cohort changes

Cohort size stays at **ten**, so the Holm family size, the 16x1 allocation, and
the power selection are untouched.

| Slot | Was | Now | Reason |
| --- | --- | --- | --- |
| Qwen | `qwen/qwen3.7-plus` @ `alibaba/fp8` | `qwen/qwen3.8-max` @ `alibaba` | Released 2026-08-03; owner elected to adopt immediately |
| DeepSeek | `deepseek/deepseek-v4-flash-0731` @ `deepseek/fp8` | same model @ `cloudflare/fp8` | First-party route deranked to status `-5` |
| MiniMax | `minimax/minimax-m3` @ `minimax/fp8` | same model @ `deepinfra/fp8` | First-party route deranked to status `-2` |

Both substitutions follow
[`docs/ROUTE_SUBSTITUTION_POLICY.md`](../ROUTE_SUBSTITUTION_POLICY.md): same
model, same FP8 quantization, highest 24h availability among eligible routes,
identical published rates.

The Qwen change is a **cohort amendment**, not a substitution — a different
model, adopted deliberately. It replaces Alibaba's cost-effective tier with
their flagship, which bills 6.25x/4.69x per token.

## How volatile the routes actually are

Everything below was observed within roughly twelve hours. None was announced.

| Route | Observed |
| --- | --- |
| `deepseek/fp8` | status 0 with the cohort's best throughput → deranked to `-5`, 30m availability 78% → recovered to status 0 the same day |
| `minimax/fp8` | status 0 → deranked to `-2` |
| `alibaba` (qwen3.7-plus) | endpoint tag silently moved to `alibaba/fp8` |
| `novita/fp8` (glm-5.2) | discount moved 55.1% → 50% |

The DeepSeek recovery is worth stating plainly: the substitution was not
strictly necessary in hindsight. It is kept because Cloudflare holds the better
24h record, but the honest reading is that the route was transiently deranked,
not lost.

## Pricing: promotional rates are no longer reserved against

`openai/gpt-5.6-luna` and `z-ai/glm-5.2` were both found pinned at 50%-off
promotional rates. The GLM discount moved 55.1% → 50% within hours of being
recorded, which is what surfaced the problem.

The snapshot now pins **undiscounted list rates** for every route. A promo is
not a floor, and a reservation computed from one is wrong the moment it ends.

| Route | Was pinned (promo) | Now pinned (list) |
| --- | --- | --- |
| `openai/gpt-5.6-luna` | 1e-07 / 6e-07 | 2e-07 / 1.2e-06 |
| `z-ai/glm-5.2` | 7e-07 / 2.2e-06 | 1.4e-06 / 4.4e-06 |

## Reservation

| | Amount |
| --- | --- |
| Previous reservation | $107.81 |
| After the Qwen amendment | $119.76 |
| **After pinning list rates** | **$127.29** |
| Committed operator ceiling | **$150.00** (raised from $120.00, 2026-08-04) |

Call count is unchanged at 3,240.

The $120 ceiling was chosen against a $119.76 reservation that turned out to
depend on two 50%-off promotional rates. Pinning list rates pushed the
committed plan over its own committed ceiling — a state nothing detected,
because the reservation and the ceiling lived in different files and nothing
compared them. `test_the_committed_plan_fits_under_the_committed_ceiling` now
does, at zero cost, so adding a model or losing a discount fails a test rather
than surfacing when someone tries to authorize a run.

The ceiling was raised to **$150.00** to clear the current reservation with
headroom for a further substitution or list-price move.

Reserve is concentrated in four models: Gemini 3.6 Flash (22.4%), Grok 4.5
(19.9%), Claude Sonnet 5 (17.4%), and Mistral Medium 3.5 (13.0%).

### Projected actual spend is far below either figure

From July smoke telemetry reprojected at current rates, models emit **48–640
output tokens per decision** against a 4,096-token reservation, and Grok's
observed internal reasoning was **516 tokens** against 4,096 reserved.

Projected actual spend is roughly **$35–45**. The reservation is a backstop, not
a forecast, and the gap is concentrated in the reserved reasoning headroom for
Gemini and Grok.

## Runner changes made alongside

- The zero-call probe now checks **every** route and reports the full set of
  failures. Exiting on the first one had twice presented a partial picture as a
  complete one. Paid phases still abort on the first bad route.
- Endpoint eligibility now enforces availability floors on two windows, 90%
  (30m) and 95% (24h).
- Live rates are compared against the committed snapshot on every probe.
  An increase fails the route; a decrease is reported and allowed.
- `budget_policy.operator_ceiling_usd` is now enforced ahead of the cell loop.
  It had been declared in config and read by nothing.
- An autouse test fixture blocks the suite from inheriting a live provider
  credential, after a test spent $0.436198 across 38 live calls.

## What this does not establish

Unchanged: `spend_authorized`, `smoke_execution_authorized`,
`panel_execution_authorized`, `publication_authorized` all `false`; registry
`route-preflight-ready`, not `frozen`; `exact_route_acceptance` `unresolved`.

Route acceptance does **not** carry across a substitution. Cloudflare and
DeepInfra are new counterparties whose data-handling terms have never been
reviewed for this project.
