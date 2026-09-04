# Reproducing the `sota-v5` publication release

This path verifies the published evidence without provider credentials or new
model spending. It checks the frozen contract files, the redacted compact
rows, and the hash links that bind those rows to withheld raw artifacts.

The archive does not include raw artifacts or seed values. You cannot recompute
the panel analysis from the public package. That is the intended split, not a
gap in this guide.

## 1. Check out the release

```bash
git clone https://github.com/nedcut/gm-bench.git
cd gm-bench
git checkout sota-v5-publication-2026-09-03
```

Use Python 3.11 or newer.

## 2. Download and verify the archive

```bash
mkdir -p /tmp/gm-bench-sota-v5-release
gh release download sota-v5-publication-2026-09-03 \
  --dir /tmp/gm-bench-sota-v5-release
cd /tmp/gm-bench-sota-v5-release
shasum -a 256 -c SHA256SUMS.txt
cd -
python3 scripts/package_publication_release.py --contract sota-v5 \
  --verify /tmp/gm-bench-sota-v5-release/gm-bench-sota-v5-publication-2026-09-03.zip
```

Expected verify line:

`ok: ... contains 11 headline and 3 diagnostic model artifact(s)`

The zip checksum is
`7fa7ae546132e96c87546683bbe4de4d88c2715c40b439ee48332d166829eef2`.

The verifier checks every archived byte hash. It confirms the eleven headline
and three diagnostic compact artifacts are redacted (no seed values, empty
episode lists). It then checks that each compact row names the same
raw-artifact SHA-256 as the analysis file and the release manifest.

## 3. Validate the committed redacted rows

```bash
for artifact in results/leaderboard/sota-v5/*.json; do
  python3 -m gm_bench validate-result "$artifact" --policy sota-v5
done
python3 -m gm_bench validate-contract
```

Expected outcome: eleven headline rows pass `sota-v5`. Every one warns that
the candidate does not beat the strongest scripted baseline. Some rows also
warn about illegal actions or adapter fallback. Those warnings do not fail
the policy.

The three diagnostic rows fail on purpose. Check them if you want to see the
recorded reasons:

```bash
for artifact in results/diagnostics/sota-v5/*.json; do
  python3 -m gm_bench validate-result "$artifact" --policy sota-v5 || true
done
```

- `openrouter-claude-haiku-4.5-anthropic` and `openrouter-glm-5-streamlake`
  fail with `paired.num_seeds must be 29` (fail-fast, incomplete panel).
- `openrouter-gpt-oss-20b-deepinfra` fails with
  `candidate decision_failure_rate 0.021 exceeds 0.020`.

`validate-result` means the compact JSON is well-formed and self-consistent
under `sota-v5`. It does not mean the numbers came from a real run. Binding a
row to withheld evidence is the job of `publication.raw_artifact_sha256` and
the release checksums.

## 4. What this does not reproduce

You cannot regenerate `results/analysis/publication-panel-analysis-v5.json`
from the public files. The analyzer reads the private seed panel and the
unredacted raw artifacts. Neither is in the zip.

The published SHA-256 values prove a narrower claim. For each headline row,
the compact artifact, the analysis row, and the release manifest all name the
same digest of a raw JSON file that is not in the archive. Anyone who holds
that file can show it hashes to the published digest. The public package does
not let you rebuild scores, p-values, or means from episodes.

The seed panel is committed only as an execution hash and a salted hiding
commitment in `config/sota_v5_lane.json`.

The public website still serves the `sota-v2` study. Do not treat a website
rebuild as part of this check.

## 5. Optional full repository verification

```bash
python3 -m pytest -q
python3 -m ruff format --check gm_bench examples tests scripts
python3 -m ruff check gm_bench examples tests scripts
```

A successful clean-clone run is external validation of packaging and of the
redacted rows. It is not an independent rerun of the paid model calls.
