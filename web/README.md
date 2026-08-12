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

The public leaderboard dataset is a separate evidence build:

```bash
python web/scripts/build_leaderboard.py
git diff --exit-code -- web/src/data/leaderboard.json
```

The builder currently preserves and emits only the frozen `sota-v2` release
instead of recomputing its references on the live engine. Its reusable
publication-gate helpers understand the frozen `sota-v3` reference-only analysis
shape—each model compared with `pick-trader`, with no model-to-model tiers—but
the command-line builder excludes both v3 and v4 until a future site/release
decision is made explicitly.
