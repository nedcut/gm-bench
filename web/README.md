# GM-Bench Web

A forward-facing landing site for GM-Bench, built with [Vite](https://vite.dev),
React, TypeScript, and [Bun](https://bun.sh). It presents the benchmark to the
outside world: what the decision loop looks like, the stdin/stdout agent
protocol, reference baseline results, and a two-command quickstart.

The site is fully static and deploys anywhere (GitHub Pages, Netlify,
Cloudflare Pages, ...). The demo walkthrough reads
`src/data/snapshot.json`; the published results and analysis views read
`src/data/leaderboard.json`, which is generated only from committed,
policy-validated evidence.

Three surfaces share one model selection, in page order: the leaderboard
(`#results`), the model profile (`#profile`), and the mechanics analysis
(`#analysis`). The replay browser (`#replay`) plays one committed episode and
does not follow the selection. The v6 reliability fields
(`malformed_rate`, `unrecoverable_rate`, `within_seed_score_stddev`,
`per_seed_scores`, `route`) are optional on every leaderboard row: rows that
predate them render "not reported" rather than a zero.

## Develop

```bash
cd web
bun install
bun dev
```

## Build

```bash
bun run build     # type-checks and emits dist/
bun run preview   # serve the production build locally
```

## Refresh generated data

The demo snapshot is produced by a deterministic evaluation of the `value`
agent against the scripted baseline panel (`random`, `conservative`,
`win-now`, `rebuild`). To regenerate it, run from the repository root:

```bash
python web/scripts/export_snapshot.py --seeds 1 2 3 4 5 --seasons 5
```

Because the simulator is seeded, the same arguments always reproduce the same
snapshot bytes (no wall-clock timestamps in the export).

The replay browser and the browser verifier both read
`public/replay/replay_fixture.json`: one five-season episode of the
`conservative` policy on seed 1. A normal build validates the committed fixture
but never rewrites it, so regenerate it explicitly after a simulator change:

```bash
python scripts/build_web_replay_bundle.py --write-fixture
cd web && bun run build   # replays it in Pyodide and checks the state digest
```

The public leaderboard dataset is a separate evidence build:

```bash
python -m web.scripts.build_study            # sota-v5, the published dataset
git diff --exit-code -- web/src/data/leaderboard.json

python web/scripts/build_leaderboard.py      # sota-v2, the archived dataset
git diff --exit-code -- web/src/data/leaderboard-sota-v2.json
```

The site publishes `sota-v5`: `src/data/leaderboard.json` is written by
`build_study.py`, which refuses to build until every frozen publication input
carries an explicit authorization decision. The analysis is reference-only—each
model compared with `pick-trader`, no model-to-model tiers—so v5 rows carry no
`tier` and the ranking plot claims no ordering.

`build_leaderboard.py` still emits the frozen `sota-v2` release, now at
`src/data/leaderboard-sota-v2.json`, so the archived study stays reproducible.
That builder preserves the release instead of recomputing its references on the
live engine, and still excludes v3 and v4.
