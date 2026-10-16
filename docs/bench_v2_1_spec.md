# GM-Bench 2.1: specification

Built 2026-10-15. Its rules and weights were fixed before any model row was
played under it; a first paid round (below) has since been played and
passed, so they are now frozen: any change is a new version.

2.1 is the 2.0 agentic lane (`docs/bench_v2_spec.md`) with three simulator
fixes and a new scoring version. The tools, the task brief, the phase
calendar, the phase guard and the ledger format are 2.0's, byte for byte.
The evidence for every change is in [score_v2_proposal.md](score_v2_proposal.md),
[score_deep_dive.md](score_deep_dive.md) and
[bench_v2_1_queue.md](bench_v2_1_queue.md); the decisions are logged in
`docs/lab_notebook.html`.

## What changes

| | 2.0 | 2.1 | Queue item |
|---|---|---|---|
| Team records | Never reset: every summary, the standings, playoff seeding, the lottery and the free-agent win signal read the running total since season 1 | Reset when each season opens | 15 |
| Playoff scoring | Realized single-game results: 9 a round, 35 a title | Exact expectation from the bracket and the playoff ratings, same weights | 16 |
| Wins term | 0.42 x the running totals after seasons 3, 4, 5 (seasons weighted 3, 3, 3, 2, 1) | 1.02 x every season's own wins | 15 |
| Opponent draft | Opponent slots between a user pick and an unused later user pick are skipped | Opponents use every slot they own behind the user's window | 18 |
| End-state terms, penalty | Total assets 0.16, young 0.18, picks 0.16, cap room 0.35 (clamped -12..10), strength 0.28, depth 8, illegal move 2.5 | Unchanged | |

Everything else, including every random draw's schedule, is 1.0's. The
playoff games are still played and decide the champion; only the score
reads their expectation, which is unbiased because the playoff dice are
drawn after the ratings that set the odds.

Weights are fixed before any 2.1 model row: 1.02 is the per-season wins
weight that keeps `pick-trader`'s mean contribution from wins equal to
score-v1's on the canary seeds 11-34, measured before the draft fix and not
recalibrated after it.

## Identity

| | 2.0 | 2.1 |
|---|---|---|
| `benchmark_version` | `gm-bench-2.0` | `gm-bench-2.1` |
| `agentic_fingerprint` | `07de948a4f4afbae` | `282dbf382c4ee56c` |
| `parent_agentic_fingerprint` | | `07de948a4f4afbae` |
| `base_contract_fingerprint` (1.0) | `a600b7da0c302231` | `a600b7da0c302231` |
| `scoring_version` | `score-v1` (`05a60ff4f691e734`) | `score-v2` (`dfdb5369a60bebc3`) |
| `simulator_version` | `sim-v4` | `sim-v4-league21` |
| `tool_surface`, `brief` | `gm-bench-agentic-v1`, `gm-bench-agentic-brief-v1` | same |

The 2.1 fingerprint hashes the 2.0 fingerprint (and through it the 1.0
contract) plus `gm_bench/v21/{rules,scoring,runner,episode}.py`. No 1.0 or
2.0 contract source was edited, so both earlier fingerprints and every
published row are unchanged; `tests/test_v21.py` pins all three.

## Code

- `gm_bench/v21/rules.py`: `League21`, a `League` subclass carrying the
  three simulator fixes and recording each season's bracket odds.
- `gm_bench/v21/scoring.py`: score-v2 and its scale fingerprint.
- `gm_bench/v21/runner.py`: the 1.0 runner loop on `League21`, for the
  references and canaries.
- `gm_bench/v21/episode.py`: `AgenticEpisode21`, the frozen 2.0 engine on
  `League21`, scored with score-v2; its ledger header names
  `gm-bench-2.1`.
- `gm_bench/agentic/versions.py` (driver): resolves `--contract`, builds the
  matching engine and contract block, and replays a ledger with the engine
  its header names.

## Running and checking

```bash
gm-bench agentic --contract 2.1 --harness <h> --model <m> ...   # default stays 2.0
gm-bench agentic-validate <run dir>                               # checks each run under its own contract
gm-bench validate-contract --contract 2.1                         # canaries under the 2.1 rules (also in CI)
```

The private-panel launcher passes `--contract 2.1` through. The standalone
stdio MCP server (`python -m gm_bench.agentic.mcp_server`) is a 2.0
contract source and plays 2.0 only; every harness driver runs the engine
in process and honours `--contract`.

`agentic-validate` replays every episode with the engine its ledger names
and fails a run whose ledgers were played under a different contract than
its `run.json` records.

## Contract checks under 2.1

`validate-contract --contract 2.1`, seeds 11-34, 5 seasons: every asserted
ordering and mechanic-coverage check passes with 2.0's margins unchanged.

| Policy | Mean (2.1) |
|---|---|
| `pick-trader` | 252.6 |
| `strategic` | 248.8 |
| `shrewd` | 245.9 |
| `value` | 178.2 |
| canaries (exploit, pick-hoard, cap-hoard, accept-everything) | 118.3 to 138.9 |

Tightest gate: `value` over accept-everything on strategy score, 30.4
against 25.

## First paid round (pre-registered)

Approved by the operator 2026-10-15 for three models, which replaced the
four proposed earlier (`gpt-6-luna` and `claude-haiku-5-5` dropped,
`claude-sonnet-5-5` added). Committed at 15:36 on 2026-10-15
(`2a9c397`), before any 2.1 panel result was read; one Sonnet 5.5 episode
had finished 74 seconds earlier, unread.

- **Question.** Do the 2.1 rules keep the published picture: the same
  order of models and the same sign of each lift against `pick-trader`?
- **Models**, each paired with its own published 2.0 row:

  | Model (harness, pinned container version) | 2.0 row | 2.0 lift, score-v1 | 2.0 lift, score-v2 E (replayed) |
  |---|---|---|---|
  | `gpt-6.1-sol` (Codex 0.162.1) | `codex-0.162.1-gpt-6.1-sol-panel-32x5` | +24.0 | +26.8 |
  | `deepseek-v4.1-flash` (OpenCode 2.0.27, OpenCode Go) | `opencode-2.0.27-deepseek-v4.1-flash-panel-32x5` | -4.6 | -11.4 |
  | `claude-sonnet-5-5` (Claude Code 2.1.281) | `claude-2.1.281-claude-sonnet-5-5-panel-32x5` | -32.1 | -36.3 |

- **Seeds.** The 2.0 private panel (32 seeds, 5 seasons, same order), so
  each 2.1 episode pairs with the same seed's 2.0 episode. Container
  isolation through the private-panel launcher with `--contract 2.1`, from
  the clean merge commit `f8befed`.
- **How it ran.** One public-seed, one-season smoke per harness first (all
  three validated). The three panels then ran **concurrently**, one per
  provider, at the operator's request; each panel is still serial inside.
  That departs from the serial default, which exists to protect a single
  provider's rate limit; no two panels share a provider.
- **Analysis, fixed now** (`scripts/compare_v21_round.py`). For each model,
  the paired lift against `pick-trader` played under 2.1 on the same seeds,
  with sign-flip p and MDE. **Success:** the three 2.1 lifts keep the order
  sol > deepseek > sonnet-5-5 (Kendall tau = 1 against both 2.0 columns),
  and no lift whose 2.1 interval excludes zero has the opposite sign in
  2.0. Also reported: the change in each model's lift, its decisions failed,
  illegal moves and tool calls against its 2.0 row.
- **Not claimed.** These are not publishable rows (no 2.1 lane), and three
  models cannot validate a ranking of twelve.

### Result (2026-10-16): passed

All three panels finished 32/32 with no failed decision, and
`agentic-validate` passes each under 2.1. Lift against `pick-trader` played
under 2.1 on the same seeds
(`results/diagnostics/v21_round/round.json`):

| Model | 2.0, score-v1 | 2.0, score-v2 E (replayed) | **2.1** | 2.1 95% interval | Seeds ahead | Paired SD, v1 → E → 2.1 | 2.1 MDE |
|---|---|---|---|---|---|---|---|
| `gpt-6.1-sol` | +24.0 | +26.8 | **+19.1** | +10.3 to +28.0 | 24/32 | 65.0 → 31.2 → 25.6 | 12.7 |
| `deepseek-v4.1-flash` | -4.6 | -11.4 | **+1.2** | -8.2 to +10.5 | 21/32 | 61.0 → 40.9 → 27.0 | 13.4 |
| `claude-sonnet-5-5` | -32.1 | -36.3 | **-46.8** | -56.9 to -36.7 | 3/32 | 68.6 → 38.8 → 29.1 | 14.4 |

- **Success criterion met.** Kendall tau = 1 against both 2.0 columns, and
  no sign conflict against either. `round.json` names the raw run
  directories behind the published 2.0 rows in the table above (the
  DeepSeek row's is `...-panel-32x5-mcpwait`, Sonnet 5.5's
  `claude-sonnet-5-5-panel`).
- **Precision.** The paired SD falls to 26-29 for every model, so 32 seeds
  detect a lift of about 13 points (score-v1: about 32; score-v2 replayed
  on 2.0 games: about 15-20).
- **Each model's lift moved by less than its noise.** Against the score-v1
  2.0 lift: -4.9 (-27.9 to +18.1), +5.8 (-16.7 to +28.2), -14.7 (-36.7 to
  +7.4). Two models moved down and one up against the replayed E column;
  DeepSeek's two published 2.0 runs already differ by 8 points.
- **Play unchanged.** Failed decisions 0 in both contracts; illegal moves
  and tool calls per episode within a few percent of each model's 2.0 row.

**Exploratory, not pre-registered.** `gpt-6-luna` (Codex 0.162.1; its 2.0 row
used 0.156.1) was added at the operator's request after the round started
(`results/diagnostics/v21_round/gpt-6-luna_exploratory.json`): 2.1 lift
-7.6 (-16.6 to +1.4), 14/32 seeds ahead, paired SD 26.0. Same sign and
place as 2.0 (-21.8 score-v1, -15.9 replayed E), whose interval excluded
zero under E and does not here.

**Decision (operator, 2026-10-16):** release 2.1 as a lane on the same
32-seed private panel; these four runs become its first rows.

## Not yet done

- **No 2.1 lane.** `agentic-redact` refuses 2.1 rows: there is no frozen
  2.1 panel, reference pins or site section yet. A first paid round can
  reuse the 2.0 private panel (same 32 seeds) so each model's 2.1 run pairs
  seed by seed with its 2.0 row; a release panel should be larger
  ([score_deep_dive.md](score_deep_dive.md) section 4 suggests about 50
  seeds).
- **2.0 queue items 1-14** (tool-surface, brief and audit fixes) are not in
  2.1: each touches a 2.0 contract source the 2.1 engine reuses unchanged.
  They stay queued for a version that forks the tool surface or brief.
