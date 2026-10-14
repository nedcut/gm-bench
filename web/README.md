# GM-Bench Web

The public GM-Bench site, built with [Vite](https://vite.dev), React,
TypeScript and [Bun](https://bun.sh). It is a small data app: GM-Bench 2.0
results first, with as little prose as possible.

The site is fully static. Every page reads `src/data/leaderboard.json`, which
is generated only from committed, policy-validated evidence. There is one HTML
entry per page (GitHub Pages has no SPA fallback, so every linked URL is a real
file; see `vite.config.ts`):

- `/` (`src/main.tsx`, `src/app/Standings.tsx`): the 2.0 standings. Every
  panel row with the scripted bots, sorted by score for reading, with a side
  panel for filters (harness, vendor, bots) and a row's details.
- `/how-it-works/` (`src/app/HowItWorks.tsx`): a step-by-step walkthrough of
  one pick-trader season: the brief, the tools open in each phase, the moves
  as 2.0 tool calls, and how the score moved. Its data,
  `src/data/walkthrough.json`, is built by `scripts/build_walkthrough.py` from
  the public demo game in `public/replay/trajectory-demo.json`.
- `/cost/` (`src/app/CostView.tsx`): score against cost per game.
- `/tools/` (`src/app/ToolsView.tsx`): tool calls, tokens, wall time and
  empty phases per game.
- `/replays/` (`src/pages/replays.tsx`): the trajectory explorer and the
  play-along decision deck.
- `/method/` (`src/app/Method.tsx`): rules, scoring, statistics, caveats, how
  to run it, and the in-browser replay verifier. Linked from the footer.
- `/v1/` (`src/app/V1Archive.tsx`): the superseded 1.0 (sota-v5) results.
  Linked from the footer.

Filters are stored in `localStorage` and apply on every tab. `src/v2.ts` turns
the leaderboard record into the rows every page shows. Styles are
`src/app.css` (the app) plus `src/legacy.css`, scoped under `.legacy`, for the
components carried over from the earlier site (play-along deck, replay
verifier). The social card lives in `public/media/`.

## Develop

The How it works and Replays pages share a small interactive rink. Drag or
flick the blue/red players and puck; Blue scores in the top net, Red in the
bottom. Arrow keys move a focused piece, Shift + arrow throws it, Space shoots,
and Home returns it to its starting position. The reset icon in the rink clears the game. Goals leave the puck in the net
and trigger a short confetti burst; drag it back out to keep playing. The sides,
back and posts of each net deflect the puck.
Positions, momentum and scores are saved under `gm-bench.rink.v1` in browser
storage and carried between pages and reloads. Other open pages mirror saves.
The rink still works when storage is blocked, but cannot persist then.

Physics uses a fixed step and updates SVG transforms without React frame renders.
The animation loop stops when settled and pauses offscreen or in a hidden tab.
Occasional small player movements hint at interaction while visible and idle,
then settle. Idle movements and confetti are disabled for reduced motion.
Builds run the rink physics and scoring/storage tests; `e2e/rink.spec.ts` covers
pointer/touch interaction, scoring, persistence, idle hints and accessibility behavior.

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

`build_study.py` also reads `results/leaderboard/decision-lane/` into
`decision_lane_models`: rows run on the same contract and private panel by a
decision model (`transport: decision-api`, see `docs/typesafe_jev_lane.md`).
They render in their own section and never join `models`, the
eligible-headline count, or the shot chart; `scripts/validate_results_data.ts`
fails the build if they do.

It also reads `results/agentic/` into `agentic_lane`: GM-Bench 2.0 rows
(`docs/bench_v2_spec.md`), panel grade only, each validated against the
checkout's 2.0 contract and the frozen panel in `config/bench_v2_lane.json`.
Smoke rows are skipped. A row is flagged `unpinned` unless its model is listed
in that file's `model_pinning.pinned_models`. Rows are ordered by pinning,
model, and harness, never by score, and carry no 1.0 row's score. Each row
carries its artifact's `reference` block, the spec's one supported inference:
pick-trader on the row's own seeds and seasons (pick-trader and random means,
paired lift with its 95% interval, sign-flip p, seed win rate). The 2.0
pages show an empty table while the list is empty, and
`scripts/validate_results_data.ts` fails the build if a 2.0 row is not panel
grade, is off the frozen panel, is same-user, lacks the pinning flag, lacks a
reference or carries one that is not pick-trader on exactly the row's (and the
lane's) seed count with no per-seed values, carries a reference whose numbers
contradict each other or the row mean, or pick-trader and random means that
differ from `reference_scores` in the lane config (once recorded) or from
another row's at the same seasons, carries any other p-value or paired
field (nothing compares two rows, harnesses, or models), or appears in a 1.0
table.

`build_leaderboard.py` still emits the frozen `sota-v2` release, now at
`src/data/leaderboard-sota-v2.json`, so the archived study stays reproducible.
That builder preserves the release instead of recomputing its references on the
live engine, and still excludes v3 and v4.

## Play the human challenge

Open `/play/` (the **Play** tab) to manage the Anchorage Auroras through the
same five seasons and twenty decision windows as the benchmark. The interface
includes the full roster and lineup, cap space, standings and rival rosters,
contracts, free agents, waivers, trades and counteroffers, scouting, draft
picks, season history, a score breakdown, and a final comparison with pick-trader
on the same seed. The old decision deck links here.

`src/game/gameWorker.ts` lazily loads Pyodide and the generated Python source
bundle. Vite generates the game's archive at startup for both `bun dev` and
production builds, then imports it as an asset with a content-hashed production
URL. An old `public/replay/gm_bench.zip` cannot shadow the game bundle. Restart
the dev server after editing Python simulator sources.
`gm_bench/browser_game.py` adapts the frozen `AgenticEpisode` without
changing the contract files. Decisions execute serially in the worker. There
are no provider calls, server sessions, or writes to leaderboard evidence.
Python is downloaded from jsDelivr on first launch, so a working connection is
needed; loading failures leave saves available and can be retried.

One challenge autosaves under `gm-bench-human-save-v1` in localStorage after
each action. Export/import JSON to back up a game or transfer it. Saves hold a
seed and action log and replay through the simulator on resume. Their engine
version is the SHA-256 of the deterministic Python bundle; incompatible or
malformed imports leave the current game intact. Export a save before changing
simulator versions. LocalStorage failure leaves the active game playable and
shows an export reminder.

For a full manual test:

1. Start seed 1, check the 23-player roster, $19.45M cap room, and tied standings.
2. Set a lineup; negotiate a signing or preseason extension. Review the cap
   impact, confirm, and check the updated roster and result summary.
3. Build a trade, including future picks; advance to midseason for waivers and
   the trade deadline for incoming offers and counteroffers.
4. Open the draft, scout a prospect, and spend your pick before finishing the
   season. Repeat through season five and inspect the final score and history.
5. Export, reload, resume, and import. An invalid import must preserve the game.

Automated coverage runs the original Python episode beside the browser adapter,
restores at every window, and plays a complete challenge through production
assets with the installed Pyodide runtime bytes (no CDN dependency in tests):

```bash
.venv/bin/python -m pytest -q tests/test_browser_game.py
cd web
bun test scripts/simulatorBundle.test.ts  # stale-archive dev startup regression
bun run test:browser -- game.spec.ts
```
