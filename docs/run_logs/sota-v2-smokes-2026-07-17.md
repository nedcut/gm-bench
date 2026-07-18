# sota-v2 phase-one smoke ledger — 2026-07-17

The frozen phase-one registry completed its serial 4,096-token OpenRouter smoke
gate under a $2 operator ceiling. Raw artifacts and checkpoints remain outside
Git under `data/publication-runs/smoke-frontier-4096-2026-07-17/`.

## Accepted registry

All ten registered models completed four decisions with zero failed decisions,
zero truncations, complete cost/finish-reason telemetry, and the exact pinned
upstream route. Accepted-route artifact spend was **$0.427613**. Total smoke
campaign spend was **$0.728909** including the excluded $0.301296 Kimi K3
diagnostic described below.

| Model | Cost | Peak output tokens per call |
| --- | ---: | ---: |
| GPT-5.6 Luna | $0.039654 | 141 |
| Claude Sonnet 5 | $0.113126 | 604 |
| Gemini 3.5 Flash | $0.050141 | 107 |
| Grok 4.5 | $0.075268 | 937 |
| Muse Spark 1.1 | $0.026332 | 1,432 |
| GLM 5.2 | $0.047053 | 311 |
| MiniMax M3 | $0.009713 | 260 |
| Qwen 3.7 Plus | $0.011145 | 266 |
| Mistral Medium 3.5 | $0.055181 | 201 |
| Tencent HY3 free | $0.000000 | 150 |

Muse had the largest response at 1,432 tokens, below the predeclared 3,072-token
cap-pressure trigger. Mistral recorded one illegal action; this is measured
model behavior and did not invalidate its clean execution smoke.

## Retained exclusions

- Kimi K3 at mandatory `max` reasoning hit the 4,096-token ceiling in two calls,
  produced two truncated responses and two failed decisions, and cost $0.301296.
  Its raw artifact is retained and the route may not be rerun in phase one.
- Nemotron 3 Ultra's exact free Nvidia route passed catalog/authentication
  preflight, then returned HTTP 404 on both permitted real calls. The checkpoint
  is retained; no paid-route substitution is allowed in phase one.
- DeepSeek V4 Pro's exact first-party route likewise returned HTTP 404 on both
  permitted real calls after passing preflight. The checkpoint is retained and
  no route substitution is allowed in phase one.
