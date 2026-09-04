# Direct API and OpenRouter lanes

GM-Bench supports first-class API adapters for OpenAI, Anthropic, Google
Gemini, and OpenRouter. These adapters send the benchmark scaffold and compact
observation directly to the selected model. Coding-agent products (`claude`,
`codex`, `cursor`, and `opencode`) remain separate harness-backed conditions.

## Credentials

Set credentials in the shell or a secret manager. Never commit keys to a config
file or result artifact.

```bash
export OPENAI_API_KEY=...
export ANTHROPIC_API_KEY=...
export GEMINI_API_KEY=...        # GOOGLE_API_KEY is also accepted
export OPENROUTER_API_KEY=...
```

The CLI automatically loads `.env.local` and then `.env` from the current
working directory. Existing shell variables take precedence, and `.env.local`
takes precedence over `.env`. Both filenames are ignored by the repository.
For example:

```dotenv
# .env.local
OPENROUTER_API_KEY=...
```

List the installed provider lanes and defaults:

```bash
python3 -m gm_bench providers
```

## Smoke before spending

Every provider should pass the four-decision smoke before a larger panel. Model
adapters should be run serially with `GM_BENCH_WORKERS=1`.

```bash
GM_BENCH_WORKERS=1 python3 -m gm_bench model \
  --provider openai --model gpt-5.4-mini \
  --preset smoke --verbose --json --no-log

GM_BENCH_WORKERS=1 python3 -m gm_bench model \
  --provider anthropic --model claude-sonnet-4-6 \
  --preset smoke --verbose --json --no-log

GM_BENCH_WORKERS=1 python3 -m gm_bench model \
  --provider gemini --model gemini-3.5-flash \
  --preset smoke --verbose --json --no-log

GM_BENCH_WORKERS=1 python3 -m gm_bench model \
  --provider openrouter --model openai/gpt-5.4-mini \
  --preset smoke --verbose --json --no-log
```

The checked-in canonical Luna configs pin the complete execution condition:

```bash
python3 -m gm_bench model --config examples/openrouter.luna.smoke.json
python3 -m gm_bench model --config examples/openrouter.luna.leaderboard.json
```

The smoke exits nonzero on model/adapter failures, missing usage or cost
coverage, or ambiguous OpenRouter routing. Illegal strategic actions and their
protocol penalties remain valid model outcomes and stay in the scored result.
Both configs atomically persist the complete JSON artifact with `output`;
terminal truncation cannot destroy the result. Explicit CLI flags override
config values, and config `env` overrides everything below it. Below that come
the provider pins in `gm_bench/providers.py` — the v6 call conditions: the
4,096-token output ceiling, reasoning disabled where the route allows it,
routing and privacy settings, and no paid retry. Those pins beat inherited
shell values, so a stale `OPENROUTER_MAX_TOKENS` in a terminal cannot quietly
buy a row a larger output budget than the panel allows. Overriding one takes a
config `env` entry, which is recorded in `run_info.provider_options` where a
reader can see the choice. Settings no pin covers still come from the shell.

Failure handling is the one setting the harness refuses to inherit silently, and
the one setting where config-file `env` does *not* win. `GM_AGENT_STRICT` is
resolved per run — an explicit `--strict-fallback` / `--no-strict-fallback` flag
first, then the lane policy (strict for `--preset leaderboard`), then config-file
`env`, then any ambient value, then strict — normalized to `"1"`/`"0"`, and stamped
into both `run_info.strict_fallback` and `run_info.provider_options`. Neither a
stale `GM_AGENT_STRICT=0` in the shell nor a stale entry in a lane config can
downgrade a leaderboard row. The flags are available on `model`, `run`, and
`evaluate`, since all three emit leaderboard-shaped artifacts.

## OpenRouter routing policy

OpenRouter normally load-balances and falls back across upstream providers.
That is useful for applications but can make benchmark rows irreproducible.
GM-Bench therefore defaults to:

- price-sorted routing;
- provider fallbacks disabled;
- providers that may collect data excluded;
- JSON mode disabled unless explicitly requested, so unsupported optional
  parameters do not silently narrow the eligible model catalog.

For a canonical row, pin the upstream and, when relevant, quantization:

```bash
export OPENROUTER_PROVIDER_ONLY=anthropic
export OPENROUTER_QUANTIZATIONS=fp16
export OPENROUTER_ALLOW_FALLBACKS=false
export OPENROUTER_REQUIRE_PARAMETERS=true
export OPENROUTER_JSON_MODE=true
```

For a deliberately price-routed exploratory row, leave
`OPENROUTER_PROVIDER_ONLY` unset and keep `OPENROUTER_PROVIDER_SORT=price`.
Label that result as price-routed rather than canonical.

Available routing controls:

| Environment variable | Default | Meaning |
| --- | --- | --- |
| `OPENROUTER_PROVIDER_ONLY` | unset | Comma-separated upstream allowlist |
| `OPENROUTER_PROVIDER_SORT` | `price` | Provider ordering strategy |
| `OPENROUTER_ALLOW_FALLBACKS` | `false` | Permit fallback upstreams |
| `OPENROUTER_REQUIRE_PARAMETERS` | `false` | Require support for every requested parameter |
| `OPENROUTER_DATA_COLLECTION` | `deny` | Permit endpoints that may retain prompts |
| `OPENROUTER_ZDR` | unset | Require zero-data-retention endpoints |
| `OPENROUTER_QUANTIZATIONS` | unset | Comma-separated allowed quantizations |
| `OPENROUTER_JSON_MODE` | `false` | Request provider-native JSON-object mode |
| `OPENROUTER_MAX_TOKENS` | `2048` | Maximum generated tokens per API call |
| `OPENROUTER_REASONING_ENABLED` | unset | Explicitly enable or disable reasoning without provider-specific effort mapping |
| `OPENROUTER_REASONING_EFFORT` | unset | Requested reasoning effort |
| `OPENROUTER_REASONING_MAX_TOKENS` | unset | Maximum reasoning-token budget |

The resolved values are stamped into `run_info.provider_options`. OpenRouter
responses additionally record the returned model, upstream provider,
generation id, cached/reasoning tokens, and authoritative reported cost.

OpenRouter's `:free` model variants can be used for diagnostics, but availability
and rate limits differ from paid routes. Preserve the full model slug in the
artifact name and do not silently compare free/quantized routes with canonical
full-precision rows.

## Result lanes

Keep transport conditions separate:

- `direct-api`: OpenAI, Anthropic, and Gemini;
- `gateway-api`: OpenRouter, with routing policy recorded;
- `coding-harness`: Claude Code, Codex, Cursor, and opencode;
- `local-api`: Ollama.

`run_info.transport` records this classification. Do not overwrite historical
harness artifacts when adding direct-API results; they answer different product
questions.

## Before a leaderboard run

1. Confirm the exact model id is stable rather than a moving `latest` alias.
2. Run the smoke and inspect failure rate, returned model, token counts, cost,
   and upstream provider.
3. Confirm account spend limits and request/day quotas.
4. Keep `GM_BENCH_WORKERS=1` unless the provider and budget explicitly permit
   concurrency.
5. Validate the resulting JSON with `validate-result` before publishing it.
6. Confirm the artifact records `run_info.strict_fallback: true` and
   `provider_options.GM_AGENT_STRICT: "1"`; a soft-fallback row is not
   `sota-v3` eligible.

Leaderboard OpenRouter runs are rejected before the first paid call unless
exactly one `OPENROUTER_PROVIDER_ONLY` value is set and fallbacks are disabled.
The observed upstream must also match the requested upstream for a clean run.

This setup intentionally does not run any paid model calls or create benchmark
artifacts by itself.
