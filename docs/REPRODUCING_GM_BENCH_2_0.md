# Verifying the public GM-Bench 2.0 artifacts from a clean clone

This guide validates the committed evidence without provider credentials,
Docker, a harness login, private seeds or new model spending. It exercises
the supported CLI against the public compact artifacts and scripted agents.
Downloading source and installing development tools requires internet access.
The validation commands themselves run locally without model requests.

Four panel rows are public, but GM-Bench 2.0 has no tag or GitHub release yet.
The rows are all `unpinned`: they may not be reproducible and are extra data
points, not headline results. This guide does not promote them to headlines.

## Check out the evidence snapshot and install

Use Python 3.11 or newer. The full commit below is the main-branch evidence
snapshot reviewed on 2026-10-02, not a release tag. Detaching at it keeps this
guide's expected artifact counts stable if more rows land later.

```bash
git clone https://github.com/nedcut/gm-bench.git
cd gm-bench
git checkout --detach 07de4b20af32d4a6a7381c13abf4577296c277d3
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m gm_bench --help
```

The simulator has no runtime dependencies. The `dev` extra installs the test
and lint tools used below; no environment file or credential setup is needed.
Work from the repository root for the remaining commands.

## Validate all committed 2.0 artifacts

```bash
(
set -eu
count=0
for artifact in results/agentic/*.json; do
  .venv/bin/python -m gm_bench agentic-validate "$artifact" --json
  count=$((count + 1))
done
test "$count" -eq 11
printf 'validated %s agentic artifacts\n' "$count"
)
```

Expected: eleven reports with `"ok": true` and `"errors": []`: four
`panel` artifacts and seven `smoke` artifacts. The smoke rows use public
seeds and do not appear in the site's panel table.

Warnings are separate from errors. Older rows record the driver revision
that played them, so a warning that it differs from this checkout is
expected. Haiku also retains the disclosed post-hoc guessed-draft-pick
warnings. A zero exit status does not establish headline eligibility or
erase these caveats. Inspect the saved artifact's `validation` block as
well as the validator's current report.

Check the identities, frozen fingerprint and numeric disclosures directly:

```bash
.venv/bin/python - <<'PY'
import json
from pathlib import Path

from gm_bench.agentic.contract import agentic_fingerprint

assert agentic_fingerprint() == "07de948a4f4afbae"
artifacts = [json.loads(p.read_text()) for p in sorted(Path("results/agentic").glob("*.json"))]
panels = [d for d in artifacts if d["grade"] == "panel"]
assert len(artifacts) == 11 and len(panels) == 4
lane = json.loads(Path("config/bench_v2_lane.json").read_text())
assert lane["model_pinning"]["pinned_models"] == {}
for row in panels:
    assert row["contract"]["agentic_fingerprint"] == agentic_fingerprint()
    assert row["panel"]["sha256"] == lane["seed_panel"]["artifact_panel_sha256"]
    assert row["reference"]["num_seeds"] == 32 and row["seasons"] == 5
    assert row["isolation"] == "container"
    assert row["summary"]["usage"]["cost_usd"] is None
    harness = row["harness"]
    print(harness["name"], harness["version"], harness["model"],
          "mean", row["summary"]["mean_score"],
          "lift", row["reference"]["paired_lift_mean"],
          "API-equivalent estimate", row["agentic_summary"]["api_equivalent_cost_usd"])
print("frozen agentic fingerprint", agentic_fingerprint())
PY
```

Expected panel means are 227.404 (Codex `gpt-6-luna`), 227.393 (Claude Code
`claude-sonnet-5`), 130.129 (Claude Code `claude-haiku-4-5`) and 230.563
(Cursor `composer-2.5`). The reference is `pick-trader` at 249.18 on the
frozen 32-seed panel. Every contrast is against that reference; these are
not tests between model or harness rows.

The whole-panel API-equivalent estimates are $4.539983, $157.375340 and
$27.707858 for Codex, Sonnet and Haiku respectively. They are dated
list-price estimates from token usage, not subscription bills. Codex's
short-context estimate is a lower bound because the artifact flags possible
long-context requests. Haiku preserves its former $25.143227 beside the
corrected estimate. Cursor reports no cost, and its model has no repository
list price, so its estimate is `null`. All four measured `cost_usd` values
are `null`; none of these values supports a measured cost ranking.

## Confirm a corrupted compact artifact is rejected

Keep the original evidence unchanged. Make a temporary copy under the
gitignored `output/` directory:

```bash
(
set -eu
mkdir -p output/reproduction
.venv/bin/python - <<'PY'
import json
from pathlib import Path

source = Path("results/agentic/claude-2.1.281-claude-sonnet-5-smoke-1x5.json")
row = json.loads(source.read_text())
row["episodes"][0]["final_score"] = 999.0
Path("output/reproduction/tampered.json").write_text(json.dumps(row))
PY
if .venv/bin/python -m gm_bench agentic-validate output/reproduction/tampered.json --json; then
  printf 'ERROR: corrupted artifact was accepted\n' >&2
  exit 1
fi
)
```

Expected: validator exit 1, `"ok": false`, and an error that
`summary.mean_score` does not match the per-seed episode mean `999.000`.

## Run the local contract and scripted checks

```bash
.venv/bin/python -m gm_bench validate-contract --json
.venv/bin/python -m gm_bench run --agent value --seeds 1 --seasons 1 --no-log --json
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff format --check gm_bench examples tests
.venv/bin/python -m ruff check gm_bench examples tests
```

Expected: the official canaries report `"ok": true`, the scripted run
completes without a model request or database write, and tests and lint pass.
The test suite uses stand-in harnesses and local sockets, so it needs a local
environment that permits socket binding; it does not launch a paid harness.
The public seed-1 scripted run checks the simulator path; it does not
recompute the private-panel reference or reproduce a model episode.

## What remains outside this verification

Standalone `agentic-validate` checks a compact row's shape, contract,
panel commitment, pinned reference means and internal numeric consistency.
The compact artifacts omit private seed values, ledgers and harness event
streams. Without those raw runs, this path cannot independently replay
actions, recompute the paired statistics, verify the recorded prompt audit
or establish that the numbers came from the claimed execution. A raw-run
SHA-256 in an artifact binds the claim to withheld bytes; it does not make
those bytes publicly available or independently authenticated.

An operator with the matching raw directory can additionally run
`python -m gm_bench agentic-validate <artifact> --raw <raw-run-directory>`.
That checks the `run.json` hash binding and equality with a fresh redaction,
including the raw ledger audit and reference recomputation. It is not part
of this credential-free public path. Keep private seeds and raw artifacts
out of Git, terminal output and shared logs.

New harness runs consume provider budget or subscription quota and need a
separate run decision. The contract remains frozen at `07de948a4f4afbae`;
known audit, replay and server changes remain in the [next-version
queue](bench_v2_1_queue.md). See the [specification](bench_v2_spec.md),
[operator guide](agentic_lane.md), [findings draft](blog/gm-bench-2.0-findings.md)
and [publication checklist](PUBLISH_READINESS.md) for their full limitations.
