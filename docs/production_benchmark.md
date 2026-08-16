# Production Benchmark Standard

GM-Bench has one general result tier plus versioned strict policies:

- `public-leaderboard`: a structurally valid public leaderboard result.
- `sota-v5`: the current strict validator for new development results.
- `sota-v4`: the frozen terminal validator for the Qwen-incompatible successor attempt.
- `sota-v3`: the frozen validator for the terminal five-of-eight smoke campaign.
- `sota-v2`: the frozen historical validator for the published phase-one study.
- `sota-v1`: the frozen historical validator for archived v1 evidence. It does
  not make a v1 row comparable to v2; it only keeps the archived contract
  independently auditable.

`sota-v4` is terminal: its Qwen/Alibaba route exhausted its two infrastructure
attempts with a reasoning-mandatory HTTP 400, so it has no publishable panel.
The outcome-independent successor is `sota-v5`, preregistered in
`config/sota_v5_lane.json`, `config/sota_v5_models.json`, and
`config/sota_v5_publication_protocol.json`. V5 retains seven non-Qwen v4
identities and replaces that slot with Google Gemini 3.7 Flash on a provisional
Google Vertex global route selected from public metadata before any v5 result.
The replacement is not a v4 amendment and no v4 data carries forward.

The v5 contract freezes the same unused hidden 16-seed commitment, with an
explicit owner attestation required before seed access. It uses a uniform
reasoning-disabled policy, a 4,096-token cap, one repair, serial execution,
two infrastructure attempts per cell, exact paired sign-flip tests, and
Holm-Bonferroni adjustment over eight contrasts. Route preflight is limited to
zero-completion metadata; v5 spend, smoke, panel, and publication authorizations
remain false until separately approved. The protocol-maximum smoke estimate is
below the owner-set `$10` ceiling, while panel authorization remains a separate
decision. See `docs/run_logs/sota-v5-preregistration-2026-08-16.md` for the
lineage and boundary record.

The public leaderboard can show development and diagnostic rows, including local
models that are below the scripted baselines. A current `sota-v5` result is the
minimum technical bar for a new serious comparison.

There are two distinct v5 workflows. The generic strict submission flow below
uses the public leaderboard preset and at least 3 repeats. Separately, the
official v5 publication lane is pre-registered in `config/sota_v5_lane.json` and
`config/sota_v5_models.json`: it is a **private** 16-seed × 1-repeat panel
against the still-hidden seed set originally frozen for v3. That private lane carries
`publication_authorized: false`. Do not publish its panel or apply its 1-repeat
design to a generic third-party submission.

Committed official artifacts belong in `results/leaderboard/` and must pass the
`public-leaderboard` validator in CI. Ineligible runs that are retained for
transparency belong in `results/diagnostics/`. The site builder separates
the frozen phase-one v2 rows from current development and explicitly archived
pre-v2 evidence while preserving the official-artifact gate.

## Strict result requirements

A new strict result on development HEAD is produced under `sota-v5`:

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
fill rows with fallback `noop`s, which then fails the strict failure-rate gate.
Opt into concurrency only when the provider can handle it:
`GM_BENCH_WORKERS=N` or `--workers N`. Scripted in-process baselines still
parallelize.

**Claude is never a parallel provider.** `GM_BENCH_WORKERS` overrides the serial
default — leave it unset or force `GM_BENCH_WORKERS=1` for Claude. On 2026-07-11 a
parallel Sonnet leaderboard panel emptied a Claude Pro 5h usage limit in ~5
minutes wall clock and produced a 0.873 decision failure rate. The
multi-megabyte failed artifact is intentionally not retained. Prefer
`--preset smoke` first; a clean serial strict panel is
multi-hour quota spend, not a quick retry.

The SOTA-v3 and SOTA-v4 strict-smoke lanes are terminal and must not be rerun.
SOTA-v5 has a frozen prospective cohort and authorizes only authenticated
zero-completion route/privacy collection and route preflight; spend, smoke,
panel, and publication remain disabled. Collect the fresh v5 route record
without allowing a historical contract path to be selected:

```bash
uv run python scripts/collect_sota_v3_route_evidence.py \
  --contract sota-v5 --apply-registry
uv run python scripts/run_publication_matrix.py route-preflight \
  --contract sota-v5
```

These commands read authenticated metadata only and record zero completion
calls. The v5 smoke-command dry run deliberately does not read Keychain or set
`GM_BENCH_PRIVATE_SEEDS`; smokes use only the public smoke seed. Paid smoke
commands remain unauthorized until this evidence, the seed-free final dry run,
exact-head CI, and a separate owner decision all pass. Keychain verification
and the explicit owner attestation are deferred to the private panel gate.
Panel execution remains a separate post-smoke decision.

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
  --output /tmp/gm-bench-<provider>-<model>-private.redacted.json \
  --policy sota-v5
```

It must also satisfy the machine validator:

```bash
python -m gm_bench validate-result \
  /tmp/gm-bench-<provider>-<model>.json \
  --policy sota-v5
```

Before publishing claims from a new source contract, run the benchmark
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
- Strict failure handling (`sota-v3` only): `run_info.strict_fallback` must be
  `true` and `run_info.provider_options.GM_AGENT_STRICT` must be `"1"`, and the
  two must agree. A failed decision then emits a bare `noop` instead of a
  host-supplied draft pick and lineup, so no roster movement is credited to a
  model that produced nothing. `model --preset leaderboard` and every
  `run_publication_matrix` cell default to strict; `--no-strict-fallback`
  records `strict_fallback: false` and makes the row ineligible. Frozen
  `sota-v1`/`sota-v2` rows were measured under the soft fallback and are
  validated without this check.
- Per-episode score components (`sota-v3` only): every episode row must carry a
  complete `score_components` block — nine raw end-of-episode metrics, the
  protocol penalty, and nine weighted `*_contribution` terms. The validator
  rejects a missing term, any non-finite or non-numeric value, contributions
  that no longer sum to the row's `strategy_score`, and a `protocol_penalty`
  that disagrees with the row. Frozen v1/v2 artifacts predate the field and
  validate without it.
- Complete paired analysis, including sign-flip p-value and strongest-baseline
  comparison.
- Fresh-spawn condition: `run_info.session` must be absent or false. Session
  rows (`--session`, model keeps its full trajectory in context) are a separate
  labeled condition — publishable, but never comparable with memo-only rows and
  never eligible for the active strict policy.
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

As of the `558e8f35ea1d66b9` re-freeze, `failed_queries` is narrowed to count
only lookups that never resolve — an unknown id, or a `scout` action whose
`player_id` and `prospect_id` disagree (ambiguous targets are now rejected as
unresolvable rather than silently preferring `player_id`). Operational refusals
of a *valid* target — "already scouted", "no scouting points left" — are no
longer conflated with lookup failures: they are counted separately in the new
`query_declines` counter (`episode.query_declines`, `summary.query_declines`,
and `candidate.summary.query_declines`). `query_declines` is diagnostic only
and does **not** feed the failed-query eligibility gate below; only genuine
unresolved lookups can push a row toward that gate.

Failed queries are zero-penalty by design, but runaway rates are gated by
`failed_queries / decisions`:

- **warning** above `warn_failed_query_rate` (**0.25**): the model is misfiring
  lookups often enough that it may not be reading query errors back before
  retrying.
- **hard error under `sota-v2`** above `max_failed_query_rate` (**1.0**): more
  failed lookups than decisions on average. That row is **ineligible**, not a
  soft diagnostic — under v1 this is exactly how the scout contract break hid
  itself (Luna ~2.3 failed queries/decision).

A `sota-v2` row can still be eligible with the warning alone; crossing the
hard gate fails validation.

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
`558e8f35ea1d66b9`** (protocol `gm-bench-v2` with midseason, the full baseline
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

- The released v2 rows validate against a literal historical contract rather
  than the current source fingerprint. Reproduce them from the tagged release;
  current HEAD emits v3.
- Simulator, scoring, preset, or schema changes that alter the fingerprint do
  not amend `sota-v2` — the Issue #84 fixes started `sota-v3`, which needs its own
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
  using `scripts/seed_panel_commitment.py commit`. The helper creates a new
  plaintext secret file with mode 0600 and refuses to overwrite it; gitignore
  is not encryption. Move that file into recoverable encrypted escrow or a
  secret manager, and announce only the commitment digest. This is a real
  hiding commitment, unlike the unsalted
  `seed_panel_hash` embedded in artifacts, which is brute-forceable from the
  digest.
- When the panel rotates out, reveal salt + seeds
  (`seed_panel_commitment.py verify`) so the prior quarter's private rows become
  independently reproducible.

### Panel identity vs contract

Rotation changes the **panel**, not the **contract**. The private panel is
supplied at run time and is *not* part of the contract fingerprint, so swapping
it in and out does not touch the frozen `558e8f35ea1d66b9` and does not start a
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
