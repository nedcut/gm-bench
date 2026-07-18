# sota-v2 model-panel revision — 2026-07-16

This is a pre-full-panel protocol amendment. No full-panel model score existed
when the user replaced the stale ten-model registry with the following current
frontier panel.

## Registered panel

| Cohort | Model | OpenRouter model ID | Exact route | Reasoning |
| --- | --- | --- | --- | --- |
| Big American lab proprietary | GPT-5.6 Luna | `openai/gpt-5.6-luna` | `openai` / OpenAI dated endpoint | disabled |
| Big American lab proprietary | Claude Sonnet 5 | `anthropic/claude-sonnet-5` | `amazon-bedrock/global` / Bedrock global | disabled |
| Big American lab proprietary | Gemini 3.5 Flash | `google/gemini-3.5-flash` | `google-ai-studio` | mandatory `minimal` |
| Big American lab proprietary | Grok 4.5 | `x-ai/grok-4.5` | `xai` | mandatory `low` |
| Big American lab proprietary | Muse Spark 1.1 | `meta/muse-spark-1.1` | `meta` | mandatory `minimal` |
| Open-weight | GLM 5.2 | `z-ai/glm-5.2` | `z-ai/fp8` | disabled |
| Open-weight | Kimi K3 | `moonshotai/kimi-k3` | `moonshotai/int4` | mandatory `max` (only exposed effort) |
| Open-weight | Nemotron 3 Ultra | `nvidia/nemotron-3-ultra-550b-a55b` | `together` | disabled |
| Open-weight | MiniMax M3 | `minimax/minimax-m3` | `minimax/fp8` | disabled |
| Open-weight | Qwen 3.7 Plus | `qwen/qwen3.7-plus` | `alibaba` | disabled |
| Open-weight | DeepSeek V4 Pro | `deepseek/deepseek-v4-pro` | `deepseek` | disabled |
| Open-weight | Mistral Medium 3.5 | `mistralai/mistral-medium-3-5` | `mistral` | disabled |

Terra, Sol, Claude Opus 4.8, and Fable 5 are recorded as future candidates,
not aliases or fallbacks for this panel.

## Route policy

- Pin the exact provider slug, endpoint tag, and dated endpoint name.
- Disable provider fallback and require every requested parameter.
- Deny data-collection routes and request JSON mode.
- Prefer a healthy first-party route. Claude is the declared exception because
  the direct Anthropic endpoint was unhealthy; the healthy global Bedrock tag
  is pinned instead.
- Nemotron uses Together rather than the cheaper DeepInfra FP4 endpoint to
  avoid the prior Nano/DeepInfra failure mode and retain the 100% five-minute
  uptime route observed during selection.
- Reasoning is disabled where optional. Mandatory-reasoning models use the
  lowest effort exposed by OpenRouter; Kimi K3 exposes only `max`.

## Compute and evidence policy

The common provisional cap is 4,096 total output tokens. If any smoke reaches
3,072 tokens or shows truncation, raise the entire panel to 8,192 before any
full-panel score is visible. Reasoning tokens, output tokens, latency, and cost
remain reported secondary efficiency metrics.

The earlier 1,024-token manifest was reset. Every route requires a new serial
smoke and exact-route preflight before the registry can become frozen.

At 2026-07-16T19:13Z, the publication runner's no-spend preflight passed all
twelve exact endpoint tags, required-parameter checks, 4,096-token limits, and
local OpenRouter credential checks. This proves route availability only; it is
not a substitute for the paid benchmark-level smokes.
