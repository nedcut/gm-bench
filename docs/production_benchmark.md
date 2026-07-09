# Production Benchmark Standard

GM-Bench has two result tiers:

- `public-leaderboard`: a structurally valid public leaderboard result.
- `sota-v1`: the stricter standard for claims about frontier model GM ability.

The public leaderboard can show development and diagnostic rows, including local
models that are below the scripted baselines. A `sota-v1` result is the minimum
bar for a result that should be compared as a serious model benchmark.

Committed official artifacts belong in `results/leaderboard/` and must pass the
`public-leaderboard` validator in CI. Ineligible runs that are retained for
transparency belong in `results/diagnostics/`; the site builder includes those
rows explicitly while preserving the official-artifact gate.

## SOTA-v1 Requirements

A `sota-v1` result must be produced by:

```bash
python -m gm_bench model \
  --provider <provider> \
  --model <model> \
  --preset leaderboard \
  --repeats 3 \
  --json > results/leaderboard/<provider>-<model>.json
```

For a held-out SOTA run, set a private leaderboard seed panel before running
and validating. Keep the raw JSON local; it contains the exact seed ids needed
for local reproduction. Publish only a redacted artifact, which preserves the
seed-panel SHA-256 commitment and strips per-seed traces. Treat that hash as an
integrity check for operators who already know the panel — small integer seed
lists are brute-forceable, so the hash is not a secrecy mechanism:

```bash
export GM_BENCH_PRIVATE_SEEDS="101,102,110-115"
python -m gm_bench model \
  --provider <provider> \
  --model <model> \
  --preset leaderboard \
  --repeats 3 \
  --json > /tmp/gm-bench-<provider>-<model>-private.raw.json
python -m gm_bench redact-result \
  /tmp/gm-bench-<provider>-<model>-private.raw.json \
  --output results/leaderboard/<provider>-<model>-private.redacted.json \
  --policy sota-v1
```

It must also satisfy the machine validator:

```bash
python -m gm_bench validate-result \
  results/leaderboard/<provider>-<model>.json \
  --policy sota-v1
```

Before publishing SOTA-v1 claims from a new source contract, run the benchmark
validity canaries:

```bash
python -m gm_bench validate-contract
```

Reproduce the active score scale, marginal-value table, reference scores, and
strategic ablations with:

```bash
python -m gm_bench calibrate-score --json
```

This checks that `strategic` and `pick-trader` remain clean, competent
references above `shrewd`, that accepted actions cover scouting, incoming
offers, pick trading, and memo persistence across the panel, and that known
degenerate strategies remain comfortably below `value` on both final score and
strategy score:

- `exploit`: replays known trade-pump and free-agent-hoarding attacks.
- `pick-hoard`: tries to convert productive players into future picks.
- `cap-hoard`: dumps productive players to maximize cap room.
- `accept-everything`: blindly accepts every opponent-initiated offer.

The validator enforces:

- `run_info.command=model`, `preset=leaderboard`, and `profile=compact`.
- A current `run_info.benchmark_contract` block, including the source-derived
  contract fingerprint for simulator, scoring, preset, and action schemas.
- An official seed panel: either the public held-back `leaderboard` panel, or
  a private panel proven by the local `GM_BENCH_PRIVATE_SEEDS` value.
- Five seasons per seed.
- The full v1 baseline panel: `random`, `conservative`, `win-now`, `rebuild`,
  `value`, `shrewd`, `strategic`, and `pick-trader`.
- At least 3 candidate repeats per seed, so model sampling noise is observable.
- Full usage telemetry for every decision point.
- Candidate decision failure rate at or below 2%.
- Complete paired analysis, including sign-flip p-value and strongest-baseline
  comparison.
- Scaffold provenance: new rows record `run_info.scaffold_fingerprint`, a
  per-provider hash of the prompt scaffold (shared prompt builder plus the
  provider's adapter script and spec). A recorded fingerprint that does not
  match the current source is an error; rows predating scaffold provenance
  get a warning instead, so the prompt layer is visibly unattested rather
  than silently trusted. Scaffold changes do not open a new contract lane —
  they mark which rows are prompt-comparable within it.

Warnings are still attached to otherwise valid results when the model has
illegal actions, any adapter fallback/error decisions, insignificant lift, or a
failure to beat the strongest scripted baseline. Those warnings are not hidden:
the public leaderboard builder always revalidates eligibility (it never trusts
embedded `validation_reports`), carries `sota_v1_eligible` and
`sota_v1_issues` into `web/src/data/leaderboard.json`, and the UI surfaces
warning counts on otherwise eligible rows. Contract version/fingerprint and
seed-panel name/hash are included when present.

`redact-result` only writes an output file when the selected policy passes.
Invalid private runs stay local; do not publish them.

## Contract freeze

The `sota-v1` leaderboard contract is **frozen at fingerprint
`cf2607e59dba0c7f`** (protocol `gm-bench-v2` with midseason, the full v1
baseline panel, public seeds 11–18) as of 2026-07-09. Every contract change so
far has invalidated all prior model rows; a leaderboard only accumulates
comparable results while the contract holds still.

Under the freeze:

- New model rows run against the frozen contract; `validate-result` already
  rejects rows whose fingerprint does not match the current source.
- Simulator, scoring, preset, or schema changes that alter the fingerprint do
  not amend `sota-v1` — they start a new claim lane (`sota-v2`) with its own
  re-cached baseline panel and reference means. Existing `sota-v1` rows stay
  published and comparable with each other under their own contract.
- Changes that do not alter simulation or scoring behavior (CLI, docs,
  adapters, site) are free. A behavior-changing bug fix is a deliberate
  lane-versioning decision, not routine maintenance.

## Interpretation

Passing `sota-v1` does not mean the model is good. It means the result was run
on the official contract and is reliable enough to discuss. A model-backed
result still needs to be interpreted next to:

- mean score and paired lift against the baseline panel,
- lift against `pick-trader`, the strongest v1 scripted baseline,
- seed win rate,
- confidence interval and sign-flip p-value,
- illegal-action count,
- fallback/error decision rate,
- token usage, dollar cost, and latency.

Results that fail `sota-v1` may still be useful diagnostics, but they should not
be used as evidence about state-of-the-art GM skill.
