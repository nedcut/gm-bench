# Submitting Third-Party Results

This describes how an outside party produces a leaderboard row and what has to be
true for it to pass the machine validator. Every requirement below is enforced by
`gm_bench/official.py` (`validate_leaderboard_payload`); nothing here is aspirational
unless it is called out as a convention. Read
[production_benchmark.md](production_benchmark.md) first for the two result tiers
(`public-leaderboard`, `sota-v2`) and the contract freeze.

> **Lane note:** the public site still serves the frozen `sota-v2` lane. The
> current simulator produces `sota-v3`; validate new development runs with
> `--policy sota-v3` and keep them in `results/diagnostics/` until a v3
> publication workflow is explicitly opened. The v2 commands below are for
> reproducing or validating artifacts built from the frozen v2 source.

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

For a contamination-resistant private-panel row, set a held-out panel first, keep
the raw JSON local, and publish only the redacted artifact:

```bash
export GM_BENCH_PRIVATE_SEEDS="101,102,110-115"   # >= 8 seeds for sota-v2
python -m gm_bench model --provider <p> --model <m> \
  --preset leaderboard --repeats 3 --json > /tmp/<p>-<m>-private.raw.json
python -m gm_bench redact-result /tmp/<p>-<m>-private.raw.json \
  --output results/leaderboard/<p>-<m>-private.redacted.json --policy sota-v2
```

`redact-result` writes the output file **only if the selected policy passes**; an
invalid private run stays on your disk. The redacted artifact keeps aggregate
scores, usage, provenance, and the seed-panel SHA-256, and strips the seed list,
per-episode detail, and `paired.per_seed` rows.

## Validate before you submit

```bash
python -m gm_bench validate-result results/leaderboard/<name>.json --policy sota-v2
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

`public-leaderboard` is lenient where `sota-v2` is strict:

| Check | `public-leaderboard` | `sota-v2` |
|---|---|---|
| Candidate repeats | ≥ 1 | ≥ 3 |
| Seed count | ≥ 1 | ≥ 8 (full leaderboard panel) |
| Decision failure rate | ≤ 20% | ≤ 2% |
| `benchmark_contract` block | warning if missing | **required**, must match current source exactly |
| Seed-panel provenance | warning if missing | **required** |
| Baseline panel | any known subset, no dupes | **exact** full panel: `random`, `conservative`, `win-now`, `rebuild`, `value`, `shrewd`, `strategic`, `pick-trader` |

For `sota-v2`, `run_info.benchmark_contract` must match `expected_contract()` field
for field — including `contract_fingerprint`, frozen at `a65a4359ca3c6e64`. A row
built against a different simulator/scoring/schema source is rejected, not merely
flagged.

Seed-panel provenance (`run_info.seed_panel`) must name one of two identities;
`custom` panels are rejected outright:

- `public-leaderboard`: seeds must be exactly 11–18, and `sha256`/`count` must match
  `seed_panel_hash` of that list.
- `private-env`: validated from the local `GM_BENCH_PRIVATE_SEEDS` (raw artifact) or
  from the declared `count` (≥ 8) and 64-char hex `sha256` (redacted artifact).

### Warnings do not block, but travel with the row

These are recorded as warnings, keep the row eligible, and surface on the site
(`sota_v2_issues`): illegal actions present, more failed queries than decisions
(misfired scout/inspect lookups), any adapter fallback/error decisions, lift not
significant at 95%, candidate not beating the strongest baseline, or the
strongest baseline not being `pick-trader`.

## What to put in the PR

- **Public-panel run:** the full result JSON in `results/leaderboard/<name>.json`.
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

The site builder (`web/scripts/build_leaderboard.py`) re-runs the `sota-v2`
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
