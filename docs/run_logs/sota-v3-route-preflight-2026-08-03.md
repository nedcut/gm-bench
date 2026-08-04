# sota-v3 authenticated route preflight — 2026-08-03

First authenticated contact with the ten registered `sota-v3` routes. **Zero
completion calls, zero spend, no run state written.** This run does not
authorize a smoke or a panel, and did not change any spend gate.

## Run configuration

| Field | Value |
| --- | --- |
| Contract fingerprint | `a523bdfcebe47bbd` |
| Command | `python3 scripts/run_publication_matrix.py route-preflight --contract sota-v3` |
| Gate granted | `route_preflight_authorized` (owner, 2026-08-03) |
| Gates unchanged | `spend_authorized`, `smoke_execution_authorized`, `panel_execution_authorized`, `publication_authorized` — all still `false` |
| Measured spend | $0.00 |

For `route-preflight` the runner validates the endpoint and then `continue`s
before reaching `subprocess.run(command)`, so no model subprocess can launch.
The runner also skips run-directory creation and `_write_run_state` for this
phase. `test_zero_call_route_preflight_has_separate_authorization_and_never_launches_child`
pins both properties by asserting that no child launches and no run-state,
raw, or checkpoint directory is created.

## Result: nine of ten pins correct, one stale, no route dead

The first run **aborted at cell 7 of 10**:

```text
OpenRouter endpoint preflight failed for openrouter-qwen3.7-plus-alibaba:
no healthy OpenRouter endpoint matches provider='Alibaba' tag='alibaba'
name='Alibaba | qwen/qwen3.7-plus-20260602'
```

The runner exits on first failure, so three routes were still untested at that
point. Rather than infer their status, each of the ten pins was checked
directly against the authenticated endpoints API:

| Pinned route | Result |
| --- | --- |
| `openrouter-gpt-5.6-luna-openai` | matches, status 0 |
| `openrouter-claude-sonnet-5-bedrock` | matches, status 0 |
| `openrouter-gemini-3.6-flash-google-ai-studio` | matches, status 0 |
| `openrouter-grok-4.5-xai` | matches, status 0 |
| `openrouter-glm-5.2-novita` | matches, status 0 |
| `openrouter-minimax-m3-minimax` | matches, status 0 |
| `openrouter-qwen3.7-plus-alibaba` | **tag mismatch** — see below |
| `openrouter-mistral-medium-3.5-mistral` | matches, status 0 |
| `openrouter-deepseek-v4-flash-0731-deepseek` | matches, status 0 |
| `openrouter-hy3-tencent` | matches, status 0 |

All ten advertise `response_format`, which the lane requires via
`OPENROUTER_JSON_MODE=true` and `OPENROUTER_REQUIRE_PARAMETERS=true`.

## The qwen mismatch was a stale label, not a dead route

The live Alibaba endpoint for `qwen/qwen3.7-plus` is healthy — status 0,
uptime 99.99% — and its `provider_name` and `name` match the registry exactly.
Only the tag differs:

| Field | Registered | Live |
| --- | --- | --- |
| `endpoint_tag` | `alibaba` | `alibaba/fp8` |
| `provider_name` | `Alibaba` | `Alibaba` (match) |
| `name` | `Alibaba \| qwen/qwen3.7-plus-20260602` | identical |

Corrected `upstream_provider_slug` and `endpoint_tag` to `alibaba/fp8` in
`config/sota_v3_models.json`, and the bound `provider_slug` in
`config/sota_v3_pricing_snapshot.json`, which the route-catalog test requires
to equal the endpoint tag.

**Prices are identical on the corrected route.** Live `prompt` 3.2e-07,
`completion` 1.28e-06, and the 256k long-context override 9.6e-07 / 3.84e-06
all match the recorded snapshot exactly. Regenerating the cost estimator
produces a byte-identical artifact, so the reservation is untouched at
**$89.845094 unrounded / $107.814113 at the 1.2x contingency**.

After the correction, the full preflight passes all ten cells.

## What this does and does not establish

**Does:** authenticated endpoint metadata reports that the ten exact routes are
reachable, resolve to the pinned upstream provider and endpoint name, advertise
the required parameters, and can accommodate the registered 4,096-token cap.
Actual inference behavior remains for the paid smoke to establish.

**Does not:** authorize spend, freeze cohort identity, or resolve
`exact_route_acceptance`. That block still reports `unresolved` with every
entry lacking authenticated verification, a timestamp, an evidence digest, and
privacy acceptance — so the smoke phase remains blocked by 60 issues, exactly
as many as before preflight ran.

## Why the cohort did not change

A dead route would have dropped the family to nine, and cohort size drives the
Holm family size, which drives the allocation, which drives the reservation —
the cascade that moved 15x1 to 16x1 in PR #107. Because the only defect was a
label, **the cohort stays at ten, the 16x1 allocation stands, and no power
re-selection is required.**

This is also the case for having run the free probe before generating the seed
panel: had this been discovered later, the correction would have landed
against a committed panel.
