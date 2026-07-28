# `sota-v3` preflight snapshot — 2026-07-27

This zero-spend preflight package starts from
`6bade3934e39d790e888f1987213628dc8f812c0`. The base-SHA facts below separate
Sunday's merged state from the provisional v3 files now present in the working
tree. This package is not a frozen preregistration, accepted smoke, model
artifact, spend approval, or claim refresh.

## Verified repository state

- The live source contract identifies `sota-v3` and resolves to fingerprint
  `4f6ddddd6a6dd81c` (`gm_bench/contract.py`).
- `python3 -m gm_bench validate-contract` passes on this checkout.
- PR #99 is present as commit `78f4655e775e0436fd714366229022e95b404699`.
  `.github/workflows/ci.yml` reads each committed current-leaderboard artifact's
  declared `benchmark_version`, dispatches `validate-result` to `sota-v1`,
  `sota-v2`, or `sota-v3`, and fails on missing/unknown versions.
- No `config/sota_v3_lane.json`, `config/sota_v3_models.json`, or
  `config/sota_v3_smoke_manifest.json` exists at the base SHA.
- No committed top-level `results/leaderboard/*.json` declares `sota-v3`; the
  public site data remains derived from the eight frozen `sota-v2` rows.
- The frozen v2 validator contract remains literal at fingerprint
  `558e8f35ea1d66b9`. This snapshot does not modify any v2 artifact, registry,
  manifest, protocol record, or generated site data.
- No paid model call was made for this reconciliation, and none is authorized
  by it.

## Provisional working-tree package

The working tree now adds:

- `config/sota_v3_lane.json`, marked `provisional-blocked`, with every spend,
  smoke, panel, and publication authorization set to false;
- `config/sota_v3_models.json`, with `selection_status:
  provisional-blocked`, no models or routes, no output cap, and no spend
  authorization;
- `config/sota_v3_smoke_manifest.json`, marked `not-started`, with no entries
  and `accepted_for_panel: false`;
- `config/sota_v3_publication_protocol.json` and
  `config/sota_v3_pricing_snapshot.json`, both blocked until the panel design,
  retry policy, live route pricing, and operator ceiling are frozen;
- required explicit `--contract sota-v2|sota-v3` runner selection for every
  active publication phase, coordinated config paths, current-fingerprint
  checks, an OpenRouter-only provider policy, and one shared authorization gate
  that fails before cells, endpoints, subprocesses, or spend logic; and
- `scripts/sota_v3_rehearsal.py` plus targeted tests for a deterministic,
  disposable synthetic artifact, real analyzer execution, and isolated
  site-data/web-build ingestion.

These files make the missing decisions explicit; they do not complete
preregistration.

## Working-tree verification

This verification ran before commit; it does not substitute for the required
clean-checkout rerun at the eventual candidate SHA.

- `uv run pytest -q`: **614 passed**.
- `uv run ruff format --check gm_bench examples tests scripts` and
  `uv run ruff check gm_bench examples tests scripts`: **clean**.
- `python3 -m gm_bench validate-contract`: **passed**.
- `bun run lint` and `bun run build` in `web/`: **passed**.
- `python3 scripts/sota_v3_rehearsal.py`: **passed**.
- Mode/evidence: deterministic synthetic non-evidence; `$0.00` spend; no
  provider or model invocation.
- Policy dispatch: accepted by `sota-v3`, rejected by `sota-v2`.
- Publication analysis: one eligible synthetic row, finite nonzero
  seed-bootstrap interval, full-family Holm dispatch, and tier assignment
  completed through `scripts/analyze_publication_panel.py`.
- Fail-closed mutations: all seven rejected — wrong contract, soft fallback,
  stale scaffold, unknown version, unregistered route, tampered compact score,
  and raw-link mismatch.
- Site path: shared row ingestion passed; the synthetic v3 row was explicitly
  excluded from the public build; generated site data matched the checked-in
  frozen-v2 dataset.
- Web path: `bun run build` passed in an isolated staged copy, leaving the real
  `web/` tree untouched.
- No real v3 provider result, accepted smoke, panel row, or publication
  artifact was created.

## Freeze boundary

Effective today, the score-affecting mechanics are semantically frozen:
simulator behavior, action/observation schemas, scoring, scripted policy logic,
and model-view compaction do not reopen for discretionary realism work.

The publication lane files now exist provisionally, but the lane is not frozen
because model/route selection, output/reasoning policy, cost assumptions, and
the operator ceiling remain unresolved. The 8-seed × 3-repeat shape is recorded
only as an illustrative candidate, not a frozen design. Its exact two-sided
sign-flip test has minimum p-value 2/2^8 = 0.0078125, which cannot clear Holm's
first 0.05/8 = 0.00625 threshold for eight predeclared reference contrasts;
repeats do not improve that seed-level resolution. Final review must affirm the seed-panel identity,
seeds-versus-repeats allocation, strict-fallback attestation, exclusions, and
multiplicity family. These are experiment-design choices, not permission to
revisit simulator mechanics.

Panel identity has two different fingerprint consequences:

- a runtime `private-env` panel can be selected and rotated without editing the
  score-affecting source fingerprint; and
- changing the canonical public seeds in
  `gm_bench/benchmark_config.py::PRESETS["leaderboard"]` changes the contract
  fingerprint.

If the power decision requires the second path, make one explicit pre-data lane
amendment, regenerate the fingerprint-bound free diagnostics, and refreeze
before any accepted smoke. Do not combine that bounded panel change with
another mechanics batch.

## Finite pre-spend checklist

- [ ] Review and finish the provisional v3 lane, empty model registry, and
  not-started smoke manifest, plus the separate v3 protocol and pricing
  records. Their identities and fingerprints already agree; model routes,
  per-route JSON/reasoning policy, pricing, and authorization remain
  intentionally unresolved.
- [ ] Record the panel-power choice and its intended claim. The focused v3 plan
  supports only each model-versus-`pick-trader` contrast, with Holm correction
  across that registered family; it does not support model tiers or all-pairs
  comparisons. First require exact sign-flip feasibility, then recompute power
  for the selected family and allocation. Do not reuse the withdrawn 0.175
  estimate or the older all-pairs 24/48/96 illustration. The frozen plan must
  also name an inference method and power analysis that match: paired t,
  deterministic Monte Carlo sign-flip, or exact enumeration with at most 20
  independent seeds. Exact enumeration is the only method currently
  implemented by the publication analyzer; choosing another requires its
  implementation and validation before spend can unlock.
- [x] Run an integrated, no-provider-call rehearsal that exercises result
  generation, v3 policy selection, compaction, raw/compact hashing, and site
  ingestion while leaving the public v2 page intact.
- [x] Demonstrate fail-closed behavior for at least: stale contract/scaffold,
  unregistered route or policy, incomplete strict-fallback provenance, broken
  raw/compact hash linkage, and unknown benchmark version.
- [ ] After commit, repeat the rehearsal from a clean checkout and record its
  command/output and exact candidate SHA. Label every generated result
  disposable and non-evidence.
- [ ] After routes are selected, explicitly authorize and run
  `python3 scripts/run_publication_matrix.py route-preflight --contract sota-v3`.
  This phase performs exact endpoint/parameter checks and never launches a
  model subprocess or completion call. Only after it passes may the operator
  separately freeze the statistical plan and authorize a paid smoke.
- [ ] Review this package and make a separate explicit decision before the
  cheapest serial route smoke.

Until every item above is reviewed, paid v3 smoke and panel spend remain
unauthorized. Completing the checklist prepares a spend decision; it does not
make that decision automatically.

## Deferred, not blocking rehearsal

- v3 site migration and headline refresh;
- post-hoc weight sensitivity and outcome-only reporting, which require real v3
  rows;
- claim-provenance UI;
- a causal memo intervention/ablation (the landed memo result is associative);
- dead-cap/reference-agent realism polish not tied to a demonstrated
  claim-threatening defect; and
- independent reproduction of the published v2 package.

These remain useful follow-through. Treating all of them as prerequisites for
offline rehearsal would turn Issue #93 back into an open-ended audit.
