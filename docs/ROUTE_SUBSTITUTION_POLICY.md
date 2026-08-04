# Route substitution policy

When a pinned OpenRouter route stops being eligible, this is how it gets
replaced. The point is to make the decision mechanical, so that a route failing
at an inconvenient moment does not turn into an improvised choice about what the
benchmark measures.

Adopted 2026-08-04, after three substitutions in two days were each decided ad
hoc.

## Why this exists

Route health is volatile on a timescale shorter than a panel run. Measured over
roughly twelve hours on 2026-08-04:

| Route | Observed |
| --- | --- |
| `deepseek/deepseek-v4-flash-0731` @ `deepseek/fp8` | status 0, best throughput in the cohort → deranked to `-5`, serving 78% of requests → recovered to status 0 |
| `minimax/minimax-m3` @ `minimax/fp8` | status 0 → deranked to `-2` |
| `qwen/qwen3.7-plus` @ `alibaba` | endpoint tag silently moved to `alibaba/fp8` |
| `z-ai/glm-5.2` @ `novita/fp8` | discount moved 55.1% → 50% |

None of these were announced. All were found by running the free probe.

## What makes a route ineligible

A pinned route is ineligible if **any** of the following holds. These are all
enforced by `_endpoint_issues` in `scripts/run_publication_matrix.py`; the free
zero-call probe reports every failing route in one pass.

1. No endpoint matches the pinned `provider_name`, `tag`, and `name`.
2. Endpoint `status` is not `0`.
3. The endpoint does not advertise `max_tokens`, `reasoning`, and — when the
   lane sets `OPENROUTER_JSON_MODE=true` — `response_format`.
4. `max_completion_tokens` is missing, non-integer, or below the registered
   output cap.
5. `uptime_last_30m` is missing, non-numeric, non-finite, or below **90%**.
6. `uptime_last_1d` is missing, non-numeric, non-finite, or below **95%**.
7. The live base rate for the pinned route is **above** the committed pricing
   snapshot. A rate below the snapshot is reported, not blocked.

On (5) and (6): both windows gate because they detect different failures. The
24h figure cannot see an outage in progress — the deranked DeepSeek route still
read 99.24% over 24h while serving 78% of requests. Both floors sit well below
the observed noise band, because these readings drift about half a point between
consecutive polls; a 99% 24h floor was measured rejecting two healthy cohort
members while still passing the route that had actually failed. An absent or
malformed figure is unknown health, not evidence that the route clears the
floor, so it blocks the same way unverifiable pricing blocks.

## Choosing the replacement

**Prefer waiting.** Deranking is frequently transient — the first-party DeepSeek
route recovered on its own within a day. If the paid phase is not imminent,
re-probe before substituting.

Where a substitution is required, take the eligible endpoint for the **same
model** with the **highest `uptime_last_1d`**, subject to:

- **Same quantization** as the outgoing route. A different precision is a
  different numerical model, not a different host, and is out of scope for a
  substitution — treat it as a cohort amendment.
- All eligibility criteria above.
- `max_completion_tokens` at or above the registered cap.

Deliberately *not* criteria: price, throughput, latency, and first-party status.

- **Price** must not steer the choice; that is how a benchmark quietly starts
  measuring whichever host is cheapest this week. Record the new rate and let
  the reservation move.
- **Throughput and latency** are the worst possible signals here. The DeepSeek
  route had the cohort's best throughput hours before it failed.
- **First-party status** is not load-bearing. It was framed as one in the
  original route roles, but on the axis that actually matters mid-panel —
  staying up — a model's author has no particular advantage. Cloudflare beat
  DeepSeek on its own model.

## Recording it

A substitution is a cohort **route** change, not a cohort **membership** change,
so it does not touch the Holm family size, the allocation, or the power
selection. It does require, in the same change:

1. `config/sota_v3_models.json` — `id`, `upstream_provider`,
   `upstream_provider_slug`, `endpoint_tag`, `endpoint_name`,
   `catalog_route_status`, `catalog_uptime_last_30m`,
   `catalog_supported_parameters`, and a `role` naming the date, the outgoing
   route, and the observed reason.
2. The same `id` in `required_smokes` and in `exact_route_acceptance.entries`.
3. `config/sota_v3_pricing_snapshot.json` — `provider_slug`, `endpoint_name`,
   and the **undiscounted list rates** (see below).
4. Regenerate `results/analysis/sota-v3-pre-smoke-cost-estimate.json` and check
   the result against `budget_policy.operator_ceiling_usd`.
5. A dated entry in the decision log, and a run log if a probe was run.

Substituting a host does **not** carry over route acceptance. `authenticated`,
`verified_at_utc`, `route_evidence_sha256`, and the whole `privacy_acceptance`
block describe a specific provider and must be re-established for the new one.

## Pricing

Pin the **undiscounted list rate**, never a promotional rate.

The reservation is a safe upper bound, and a promo is not a floor. On
2026-08-04 the GLM 5.2 Novita discount moved from 55.1% to 50% within hours,
and `openai/gpt-5.6-luna` and `z-ai/glm-5.2` were both found pinned at 50%-off
prices — which is the only reason the panel had appeared to fit under the
$120 ceiling in force at the time. Where the endpoint reports a `discount`, record
`live_rate / (1 - discount)`.

A live discount then only ever brings the run in under reserve, which is the
direction that cannot hurt.

## When to re-probe

Immediately before any paid phase, every time. A passing probe has a shelf life
measured in hours, and a stale pass is not a pass.
