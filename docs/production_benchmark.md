# Production Benchmark Standard

GM-Bench has two result tiers:

- `public-leaderboard`: a structurally valid public leaderboard result.
- `sota-v2`: the stricter standard for claims about frontier model GM ability.
- `sota-v1`: the frozen historical validator for archived v1 evidence. It does
  not make a v1 row comparable to v2; it only keeps the archived contract
  independently auditable.

The public leaderboard can show development and diagnostic rows, including local
models that are below the scripted baselines. A `sota-v2` result is the minimum
bar for a result that should be compared as a serious model benchmark.

Committed official artifacts belong in `results/leaderboard/` and must pass the
`public-leaderboard` validator in CI. Ineligible runs that are retained for
transparency belong in `results/diagnostics/`. The site builder separates
current v2 rows from explicitly archived pre-v2 evidence while preserving the
official-artifact gate.

## SOTA-v2 Requirements

A `sota-v2` result must be produced by:

```bash
python -m gm_bench model \
  --provider <provider> \
  --model <model> \
  --preset leaderboard \
  --repeats 3 \
  --json > results/leaderboard/<provider>-<model>.json
```

Model / external-process adapters run **serially by default** (one episode at a
time). Parallel fan-out across seeds×repeats will burn provider rate limits and
fill rows with fallback `noop`s, which then fails the sota-v2 failure-rate gate.
Opt into concurrency only when the provider can handle it:
`GM_BENCH_WORKERS=N` or `--workers N`. Scripted in-process baselines still
parallelize.

**Claude is never a parallel provider.** `GM_BENCH_WORKERS` overrides the serial
default — leave it unset or force `GM_BENCH_WORKERS=1` for Claude. On 2026-07-11 a
parallel Sonnet leaderboard panel emptied a Claude Pro 5h usage limit in ~5
minutes wall clock and produced a 0.873 decision failure rate. The
multi-megabyte failed artifact is intentionally not retained. Prefer
`--preset smoke` first; a clean serial sota-v2 panel is
multi-hour quota spend, not a quick retry.

Fresh-spawn serial model panels write an atomic checkpoint after every completed
seed/repeat and stop after two consecutive adapter failures. Resume with
`--resume` for the default checkpoint or add one or more `--resume-from PATH`
result/checkpoint sources. Only zero-failure episodes with matching model,
profile, benchmark-contract, and scaffold provenance are reused.

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
  --policy sota-v2
```

It must also satisfy the machine validator:

```bash
python -m gm_bench validate-result \
  results/leaderboard/<provider>-<model>.json \
  --policy sota-v2
```

Before publishing SOTA-v2 claims from a new source contract, run the benchmark
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
- The full baseline panel: `random`, `conservative`, `win-now`, `rebuild`,
  `value`, `shrewd`, `strategic`, and `pick-trader`.
- At least 3 candidate repeats per seed, so model sampling noise is observable.
- Full usage telemetry for every decision point.
- Candidate decision failure rate at or below 2%.
- Complete paired analysis, including sign-flip p-value and strongest-baseline
  comparison.
- Fresh-spawn condition: `run_info.session` must be absent or false. Session
  rows (`--session`, model keeps its full trajectory in context) are a separate
  labeled condition — publishable, but never comparable with memo-only rows and
  never `sota-v2`.
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
embedded `validation_reports`), carries `sota_v2_eligible` and
`sota_v2_issues` into `web/src/data/leaderboard.json`, and the UI surfaces
warning counts on otherwise eligible rows. Contract version/fingerprint and
seed-panel name/hash are included when present.

### `failed_queries`

`scout`, `inspect_team`, `inspect_player`, and `list_free_agents`
(`gm_bench/protocol.py` `QUERY_ACTION_TYPES`) are declined without a protocol
penalty when the lookup target doesn't resolve — querying is free, so a bad
query shouldn't cost score the way an illegal mutating action does. Under
`sota-v1` that meant failed queries were invisible: they showed up nowhere in
episode results, run summaries, or comparison blocks, no matter how many
there were. `episode.failed_queries`, `summary.failed_queries`, and
`candidate.summary.failed_queries` in comparison output now count them
explicitly, the same way `illegal_actions` is counted.

The validator adds a warning — not an error, since failed queries are
zero-penalty by design — when `candidate_failed_queries` exceeds the
candidate's decision count: that ratio means the model is issuing more than
one failed lookup per decision on average, which usually means it isn't
reading the query error back before retrying (or is stuck resubmitting the
same malformed lookup). A `sota-v2` row can still be eligible with this
warning; it's a diagnostic signal about the model's query behavior, not a
contract violation.

### Reporting requirements

Score alone is not a fair comparison: within this leaderboard, published
score tracks tokens/decision almost monotonically. Any published score claim
— a leaderboard row, a table in a writeup, a comparison in an issue — must be
accompanied by:

- **Lane**: direct API vs. a coding-agent CLI harness (Claude Code, Codex,
  Cursor, opencode). `run_info.transport` records this
  (`direct-api` / `gateway-api` / `coding-harness` / `local-api`); the site
  collapses it to `lane: cli-harness | api`. A CLI harness brings its own tool
  loop, retry behavior, and prompt scaffold on top of the model, so a harness
  row and a direct-API row for the "same" model are not the same measurement.
- **Mean tokens/decision**: `candidate_mean_tokens_per_decision` in
  comparison output, `tokens_per_decision` on the site. This is the strongest
  available proxy for how much compute a row spent per decision.
- **Cost**: `usage.cost_usd` (from `gm_bench/pricing.json` or adapter-reported
  cost), and `cost_per_episode_usd` on the site.
- **Reasoning-effort / output-cap settings**: whatever the provider exposes
  (`OPENROUTER_REASONING_EFFORT`, `OPENROUTER_MAX_TOKENS`, a CLI's own
  `--profile`/effort flag, etc.), recorded in `run_info.provider_options`.

Omitting any of these turns a score into an unfalsifiable claim: a higher
score with no compute context could just mean more tokens were spent, not
that the model is a better GM.

`redact-result` only writes an output file when the selected policy passes.
Invalid private runs stay local; do not publish them.

## Contract freeze

The `sota-v2` leaderboard contract is **frozen at fingerprint
`a65a4359ca3c6e64`** (protocol `gm-bench-v2` with midseason, the full baseline
panel, public seeds 11–18) as of 2026-07-13. It supersedes `sota-v1`, frozen
at fingerprint `cf2607e59dba0c7f`: under `sota-v1` the simulator accepted a
`scout` action's `player_id` only, even though the scaffold prompt also
documented `prospect_id`, and never surfaced failed query actions in any
summary (see
[`results/leaderboard/archive-v1/README.md`](../results/leaderboard/archive-v1/README.md)
for the affected rows and their effect on candidate-vs-baseline comparisons).
Every contract change so far has invalidated all prior model rows; a
leaderboard only accumulates comparable results while the contract holds
still.

Under the freeze:

- New model rows run against the frozen contract; `validate-result` already
  rejects rows whose fingerprint does not match the current source.
- Simulator, scoring, preset, or schema changes that alter the fingerprint do
  not amend `sota-v2` — they start a new claim lane (`sota-v3`) with its own
  re-cached baseline panel and reference means, exactly as `sota-v2` superseded
  `sota-v1`. Existing `sota-v2` rows stay published and comparable with each
  other under their own contract.
- Changes that do not alter simulation or scoring behavior (CLI, docs,
  adapters, site) are free. A behavior-changing bug fix is a deliberate
  lane-versioning decision, not routine maintenance.

## Seed-panel rotation and contamination

The benchmark is deterministic by seed, so a public seed panel is contamination-
exposed: once decision traces circulate, the exact league instances behind seeds
11–18 can be memorized or solved offline. The public panel is therefore a
**reproducibility** surface, not a contamination-resistant one. Contamination-
resistant claims come from a **private** evaluation panel that is held back,
rotated on a schedule, and pre-committed so operators cannot improvise a panel
after seeing scores.

### Rotation cadence

- The private evaluation panel rotates **quarterly**. Each rotation picks a new
  held-out seed list (kept out of the repo, supplied at run time via
  `GM_BENCH_PRIVATE_SEEDS`) with at least as many seeds as the public panel —
  `sota-v2` requires `len(PRESETS["leaderboard"]["seeds"])` seeds (currently 8),
  so a short panel is rejected.
- Before the quarter's runs, publish a **salted commitment** to the new panel
  using `scripts/seed_panel_commitment.py commit`. The salt stays local (the
  `*.seed-salt.json` path is gitignored); only the commitment digest is
  announced. This is a real hiding commitment, unlike the unsalted
  `seed_panel_hash` embedded in artifacts, which is brute-forceable from the
  digest.
- When the panel rotates out, reveal salt + seeds
  (`seed_panel_commitment.py verify`) so the prior quarter's private rows become
  independently reproducible.

### Panel identity vs contract

Rotation changes the **panel**, not the **contract**. The private panel is
supplied at run time and is *not* part of the contract fingerprint, so swapping
it in and out does not touch the frozen `a65a4359ca3c6e64` and does not start a
new claim lane. The validator recognizes the private panel by the `private-env`
name plus a seed-count and SHA-256 that it re-derives from the local
`GM_BENCH_PRIVATE_SEEDS` value (or, for redacted artifacts, the declared
`count` and `sha256`).

There is one sharp edge, enforced by the code and not to be papered over: the
public panel (seeds 11–18) lives in `gm_bench/benchmark_config.py`, which **is**
one of the contract-fingerprint sources (`gm_bench/contract.py`,
`_CONTRACT_SOURCES`). Editing the canonical public panel changes the fingerprint
and therefore ends `sota-v2` and opens `sota-v3` — it is a deliberate lane
version bump, not a free rotation. The validator also hardcodes exactly two
official panel identities: `public-leaderboard` (must equal 11–18) and
`private-env`. `custom` panels are rejected outright.

Consequently, "the previous private panel becomes public when rotated out" is a
**disclosure convention, not a rename inside the validator**. A retired panel is
republished by revealing its seeds/salt/commitment; anyone reproduces it by
exporting those seeds as `GM_BENCH_PRIVATE_SEEDS`, at which point the validator
still labels it `private-env` (its own reproduced hash), not
`public-leaderboard`. The canonical `public-leaderboard` identity stays 11–18
until a deliberate contract bump.

**Required follow-up (not yet implemented):** there is no validator concept of a
named, archived public panel. If retired panels should carry a distinct,
machine-checkable public identity — rather than being reproduced under the
`private-env` label — `official.py` (`_resolve_expected_seeds`) needs an
archived-panel registry keyed by name/hash. Until then, do not claim a retired
panel validates as its own public panel; it validates as a reproduced
`private-env` panel.

### Row labeling

Every published row is labeled with its panel name and hash (`run_info.seed_panel`),
which the leaderboard builder carries through. Read the labels as:

- **Public-panel rows** (`public-leaderboard`, seeds 11–18) are reproducibility
  artifacts. Anyone can rerun them exactly and check the score; because the seeds
  are public they are contamination-exposed and should be read as "does this
  pipeline reproduce," not as a clean state-of-the-art claim.
- **Private-panel rows** (`private-env`) are the contamination-resistant claims,
  valid for the quarter their pre-committed panel was live. Published as redacted
  artifacts (seeds stripped, commitment retained); reproducible in full only
  after the panel is rotated out and revealed.

## Interpretation

Passing `sota-v2` does not mean the model is good. It means the result was run
on the official contract and is reliable enough to discuss. A model-backed
result still needs to be interpreted next to:

- mean score and paired lift against the baseline panel,
- lift against `pick-trader`, the strongest scripted baseline,
- seed win rate,
- confidence interval and sign-flip p-value,
- illegal-action count,
- failed-query count,
- fallback/error decision rate,
- lane (direct API vs. CLI harness), token usage, dollar cost, and latency.

None of these is optional context: score alone, without lane and
tokens/decision next to it, is not a comparable claim (see "Reporting
requirements" above). Results that fail `sota-v2` may still be useful
diagnostics, but they should not be used as evidence about state-of-the-art
GM skill.
