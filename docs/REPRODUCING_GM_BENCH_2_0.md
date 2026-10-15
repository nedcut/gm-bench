# Verifying the public GM-Bench 2.0 artifacts from a clean clone

This guide validates the committed evidence without provider credentials,
Docker, a harness login, private seeds or new model spending. It exercises
the supported CLI against the public compact artifacts and scripted agents.
Downloading source and installing development tools requires internet access.
The validation commands themselves run locally without model requests.

Twelve panel rows are public, but GM-Bench 2.0 has no tag or GitHub release yet.
The rows are all `unpinned`: they may not be reproducible and are extra data
points, not headline results. This guide does not promote them to headlines.

## Check out the evidence snapshot and install

Use Python 3.11 or newer. The evidence snapshot is the main-branch commit
that added the newest panel row (OpenCode 2.0.27
`muse-spark-1.3-contributor`, published 2026-10-14),
not a release tag; the `git log` lookup below finds it. Detaching at it keeps
this guide's expected artifact counts stable if more rows land later.

```bash
git clone https://github.com/nedcut/gm-bench.git
cd gm-bench
git checkout --detach "$(git log origin/main -1 --diff-filter=A --format=%H -- \
  results/agentic/opencode-2.0.27-muse-spark-1.3-contributor-panel-32x5.json)"
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
test "$count" -eq 22
printf 'validated %s agentic artifacts\n' "$count"
)
```

Expected: twenty-two reports with `"ok": true` and `"errors": []`: twelve
`panel` artifacts and ten `smoke` artifacts. The smoke rows use public
seeds and do not appear in the site's panel table.

Warnings are separate from errors. Older rows record the driver revision
that played them, so a warning that it differs from this checkout is
expected. Haiku 4.5 also retains the disclosed post-hoc guessed-draft-pick
warnings, and Sonnet 5.5 the disclosed post-hoc guessed-signing warning. A zero exit status does not establish headline eligibility or
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
assert len(artifacts) == 22 and len(panels) == 12
lane = json.loads(Path("config/bench_v2_lane.json").read_text())
assert lane["model_pinning"]["pinned_models"] == {}
for row in panels:
    assert row["contract"]["agentic_fingerprint"] == agentic_fingerprint()
    assert row["panel"]["sha256"] == lane["seed_panel"]["artifact_panel_sha256"]
    assert row["reference"]["num_seeds"] == 32 and row["seasons"] == 5
    assert row["isolation"] == "container"
    cost = row["summary"]["usage"]["cost_usd"]
    assert (cost is None) == (row["harness"]["name"] != "opencode")
    harness = row["harness"]
    print(harness["name"], harness["version"], harness["model"],
          "mean", row["summary"]["mean_score"],
          "lift", row["reference"]["paired_lift_mean"],
          "cost", cost,
          "API-equivalent estimate", row["agentic_summary"].get("api_equivalent_cost_usd"))
print("frozen agentic fingerprint", agentic_fingerprint())
PY
```

Expected panel means are 227.404 (Codex `gpt-6-luna`), 227.393 (Claude Code
`claude-sonnet-5`), 130.129 (Claude Code `claude-haiku-4-5`), 230.563
(Cursor `composer-2.5`), 247.134 (OpenCode 1.18.31 `deepseek-v4.1-flash`),
273.167 (Codex `gpt-6.1-sol`), 202.665 (Claude Code `claude-haiku-5-5`),
288.417 (Codex `gpt-6-astra`), 244.586 (OpenCode 2.0.27
`deepseek-v4.1-flash`), 217.06 (Claude Code `claude-sonnet-5-5`), 202.496
(Claude Code `claude-opus-5-5`) and 250.33 (OpenCode 2.0.27
`muse-spark-1.3-contributor`). The reference is `pick-trader` at 249.18 on the
frozen 32-seed panel. Every contrast is against that reference; these are
not tests between model or harness rows.

The whole-panel API-equivalent estimates are $4.539983, $157.375340,
$27.707858, $17.379311, $4.887320, $115.038552, $38.312087 and $129.124780
for `gpt-6-luna`, Sonnet 5, Haiku 4.5, `gpt-6.1-sol`, Haiku 5.5,
`gpt-6-astra`, Sonnet 5.5 and Opus 5.5 respectively. They are
dated list-price estimates from token usage, not subscription bills. The
`gpt-6-astra` estimate was re-derived at redaction (the run recorded `null`
because the model was not yet priced), and its artifact keeps the recorded
figure under `api_equivalent_recorded`. All three Codex estimates are short-context lower
bounds because their artifacts flag possible long-context requests, and so
is the Haiku 5.5 estimate: 1,037 of its 2,837 requests had prompts over
Haiku 5.5's 100,000-token threshold, where every rate is 5x, which puts
the panel at about $12 to $16. Haiku 4.5 preserves its former $25.143227 beside the
corrected estimate. Cursor reports no cost, and its model has no repository
list price, so its estimate is `null`. Those nine rows' measured
`cost_usd` values are `null`. The three OpenCode rows carry OpenCode's own
cost figures: $3.691094 and $4.909211 for the two DeepSeek rows (1.18.31
and 2.0.27), which have no API-equivalent estimate, and $1.701723 for
`muse-spark-1.3-contributor`, at Muse Spark 1.3's discounted Contributor
rates (Meta may train on the prompts and completions). That
row also carries an API-equivalent estimate of $69.902898, its recorded
tokens at the model's standard list price, added at redaction; the run
recorded none, and the artifact keeps the empty recorded fields under
`api_equivalent_recorded`. All three ran on an OpenCode Go
subscription, which counts usage against the plan's limits rather than
billing per token. None of these values supports a cost ranking.

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
