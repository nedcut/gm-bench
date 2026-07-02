# GM-Bench Web

A forward-facing landing site for GM-Bench, built with [Vite](https://vite.dev),
React, TypeScript, and [Bun](https://bun.sh). It presents the benchmark to the
outside world: what the decision loop looks like, the stdin/stdout agent
protocol, reference baseline results, and a two-command quickstart.

All charts and tables are rendered from a static snapshot of real benchmark
output committed at `src/data/snapshot.json`, so the site is fully static and
deploys anywhere (GitHub Pages, Netlify, Cloudflare Pages, ...).

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

## Refresh the results snapshot

The snapshot is produced by a deterministic evaluation of the `value` agent
against the scripted baseline panel (`random`, `conservative`, `win-now`,
`rebuild`). To regenerate it, run from the repository root:

```bash
python web/scripts/export_snapshot.py --seeds 1 2 3 4 5 --seasons 5
```

Because the simulator is seeded, the same arguments always reproduce the same
snapshot.
