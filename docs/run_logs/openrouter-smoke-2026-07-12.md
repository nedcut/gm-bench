# OpenRouter smoke run — 2026-07-12

## Outcome

The first direct OpenRouter smoke run reached the provider, but OpenRouter
rejected the requests with HTTP 402 (`Payment Required`). GM-Bench aborted after
two consecutive model failures, as designed. No benchmark result was produced
and no leaderboard claim can be made from this attempt.

This is an account-credit blocker, not evidence of an adapter, prompt, or model
failure.

## Run record

- Started: `2026-07-13T01:29:15Z` (`2026-07-12` America/New_York)
- Base commit: `e70c1838f440b0506188d9a878403d7a7839c8ef`
- Provider: `openrouter`
- Transport: `gateway-api`
- Requested model: `openai/gpt-5.4-mini`
- Preset: `smoke`
- Planned panel: seed `1`, one season, one repeat, four decisions
- Workers: `1`
- Completed decisions: `0`
- Attempted decisions before fail-fast: `2`
- Terminal error: `api_error: HTTP Error 402: Payment Required`
- Local checkpoint: `data/model_checkpoints/openrouter-openai-gpt-5.4-mini.json`
  (gitignored; contains no completed episodes)

Command:

```bash
GM_BENCH_WORKERS=1 python3 -m gm_bench model \
  --provider openrouter \
  --config examples/openrouter.smoke.json
```

Resolved routing policy:

```text
OPENROUTER_PROVIDER_SORT=price
OPENROUTER_ALLOW_FALLBACKS=false
OPENROUTER_REQUIRE_PARAMETERS=false
OPENROUTER_DATA_COLLECTION=deny
OPENROUTER_JSON_MODE=false
```

Benchmark provenance:

```text
benchmark_version=sota-v1
simulator_version=sim-v1
scoring_version=score-v1
contract_fingerprint=cf2607e59dba0c7f
scaffold_fingerprint=fe492966ee4a2dc4
```

## Next action

Add OpenRouter credits, then rerun the same command. The existing checkpoint is
safe to resume, but because it contains zero completed decisions, restarting the
smoke from scratch is equivalent and gives the cleanest run record. Do not begin
a larger panel until the smoke completes all four decisions with zero failures
and reports token usage, cost, returned model, and upstream-provider metadata.
