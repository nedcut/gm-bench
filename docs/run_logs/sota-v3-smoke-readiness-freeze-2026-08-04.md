# SOTA-v3 smoke-readiness freeze — 2026-08-04

## Outcome

The SOTA-v3 lane is frozen and authorized for the **strict smoke phase only**.
No model completion was called while preparing this freeze. Panel execution and
publication remain locked.

## Frozen inputs

- Contract fingerprint: `a523bdfcebe47bbd`.
- Cohort: ten exact OpenRouter routes in `config/sota_v3_models.json`.
- Statistical allocation: 16 private seeds x 1 repeat.
- Output policy: common 4,096-token request cap; 3,072-token pressure trigger;
  one symmetric 8,192-token fallback amendment allowed only if the whole smoke
  family is invalidated and rerun.
- Strict failure handling, one protocol repair, no route fallbacks, JSON mode,
  `data_collection=deny`, and serial `GM_BENCH_WORKERS=1` execution.
- Spend: smoke authorized under the committed `$150.00` operator ceiling;
  panel spend is not authorized.

## Private seed commitment

The owner-authorized generator sampled 16 ordered, unique high-entropy 63-bit
seeds with `uniform-rejection-sampling-secrets-randbelow-63bit-v1`.

- Ordered execution SHA-256:
  `291fa61cc3dfd8b23fdd79cce3c80a0a98f918f6c8757d35c21b4d8131cc6099`
- Salted hiding commitment SHA-256:
  `7f8da7ca4db4a698ea2b0506af8568c89744e18508d8dedbfeb1c87e90a2b5f8`
- Secret values and salt: stored only in macOS Keychain service
  `gm-bench-sota-v3-private-panel`; the temporary plaintext file was securely
  removed after a hash-only escrow verification.

The repository contains no seed or salt values. The launcher
`scripts/run_sota_v3_smoke_from_keychain.py` verifies both committed hashes
before setting `GM_BENCH_PRIVATE_SEEDS` in-process.

## Route and privacy evidence

`results/analysis/sota-v3-route-acceptance-evidence.json` records an
authenticated credits-metadata success, all ten exact endpoint identities,
supported parameters, health telemetry, provider policy links, and the live
OpenRouter ZDR classification. The collector made zero completion calls and
retained no credential, balance, or account-usage value.

The accepted privacy standard is explicit rather than implied:

- GM-Bench sends synthetic game state with no personal or confidential data.
- `OPENROUTER_DATA_COLLECTION=deny` is required, so training-use routes are
  excluded.
- Provider retention terms are accepted for this synthetic benchmark.
- ZDR is preferred but is not required; 5 of the 10 exact routes were present
  in OpenRouter's authenticated ZDR endpoint list at the freeze.

## Null cap metadata

The exact Grok 4.5 xAI ZDR and Mistral Medium 3.5 Mistral routes advertise
`max_tokens` but return `max_completion_tokens: null`. No same-model alternative
route supplies a numeric maximum. They therefore carry the narrow status
`request-cap-pending-strict-smoke`.

This is not a general missing-metadata bypass. The route gate accepts it only
when the endpoint advertises `max_tokens`, the registry declares the exact
exception, and strict-smoke verification remains required. Panel execution
still requires complete per-call finish-reason and usage telemetry, zero
truncations, and a peak below 3,072 tokens for every registered smoke.

## Zero-spend verification

- Authenticated route evidence collection: 10 routes, 5 ZDR, 0 completions.
- Route preflight: 10/10 passed, 0 completions.
- Keychain-backed smoke dry-run: all ten serial commands built successfully;
  no child model process launched.
- The live Luna and GLM prices remained below the conservative undiscounted
  snapshot; decreases were reported and allowed.

Launch only with an explicit ceiling:

```bash
uv run python scripts/run_sota_v3_smoke_from_keychain.py \
  --max-spend-usd 150
```

Before launching, rerun the route preflight because health and pricing evidence
has an hours-long shelf life. After the smokes, record and validate every
artifact, evaluate the whole-cohort cap-pressure rule, refresh the cost/runtime
plan, and request a separate panel authorization.
