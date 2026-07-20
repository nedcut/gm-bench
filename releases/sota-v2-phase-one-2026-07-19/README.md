# `sota-v2` phase-one release

This release freezes the first public GM-Bench panel under the corrected
`sota-v2` contract and the common 4,096-token native-minimum-reasoning API lane.

## Evidence state

- 10 pre-registered model cells completed.
- 8 cells are strict, route-matched, cost-complete headline rows.
- Grok 4.5 is diagnostic because usage covers 476/480 decisions and cost covers
  474/480.
- Mistral Medium 3.5 is diagnostic because cost covers 479/480 decisions after
  one adapter fallback.
- All eight eligible rows occupy one overlapping uncertainty tier.
- Every eligible model trails `pick-trader` (411.619).

The release archive contains the exact ten raw public artifacts, frozen registry
and protocol files, generated panel analysis, and final run/reservation metadata.
[`manifest.json`](manifest.json) records byte and canonical JSON hashes plus
compact-to-raw links. [`SHA256SUMS.txt`](SHA256SUMS.txt) is committed and
attached beside the archive.

## Interpretation

Muse Spark 1.1 has the highest observed eligible mean (231.851), but the study
does not support an ordinal winner claim. The public panel contains eight seeds;
full-family Holm-adjusted p-values are 0.078125, and model intervals overlap.

See [`docs/blog/sota-v2-findings.md`](../../docs/blog/sota-v2-findings.md) for
the narrative and
[`docs/REPRODUCING_SOTA_V2_RELEASE.md`](../../docs/REPRODUCING_SOTA_V2_RELEASE.md)
for the no-provider-cost verification path.
