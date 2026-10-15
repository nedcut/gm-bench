# Proposal: a score-v2 for the next contract

Draft, 2026-10-14. Not adopted: `score-v1` stays the scoring rule of every
published row and of both frozen contracts. This proposes a rule for the
next contract version, with the evidence for it, so the choice can be
pre-registered before any row is played under it.

Tool: `scripts/score_v2.py`. Results: `results/diagnostics/score_ceiling/
score_v2_baselines.json` and `score_v2_panels.json` (aggregates only).
Background: [score_ceiling.md](score_ceiling.md) and
[bench_v2_1_queue.md](bench_v2_1_queue.md) items 15 and 16.

## The proposal

Keep the simulator and every `score-v1` term and weight, with two changes:

1. **Expected playoffs.** Score `playoff_rounds` (last three seasons) and
   `championships` (all seasons) as their exact expectation given the
   bracket and the playoff ratings the simulator drew, instead of the
   single-game results. Weights unchanged (9 per round, 35 per title).
2. **Per-season recent wins.** Score the user's own wins in the last three
   seasons, not the sum of the running win totals after seasons 3, 4 and 5
   (records never reset, so `score-v1` weights seasons 3, 3, 3, 2, 1). The
   weight goes from 0.42 to **1.67**, chosen so `pick-trader`'s mean
   contribution from this term on the canary seeds 11-34 is unchanged (the
   ratio of its cumulative to per-season term there is 3.968).

This is candidate `C` in the tool. Both changes read only state the
simulator already produces, so neither changes a single game, trade or
draw. Both are scoring-contract changes and need a new scoring version and
fingerprint.

## Evidence

### Scripted references and canaries (seeds 11-34, the canary panel)

| | v1 | A: expected playoffs | C: proposal |
|---|---|---|---|
| `pick-trader` mean (across-seed SD) | 251.3 (42.3) | 258.2 (30.0) | 258.3 (32.3) |
| `strategic` | 256.6 | 249.9 | 249.0 |
| `shrewd` | 264.0 | 246.4 | 244.8 |
| `value` | 187.7 | 184.3 | 174.5 |
| `random` | 94.6 | 94.5 | 79.7 |
| Canaries (exploit, pick-hoard, cap-hoard, accept-everything) | 117.6 to 138.9 | 118.9 to 135.9 | 109.5 to 132.2 |
| Asserted orderings (`validate-contract`) | all pass | all pass | all pass |
| `pick-trader` - `value`, paired t | 8.9 | 18.7 | 19.1 |
| `pick-trader` - `strategic` (t) | -5.3 (-0.7) | +8.3 (2.3) | +9.4 (2.1) |
| `strategic` - `shrewd` (t) | -7.4 (-1.1) | +3.5 (1.8) | +4.1 (1.6) |
| `pick-trader` - `shrewd` (t, paired SD) | -12.7 (-1.1, 57.1) | +11.8 (3.2, 17.9) | +13.5 (3.2, 20.4) |

- Every ordering the contract asserts holds under both candidates, with
  paired t roughly doubled. Every canary still trails `value` by 42 points
  or more (the gate is 25).
- **The adjacent references resolve, and in the opposite order.**
  `validate-contract` keeps `pick-trader`, `strategic` and `shrewd`
  unasserted because they could not be separated. Under v1 on these seeds
  `shrewd` leads. With playoff dice removed the paired SD of
  `pick-trader` - `shrewd` falls from 57.1 to 17.9 and `pick-trader` leads
  by 11.8 (t 3.2): `shrewd`'s v1 lead here was title luck (it won 17.6
  points more from the playoffs than its brackets were worth). The
  expected-playoff score is unbiased for every policy, since the playoff
  dice are drawn after the ratings that set the odds.

### Published 2.0 panel rows (32 private seeds, replayed, no model calls)

All eleven published panel rows. Lift is paired against `pick-trader` on
the same seed; MDE is the paired difference detectable at 80% power,
two-sided 5%.

| Row | v1 lift (p, MDE) | A lift (p, MDE) | C lift (p, MDE) |
|---|---|---|---|
| Codex `gpt-6-astra` | +39.2 (0.0033, 34.5) | +43.4 (<0.0001, 16.1) | +44.0 (<0.0001, 16.9) |
| Codex `gpt-6.1-sol` | +24.0 (0.0475, 32.2) | +26.9 (<0.0001, 15.7) | +26.8 (0.0002, 16.2) |
| Codex `gpt-6-luna` | -21.8 (0.0620, 31.4) | -16.3 (0.0043, 14.7) | -15.0 (0.0060, 14.2) |
| OpenCode 1.18.31 `deepseek-v4.1-flash` | -2.0 (0.847, 29.3) | -3.4 (0.606, 18.0) | -3.4 (0.585, 17.4) |
| OpenCode 2.0.27 `deepseek-v4.1-flash` | -4.6 (0.671, 30.2) | -11.2 (0.14, 20.7) | -12.2 (0.112, 21.0) |
| Cursor `composer-2.5` | -18.6 (0.0441, 25.1) | -18.0 (0.0019, 14.9) | -16.4 (0.0093, 16.5) |
| Claude Code `claude-sonnet-5` | -21.8 (0.111, 36.9) | -14.9 (0.0648, 21.8) | -14.0 (0.0910, 22.5) |
| Claude Code `claude-sonnet-5-5` | -32.1 (0.0126, 34.0) | -36.5 (<0.0001, 19.6) | -35.5 (<0.0001, 19.8) |
| Claude Code `claude-opus-5-5` | -46.7 (0.0009, 34.6) | -35.5 (<0.0001, 19.9) | -34.6 (<0.0001, 20.3) |
| Claude Code `claude-haiku-5-5` | -46.5 (0.0002, 29.9) | -60.2 (<0.0001, 18.3) | -58.8 (<0.0001, 18.4) |
| Claude Code `claude-haiku-4-5` | -119.1 (<0.0001, 20.5) | -119.5 (<0.0001, 19.3) | -124.5 (<0.0001, 21.0) |
| Mean MDE | 30.8 | 18.1 | 18.6 |

No row changes direction. Under a Holm correction across the eleven rows, 4
differ from `pick-trader` under v1 and 8 under C (and A): `gpt-6.1-sol`,
`gpt-6-luna`, `composer-2.5` and `claude-sonnet-5-5` resolve. The three
still unresolved are `claude-sonnet-5` and both `deepseek-v4.1-flash` rows.

## Options considered

- **A alone** (expected playoffs, keep v1's recent-wins term). Same
  sensitivity as C, but keeps a term that weights early seasons three times
  as much as the last one while calling itself "recent".
- **B** (C at v1's 0.42 weight). Lower MDE in points (15.9), but only
  because it shrinks every score by about 70 points: relative to the
  `pick-trader` - `value` gap it is no more sensitive than C, and it moves
  the balance between winning and asset building, which `score-v1`'s
  weights were calibrated for (`docs/scoring_calibration.md`).
- **D** (C with expected regular-season wins). No measurable gain over C
  (mean MDE 18.1 against 18.6), and it would stop rewarding wins the team
  actually earned. Regular-season dice are not where the noise is.
- **Best-of series in the simulator.** Would also cut playoff variance, but
  changes the simulation, so every existing row would have to be played
  again. C can be computed exactly from any recorded episode.

## What adopting it involves

- A new scoring version (`score-v2`) with its own scale fingerprint, the
  expected-playoff bookkeeping in the simulator (record the bracket odds at
  the playoffs; the hook in `scripts/score_v2.py` is the reference), the
  per-season wins term, and recalibrated `validate-contract` margins.
- **Existing evidence can be rescored without any model run.** Every 2.0
  ledger replays exactly, so each published row could carry a `score-v2`
  figure next to its `score-v1` one, as a separately labelled column.
  All eleven published 2.0 panel rows have been replayed this way. 1.0
  rows would need their raw private-panel artifacts.
- **What it does not fix.** Records still never reset in the simulation,
  so playoff qualification and seeding, the lottery order and the
  free-agent win signal still read running totals (queue item 15). That
  half needs a simulator change and therefore new runs; it is better
  bundled with the next contract's panels than run on its own.
- **This was chosen after seeing the data.** The 1.67 weight is calibrated
  on public canary seeds and the comparison used published rows, so it has
  to be pre-registered for the next contract, not applied to change any
  published result.
