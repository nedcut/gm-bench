# GM-Bench Web

Landing site for GM-Bench: why the benchmark exists, the official leaderboard
panel, the four-phase decision loop, adapters, and how to run / submit a row.

Built with [Vite](https://vite.dev), React, TypeScript, and [Bun](https://bun.sh).
The leaderboard table is rendered from static data at
`src/data/leaderboard.json` (built from `results/leaderboard/` artifacts).

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

## Refresh the leaderboard

From the repository root, after adding or updating result JSON under
`results/leaderboard/`:

```bash
python web/scripts/build_leaderboard.py
```

## Optional reference snapshot

`src/data/snapshot.json` is a deterministic `value`-vs-baselines export used for
local calibration demos. Regenerate with:

```bash
python web/scripts/export_snapshot.py --seeds 1 2 3 4 5 --seasons 5
```

The public site no longer surfaces this panel as a second results story; the
official board is the leaderboard preset (seeds 11–18).
