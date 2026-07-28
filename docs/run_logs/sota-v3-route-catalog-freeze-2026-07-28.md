# SOTA-v3 public route-catalog freeze — 2026-07-28

## Outcome

An eight-model pre-data cohort and its exact OpenRouter catalog routes are
recorded in `config/sota_v3_models.json`. Route-level prices are recorded in
`config/sota_v3_pricing_snapshot.json`.

This is a **public metadata freeze, not an execution-readiness claim**.
`selection_status` remains `provisional-blocked`, and route-preflight, spend,
smoke, panel, and publication authorization remain false. No chat or completion
endpoint was called and spend was $0.

## Method and sources

By `2026-07-28T04:15:49Z`, the following unauthenticated, read-only HTTP GET
sources were inspected:

- `https://openrouter.ai/api/v1/models`
- `https://openrouter.ai/api/v1/models/{model_id}/endpoints` for each selected
  model
- the same endpoint source for `openai/gpt-5.6-luna`, solely to recheck the
  historical replacement decision

The responses were held only as local temporary review inputs. The checked-in
configs preserve the fields needed for reproducibility: model and canonical
slug, exact upstream tag and dated endpoint name, route status, recent uptime,
supported parameters, structured reasoning metadata, and route-level prices.

## Frozen public-catalog cohort

| Cohort | Model | Exact upstream route | Public status | Reasoning policy | Prompt / completion USD per token |
| --- | --- | --- | ---: | --- | ---: |
| Frontier proprietary | GPT-5.6 Luna Pro | `openai` / `OpenAI \| openai/gpt-5.6-luna-pro-20260709` | 0 | Disable where structured catalog says optional; strict smoke must resolve contradictory Pro description | `0.0000005` / `0.000003` |
| Frontier proprietary | Claude Sonnet 5 | `amazon-bedrock/global` / `Amazon Bedrock \| anthropic/claude-sonnet-5-20260630` | 0 | Disabled where optional | `0.000002` / `0.00001` |
| Frontier proprietary | Gemini 3.6 Flash | `google-ai-studio` / `Google AI Studio \| google/gemini-3.6-flash-20260721` | 0 | Mandatory `minimal` | `0.0000015` / `0.0000075` |
| Frontier proprietary | Grok 4.5 | `xai/zdr` / `xAI \| x-ai/grok-4.5-20260708` | 0 | Mandatory `low` | `0.000002` / `0.000006` |
| Open-weight | GLM 5.2 | `novita/fp8` / `Novita \| z-ai/glm-5.2-20260616` | 0 | Disabled where optional | `0.0000007266` / `0.0000022836` |
| Open-weight | MiniMax M3 | `minimax/fp8` / `Minimax \| minimax/minimax-m3-20260531` | 0 | Disabled where optional | `0.0000003` / `0.0000012` |
| Open-weight | Qwen 3.7 Plus | `alibaba` / `Alibaba \| qwen/qwen3.7-plus-20260602` | 0 | Disabled where optional | `0.00000032` / `0.00000128` |
| Open-weight | Mistral Medium 3.5 | `mistral` / `Mistral \| mistralai/mistral-medium-3.5-20260430` | 0 | Disabled where optional | `0.0000015` / `0.0000075` |

All eight selected endpoints publicly listed `reasoning`, `max_tokens`, and
`response_format`, which are the runner's route-level required parameters.
That listing does not prove authenticated acceptance or correct behavior.
For routes whose structured catalog marks reasoning optional, the registry uses
the runner's machine enum `reasoning_policy: "disabled"`; the optionality
evidence remains separately recorded under each model's `catalog_reasoning`.

## Cohort and route decisions

- **Luna Pro instead of Luna:** the prior audit made this substitution while the
  non-Pro Luna route was unhealthy. On this snapshot, the public non-Pro OpenAI
  route had recovered to status `0` with 30-minute uptime about `99.303%`.
  Because no v3 model data exists and the user requested preserving the
  substitution, the cohort stays on Luna Pro. This is not described as a
  current Luna outage.
- **Gemini 3.6 Flash instead of 3.5 Flash:** 3.6 is the current preferred fast
  Google anchor and exposes the same required structured-output surface. Its
  catalog reasoning policy is mandatory with `minimal` as the lowest listed
  effort.
- **Mistral Medium 3.5 instead of Muse Spark 1.1:** this keeps the eight-model
  family balanced at four proprietary and four open-weight systems. Mistral is
  the European open-weight anchor and preserves a route/model identity already
  used in the earlier panel; Muse would duplicate the proprietary cohort and
  weaken the open-weight comparison.
- **Sonnet on Bedrock global rather than recovered direct Anthropic:** the global
  Bedrock route preserves the exact upstream identity already selected and
  smoked in the earlier panel. Direct Anthropic now also reports status `0`,
  but momentary recovery is not enough reason to change route identity before
  authenticated and privacy review.
- **GLM on Novita FP8 rather than recovered Z.AI FP8:** Novita preserves the
  amended route identity that completed the earlier strict smoke after the Z.AI
  route was unhealthy. Both now report status `0`; retaining Novita avoids a
  health-only route reversal and preserves known quantization and provider
  identity.
- **Grok on `xai/zdr` rather than `xai`:** both tags report the same dated
  endpoint name, prices, parameters, and status `0`. Selecting the public
  ZDR-tagged route is directionally aligned with the privacy goal. The tag alone
  is not provider-policy evidence, so privacy remains blocked rather than
  treated as solved.

## Public metadata limitations

The endpoint responses did not expose usable exact-route commitments for prompt
retention, training use, deletion, geographic handling, or zero-data-retention.
`OPENROUTER_DATA_COLLECTION=deny` is a requested router constraint, not evidence
of an upstream policy. The `xai/zdr` tag is likewise not accepted as proof
without authenticated routing evidence and provider-policy review.

The Luna Pro public description says the variant is served with
`reasoning.mode=pro`; the structured catalog simultaneously marks reasoning
optional and lists `none`. The checked-in execution intent follows the
structured catalog and disables optional reasoning, but no Luna Pro evidence
may be accepted until a strict smoke resolves the contradiction.

## Remaining authenticated zero-completion-call route-preflight blockers

1. `config/sota_v3_lane.json` keeps `route_preflight_authorized: false`.
2. The registry deliberately remains `selection_status:
   provisional-blocked`; the runner accepts only `route-preflight-ready` or
   `frozen` for that phase.
3. The current runner's route-preflight GET is unauthenticated. It can confirm
   public catalog identity and health but cannot prove that the configured
   OpenRouter account can use the exact route. An authenticated, non-generation
   account/route capability check must be defined before changing either gate.
4. Exact-route privacy and retention requirements, including what evidence is
   sufficient for ZDR, remain unresolved.
5. The Luna Pro reasoning contradiction requires a separately authorized strict
   smoke; it cannot be resolved from public metadata.

No authorization flag should be changed merely because the public catalog
snapshot is complete.
