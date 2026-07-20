# Reproducing the `sota-v2` phase-one release

This path verifies the published evidence without provider credentials or new
model spending. It checks the frozen contract, compact result rows, raw archive
hashes, compact-to-raw links, generated analysis, and website data.

## 1. Check out the release

```bash
git clone https://github.com/nedcut/gm-bench.git
cd gm-bench
git checkout sota-v2-phase-one-2026-07-19
```

Use Python 3.11 or newer. Bun is required only for the website build.

## 2. Download and verify the raw evidence

```bash
mkdir -p /tmp/gm-bench-sota-v2-release
gh release download sota-v2-phase-one-2026-07-19 \
  --dir /tmp/gm-bench-sota-v2-release
cd /tmp/gm-bench-sota-v2-release
shasum -a 256 -c SHA256SUMS.txt
cd -
python3 scripts/package_publication_release.py \
  --verify /tmp/gm-bench-sota-v2-release/gm-bench-sota-v2-phase-one-raw-2026-07-19.zip
```

The verifier checks every archived byte hash and canonical raw JSON hash, then
proves that each committed compact artifact links to the corresponding raw
artifact where one exists.

## 3. Re-run the publication analysis

```bash
rm -rf /tmp/gm-bench-sota-v2-extracted
mkdir -p /tmp/gm-bench-sota-v2-extracted
unzip -q /tmp/gm-bench-sota-v2-release/gm-bench-sota-v2-phase-one-raw-2026-07-19.zip \
  -d /tmp/gm-bench-sota-v2-extracted
python3 scripts/analyze_publication_panel.py \
  --artifacts-dir /tmp/gm-bench-sota-v2-extracted/raw \
  --output /tmp/reproduced-publication-panel-analysis.json
cmp /tmp/reproduced-publication-panel-analysis.json \
  results/analysis/publication-panel-analysis.json
```

Expected outcome: eight eligible rows, with Grok 4.5 and Mistral Medium 3.5
rejected for incomplete usage/cost telemetry.

## 4. Validate the committed rows and generated site

```bash
for artifact in results/leaderboard/*.json; do
  python3 -m gm_bench validate-result "$artifact" --policy sota-v2
done
python3 -m gm_bench validate-contract
python3 web/scripts/build_leaderboard.py
git diff --exit-code -- web/src/data/leaderboard.json
```

Expected site gate:

- `eligible_headline_models`: 8
- `minimum_headline_models`: 8
- `publishable_ranking`: `true`
- `panel_analysis_ready`: `true`

`publishable_ranking` means the table cleared its evidence gate. It does not
override the analysis: all eight model rows occupy one overlapping uncertainty
tier and every row trails `pick-trader`.

## 5. Optional full repository verification

```bash
python3 -m pytest -q
python3 -m ruff format --check gm_bench examples tests scripts
python3 -m ruff check gm_bench examples tests scripts
cd web
bun install --frozen-lockfile
bun run lint
bun run build
```

Please report the operating system, Python/Bun versions, release archive SHA,
and exact pass/fail output on the independent-reproduction issue. A successful
clean-clone run is external validation of packaging and reproducibility—not an
independent rerun of the paid model calls.
