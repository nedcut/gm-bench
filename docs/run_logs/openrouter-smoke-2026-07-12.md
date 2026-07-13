# OpenRouter smoke run — 2026-07-12

## Outcomes

Three OpenRouter smoke attempts were made:

1. The initial GPT-5.4 Mini attempt reached OpenRouter, but OpenRouter rejected
   two requests with HTTP 402 (`Payment Required`). GM-Bench aborted as designed.
2. After credits were added, an intended HY3 Free invocation unexpectedly ran
   GPT-5.4 Mini because the checked-in config's `model` value won over the
   explicit `--model` flag. All four GPT decisions completed successfully and
   cost `$0.024776`.
3. HY3 Free was then invoked without a config file. Three decisions completed
   successfully through Novita at zero cost; the fourth decision timed out at
   GM-Bench's 120-second external-agent limit.

The paid GPT run proves that the OpenRouter transport and account are ready.
The HY3 run proves the free route, response parsing, and telemetry work, but its
25% decision failure rate is not a clean model smoke. None of these one-seed,
one-repeat diagnostics is eligible for a leaderboard claim.

## Initial credit failure

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

Credits were subsequently added. The local aborted checkpoint contains zero
completed decisions and no longer needs to be resumed.

## Config precedence discovery and paid transport smoke

The following command was intended to override the config model with HY3 Free:

```bash
GM_BENCH_WORKERS=1 python3 -m gm_bench model \
  --provider openrouter \
  --model 'tencent/hy3:free' \
  --config examples/openrouter.smoke.json
```

Instead, the resolved run used `openai/gpt-5.4-mini`. This demonstrates that the
config's `model` currently takes precedence over an explicit `--model` value.
The config's `no_log: true` also did not prevent the CLI from logging this run to
the default SQLite database. Future multi-model commands must avoid the
model-specific config until precedence semantics are fixed or documented.

Paid-run summary:

- Timestamp: `2026-07-13T01:35:29+00:00`
- Requested by resolved config: `openai/gpt-5.4-mini`
- Returned model: `openai/gpt-5.4-mini-20260317`
- Upstream provider: `Azure`
- Decisions: `4`; failures: `0`
- Input tokens: `29,338`
- Output tokens: `616`
- Reasoning tokens: `0`
- API latency: `7,480.0 ms`
- Reported cost: `$0.024776`
- Candidate score: `101.302` (`131.302` strategy score minus `30.0` protocol
  penalty from 12 illegal actions)
- Logged run ID: `dea2061f-59d4-49f1-8850-4d198033325f`

## HY3 Free smoke

Corrected command:

```bash
GM_BENCH_WORKERS=1 python3 -m gm_bench model \
  --provider openrouter \
  --model 'tencent/hy3:free' \
  --preset smoke \
  --no-log \
  --json
```

Run summary:

- Timestamp: `2026-07-13T01:40:32+00:00`
- Requested model: `tencent/hy3:free`
- Returned model: `tencent/hy3-20260706:free`
- Upstream provider: `Novita`
- Decisions: `4`; failures: `1` (draft timed out after `120.0s`)
- Decision failure rate: `0.25`
- Successful API calls with usage: `3`
- Input tokens: `22,960`
- Output tokens: `10,678`
- Reasoning tokens: `10,212`
- API latency for completed calls: `168,462.3 ms`
- Total harness latency: `288,813.2 ms`
- Reported cost: `$0.00`
- Candidate score: `176.11`, with zero protocol penalty; this diagnostic score
  is not comparable or publishable because one decision failed and the run has
  only one seed and one repeat

HY3's three completed decisions confirm end-to-end OpenRouter functionality,
including generation IDs, token usage, zero-cost reporting, returned-model
identity, and upstream-provider identity. Its long reasoning outputs and timeout
make it a poor readiness gate for larger panels under the current timeout.

The next meaningful step is a four-decision `openai/gpt-5.6-luna` smoke, using
explicit flags without `examples/openrouter.smoke.json`. Do not begin a larger
Luna panel until that smoke completes all four decisions with zero failures.
