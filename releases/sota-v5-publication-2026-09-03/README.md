# `sota-v5` publication release

This release freezes the first public GM-Bench panel under the `sota-v5`
contract (contract fingerprint `a600b7da0c302231`, OpenRouter scaffold
`c582e126bbb6af10`) on the v6-spec sixteen-model cohort, run over the
committed 29-seed private panel with one episode per seed, zero repair
attempts, and a 4,096-token output ceiling.

## Evidence state

- 16 pre-registered model cells were launched; every one is accounted for.
- 11 cells are strict, route-matched, cost-complete headline rows
  (580 of 580 decisions each).
- 3 cells are ineligible on model behavior under rules frozen before the panel
  ran, and ship as redacted diagnostic artifacts bound to their retained
  checkpoints: gpt-oss-20b (decision failure rate 0.0207 over the 0.020 gate),
  claude-haiku-4.5 (fail-fast at seed 14), glm-5 (fail-fast at seed 25).
- 2 cells are excluded at the two-attempt infrastructure limit with no
  artifact: qwen3.8-flash (Alibaba HTTP 429 on both attempts) and gpt-5.6-sol
  (billed responses with no choices on both attempts).
- The five exclusions are listed with their frozen rule, attempts, decisions,
  cost, and checkpoint SHA-256 in the archived
  `config/sota_v5_panel_exclusions.json`.
- The Holm family stays at the registered sixteen; no p-value was eased by the
  five missing rows.

The accounted-for rule and the headline floor of eight were amended after the
panel completed and are recorded as a post-data owner decision in
`docs/run_logs/sota-v5-v6-route-and-cohort-amendment-2026-09-01.md`
(addendum 2026-09-03T20:45Z). Nothing about how any row was run, scored, or
gated changed.

## Interpretation

The predeclared analysis is reference-only: each model is contrasted against
the deterministic `pick-trader` baseline (mean 247.109 on this panel) with an
exact paired sign-flip test. No model-to-model tiers or ordinal ranking are
assigned.

Every eligible model trails `pick-trader`. Ten of the eleven headline rows
reject at Holm-adjusted alpha 0.05; gemini-3.7-flash (mean lift -23.4,
Holm-adjusted p 0.221) does not. Within-seed noise is unmeasured under the
one-repeat lane, so the minimum detectable difference rests on the calibration
panel's assumed repeat noise, as each row states.

## Contents

The archive holds the frozen configuration and smoke manifest, the exclusion
register, the generated panel analysis, the eleven redacted headline artifacts,
the three redacted diagnostic artifacts, and the final run-state and
reservation metadata. Private-panel raw artifacts and seed values are not
included; the seed panel is committed by execution hash and salted hiding
commitment in `config/sota_v5_lane.json`.
[`manifest.json`](manifest.json) records byte and canonical JSON hashes and the
compact-to-raw links. [`SHA256SUMS.txt`](SHA256SUMS.txt) is committed and
attached beside the archive.

## Verify

```bash
shasum -a 256 -c SHA256SUMS.txt
python3 scripts/package_publication_release.py --contract sota-v5 \
  --verify gm-bench-sota-v5-publication-2026-09-03.zip
```

See [`docs/REPRODUCING_SOTA_V5_RELEASE.md`](../../docs/REPRODUCING_SOTA_V5_RELEASE.md)
for the no-provider-cost verification path.

The public website still serves the `sota-v2` release; publishing this panel
on the site is a separate decision.
