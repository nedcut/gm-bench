# Submitting Third-Party Results

This describes how an outside party produces a leaderboard row and what has to be
true for it to pass the machine validator. Every requirement below is enforced by
`gm_bench/official.py` (`validate_leaderboard_payload`); nothing here is aspirational
unless it is called out as a convention. Read
[production_benchmark.md](production_benchmark.md) first for the two result tiers
(`public-leaderboard`, strict versioned policies) and the contract freeze.

> **Current status:** the public site is the frozen `sota-v2` phase-one study.
> Development HEAD emits `sota-v3`, but a v3 publication registry and lane have
> not been pre-registered. New strict submissions should therefore remain local
> or diagnostic until that protocol is frozen; do not add a v3 row to
> `results/leaderboard/` and expect the v2 site to publish it.

## Produce the row

Run the official configuration: `model` command, `leaderboard` preset, `compact`
profile (the preset pins it), 3 repeats.

```bash
python -m gm_bench model \
  --provider <provider> \
  --model <model> \
  --preset leaderboard \
  --repeats 3 \
  --json > results/leaderboard/<provider>-<model>.json
```

The `leaderboard` preset is 8 public seeds (11–18) × 5 seasons against the full
baseline panel. `--repeats 3` runs the candidate three times per seed so sampling
noise is observable; the baselines are deterministic and run once. This produces a
public-panel row.

That command also selects strict failure handling, because `--preset
leaderboard` is a publication lane: a decision the adapter could not read back
from the model becomes a bare `noop` rather than a host-supplied draft pick and
lineup. Do not set `GM_AGENT_STRICT` yourself — the harness resolves it and
records the result in `run_info.strict_fallback`. `--no-strict-fallback` is a
legitimate diagnostic choice, but the resulting row is not `sota-v3` eligible.

For a contamination-resistant private-panel row, set a held-out panel first, keep
the raw JSON local, and publish only the redacted artifact:

```bash
export GM_BENCH_PRIVATE_SEEDS="101,102,110-115"   # >= 8 seeds for the strict policy
python -m gm_bench model --provider <p> --model <m> \
  --preset leaderboard --repeats 3 --json > /tmp/<p>-<m>-private.raw.json
python -m gm_bench redact-result /tmp/<p>-<m>-private.raw.json \
  --output /tmp/<p>-<m>-private.redacted.json --policy sota-v3
```

`redact-result` writes the output file **only if the selected policy passes**; an
invalid private run stays on your disk. The redacted artifact keeps aggregate
scores, usage, provenance, and the seed-panel SHA-256, and strips the seed list,
per-episode detail, and `paired.per_seed` rows.

## Validate before you submit

```bash
python3 -m gm_bench validate-result /tmp/<name>.raw.json --policy sota-v3
python3 -m gm_bench compact-result /tmp/<name>.raw.json \
  --output /tmp/<name>.compact.json --policy sota-v3
```

Use `--policy public-leaderboard` for a development/diagnostic row. Exit code is
non-zero on any error. The site builder ignores whatever `validation_reports` an
artifact carries and re-runs this validation itself, so a hand-edited report will
not buy eligibility.

## What the validator checks

Both policies require these; the values are read straight from the payload:

- `run_info` present, with `command=model`, `preset=leaderboard`, `profile=compact`.
- `run_info.gm_bench_version` resolved to a real package version (not `…+unknown`).
- `run_info.provider` and `run_info.model` non-empty.
- `seasons == 5`.
- Full per-decision usage: `candidate.summary.usage.decisions_with_usage` must equal
  the candidate decision count, and `usage.cost_usd` must be present (use `null`
  only when pricing is genuinely unknown — omitting the key fails).
- A `normalized` block with `candidate_mean_score`, `baseline_panel_mean_score`,
  `score_lift`.
- A `paired` block with `num_seeds` equal to the panel seed count,
  `sign_flip_p_value`, and `best_baseline`.
- Every candidate episode present exactly once per seed/repeat, each with
  `seasons == 5`; each baseline episode present once per seed.

`public-leaderboard` is lenient where the current `sota-v3` policy is strict:

| Check | `public-leaderboard` | `sota-v3` |
|---|---|---|
| Candidate repeats | ≥ 1 | ≥ 3 |
| Seed count | ≥ 1 | ≥ 8 (full leaderboard panel) |
| Decision failure rate | ≤ 20% | ≤ 2% |
| `benchmark_contract` block | warning if missing | **required**, must match current source exactly |
| Seed-panel provenance | warning if missing | **required** |
| Baseline panel | any known subset, no dupes | **exact** full panel: `random`, `conservative`, `win-now`, `rebuild`, `value`, `shrewd`, `strategic`, `pick-trader` |
| Scaffold provenance | warning if missing | **required**, and must match the current source |
| Strict failure handling | not checked | **required**: `run_info.strict_fallback` true and `provider_options.GM_AGENT_STRICT == "1"`, agreeing |
| Per-episode `score_components` | not checked | **required** on every episode row, finite, contributions summing to `strategy_score` |

For `sota-v3`, `run_info.benchmark_contract` must match `expected_contract()`
field for field. The historical `sota-v2` policy instead matches the literal
released contract, including fingerprint `558e8f35ea1d66b9`. A row built against
a different simulator/scoring/schema source is rejected, not merely flagged.

**What these checks do and do not prove.** Every table row above establishes
*internal consistency*: that the artifact agrees with itself and with the
declared contract. None of them establish that the numbers came from a real
run. A tampered artifact whose raw metrics, `*_contribution` terms,
`strategy_score` and `final_score` were all scaled together satisfies the
`score_components` check, because recomputing a score from its own components
cannot detect a consistent lie. The same is true of `strict_fallback`: the
validator confirms the two provenance fields agree, not that the adapter
actually noop-ed on failure. Binding an artifact to real evidence is the job of
`publication.raw_artifact_sha256` and the release manifest checksums — read
`validate-result` as "this row is well-formed and self-consistent under
`sota-v3`", never as "this row is authentic".

Seed-panel provenance (`run_info.seed_panel`) must name one of two identities;
`custom` panels are rejected outright:

- `public-leaderboard`: seeds must be exactly 11–18, and `sha256`/`count` must match
  `seed_panel_hash` of that list.
- `private-env`: validated from the local `GM_BENCH_PRIVATE_SEEDS` (raw artifact) or
  from the declared `count` (≥ 8) and 64-char hex `sha256` (redacted artifact).

### Warnings do not block, but travel with the row

These are recorded as warnings, keep the row eligible, and surface on the site
(`sota_v2_issues`): illegal actions present, failed-query rate above 0.25
(misfired scout/inspect lookups; rates above 1.0 are a hard strict-policy error,
not a warning), any adapter fallback/error decisions, lift not significant at
95%, candidate not beating the strongest baseline, or the strongest baseline
not being `pick-trader`.

## What to put in the PR

- **Public-panel run:** the `compact-result` output in
  `results/leaderboard/<name>.json`; retain the full raw result outside git.
  Committed artifacts in that directory must pass the `public-leaderboard` validator
  in CI.
- **Private-panel run:** the **redacted** artifact only
  (`results/leaderboard/<name>-private.redacted.json`). Never commit the raw JSON or
  the seed list — that is the held-out panel.
- **Ineligible-but-interesting run:** put it in `results/diagnostics/` instead. The
  site shows diagnostics for transparency, but they sit outside the official-artifact
  gate on purpose.

### Trace publication (convention, not validated)

For public-panel rows, publish the full per-decision traces alongside the result so
the run can be audited and reproduced — the public panel is a reproducibility
surface and there is no reason to withhold traces. The validator does **not** check
for traces; this is a submission expectation, not a machine gate. For private-panel
rows, traces are withheld until the panel rotates out and is revealed (see
"Seed-panel rotation and contamination" in production_benchmark.md), because full
traces would leak the held-out seeds.

## Eligible vs diagnostic

The phase-one site builder (`web/scripts/build_leaderboard.py`) re-runs the frozen `sota-v2`
validator on every artifact under `results/leaderboard/` and sets
`sota_v2_eligible` from `report.ok`, carrying all errors and warnings into
`sota_v2_issues`. A row is:

- **sota-v2 eligible** when the `sota-v2` validator returns no errors. Warnings may
  still be attached and are shown.
- **diagnostic** when it fails `sota-v2` (too few repeats, wrong contract, partial
  baseline panel, failure rate over 2%, missing provenance, …) or when it is placed
  in `results/diagnostics/`. Diagnostics are useful signal but are not evidence about
  state-of-the-art GM skill.

Passing `sota-v2` means the row was produced on the frozen official contract and is
reliable enough to compare — not that the model is good. Interpret it next to the
paired lift, `pick-trader` lift, seed win rate, sign-flip p-value, illegal-action
count, failed-query count, fallback rate, lane (API vs. CLI harness), tokens/decision,
and cost, as described in production_benchmark.md.

The raw artifact is the audit source and should be retained outside git (for
example as a release asset). `compact-result` removes observations,
transactions, season traces, and per-decision telemetry while preserving
summary statistics, per-seed/repeat scores, aggregate usage, provenance, and a
SHA-256 of the canonical raw payload. CI rejects current leaderboard artifacts
that are not compact or exceed 1 MB.
