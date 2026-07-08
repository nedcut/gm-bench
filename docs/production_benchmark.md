# Production Benchmark Standard

GM-Bench has two result tiers:

- `public-leaderboard`: a structurally valid public leaderboard result.
- `sota-v1`: the stricter standard for claims about frontier model GM ability.

The public leaderboard can show development and diagnostic rows, including local
models that are below the scripted baselines. A `sota-v1` result is the minimum
bar for a result that should be compared as a serious model benchmark.

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
and validating. The exact seed list stays local, while the result records a
SHA-256 seed-panel commitment:

```bash
export GM_BENCH_PRIVATE_SEEDS="101,102,110-115"
python -m gm_bench model \
  --provider <provider> \
  --model <model> \
  --preset leaderboard \
  --repeats 3 \
  --json > results/leaderboard/<provider>-<model>-private.json
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

This checks that the honest `shrewd` reference still beats `value`, and that
known degenerate strategies remain comfortably below `value` on both final
score and strategy score:

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
  `value`, and `shrewd`.
- At least 3 candidate repeats per seed, so model sampling noise is observable.
- Full usage telemetry for every decision point.
- Candidate decision failure rate at or below 2%.
- Complete paired analysis, including sign-flip p-value and strongest-baseline
  comparison.

Warnings are still attached to otherwise valid results when the model has
illegal actions, any adapter fallback/error decisions, insignificant lift, or a
failure to beat the strongest scripted baseline. Those warnings are not hidden:
the public leaderboard builder carries `sota_v1_eligible` and
`sota_v1_issues` into `web/src/data/leaderboard.json`, along with the
benchmark contract version/fingerprint and seed-panel name/hash when present.

## Interpretation

Passing `sota-v1` does not mean the model is good. It means the result was run
on the official contract and is reliable enough to discuss. A model-backed
result still needs to be interpreted next to:

- mean score and paired lift against the baseline panel,
- lift against `shrewd`, the strongest v1 scripted baseline,
- seed win rate,
- confidence interval and sign-flip p-value,
- illegal-action count,
- fallback/error decision rate,
- token usage, dollar cost, and latency.

Results that fail `sota-v1` may still be useful diagnostics, but they should not
be used as evidence about state-of-the-art GM skill.
