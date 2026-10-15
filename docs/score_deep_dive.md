# Stress-testing the score-v2 proposal

Diagnostic, 2026-10-15. Nothing here changes a published row or a frozen
contract. It tests the candidate in [score_v2_proposal.md](score_v2_proposal.md)
(`C`: expected playoffs plus per-season recent wins) before it is
pre-registered, using only local CPU: no model was called. Tool:
`scripts/score_deep_dive.py`. Results: `results/diagnostics/score_deep_dive/`
(aggregates only for the private panels; public seeds otherwise).

The published rows are the twelve 2.0 panel rows (32 private seeds each,
replayed from their ledgers); the scripted policies play public seeds.
"Lift" is paired against `pick-trader` on the same seed.

## Summary

- **Most models out-win `pick-trader`; they lose on what they leave behind.**
  Nine of twelve rows gain on the winning terms (wins, expected playoffs,
  expected titles). Every row loses on the end-state terms, mostly young
  players' asset value. Opus 5.5: winning +37, end state -67.
- **The end-state terms are worth what they claim.** Handing every final
  league to the same scripted manager for five more seasons on the same
  dice, one point of C's end-state score predicts 1.0 point of later
  winning value (slope 1.01 +/- 0.06; 0.95 +/- 0.05 with a different
  manager). The models' asset deficits turn into real future losses.
- **Model order is robust; "beats `pick-trader`" is not.** Halving or
  raising any weight by half never reorders the rows much (Kendall tau
  0.88 or more) and never flips a sign except on rows within 5 points of
  zero. But `pick-trader` leaves about 20 to 35 points of future value
  that no end-state term captures, so valuing the end state by simulation
  instead shifts every row down: `gpt-6-astra`'s +44 becomes about +5.
- **Most of the remaining noise is still dice**, now development, injury,
  market and lottery draws rather than playoff games: 60 to 90% of the
  paired spread between scripted policies under C.
- **The fair planner finds no exploit in C or E.** Optimizing either
  directly, it gains +27 to +29 over `pick-trader` by winning more and
  keeping more assets; it does not tank the two seasons C's wins term
  ignores.
- **Fixing the records bug (queue item 15) leaves C's checks intact.** With
  records reset each season, C passes every asserted ordering on 24 and 96
  public seeds and keeps `pick-trader` > `strategic` > `shrewd`.
- **A small variant, E, is at least as good as C.** Counting every season's
  own wins (weight 1.02) instead of the last three seasons' (1.67) gives
  the same row order and separability, a slightly smaller detectable
  difference (17.9 against 18.3 points) and no season the score ignores.

## 1. Where the lifts come from

Lift under C split into its winning terms (recent wins, expected playoff
rounds, expected titles) and its end-state terms (assets, young assets,
future picks, cap room, current strength, roster depth). `panels.json`.

| Row | C lift | Winning | End state | of which young assets | Extra wins per season (1 to 5) |
|---|---|---|---|---|---|
| Codex `gpt-6-astra` | +44.0 | +67.4 | -18.8 | -20.4 | +3.1 +3.5 +3.5 +5.0 +2.6 |
| Codex `gpt-6.1-sol` | +26.8 | +51.8 | -18.7 | -20.2 | +3.2 +2.0 +2.6 +3.8 +1.8 |
| OpenCode 2.0.27 `muse-spark-1.3` | -0.3 | +11.5 | -11.7 | -9.8 | +1.0 -0.5 +0.4 +1.6 +0.4 |
| OpenCode 1.18.31 `deepseek-v4.1-flash` | -3.4 | +20.3 | -21.0 | -13.9 | +1.6 +0.6 +0.7 +2.0 +0.6 |
| OpenCode 2.0.27 `deepseek-v4.1-flash` | -12.2 | +10.1 | -19.7 | -13.0 | +1.3 +0.2 +0.1 +1.2 -0.1 |
| Claude Code `claude-sonnet-5` | -14.0 | +14.8 | -26.9 | -14.1 | +0.8 0.0 +0.2 +1.9 +0.2 |
| Codex `gpt-6-luna` | -15.0 | -7.4 | -6.1 | -8.7 | -0.2 -1.7 -1.1 +0.2 -0.6 |
| Cursor `composer-2.5` | -16.4 | -5.1 | -7.1 | -8.5 | -0.4 -1.8 -1.1 +1.0 -1.2 |
| Claude Code `claude-opus-5-5` | -34.6 | +37.1 | -67.1 | -30.5 | +1.6 +1.2 +2.2 +2.7 +1.0 |
| Claude Code `claude-sonnet-5-5` | -35.5 | +9.0 | -41.6 | -17.9 | +0.7 -0.6 +0.2 +1.3 0.0 |
| Claude Code `claude-haiku-5-5` | -58.8 | +5.0 | -60.3 | -25.0 | +0.7 -1.1 -0.4 +1.3 0.0 |
| Claude Code `claude-haiku-4-5` | -124.5 | -40.8 | -79.2 | -30.5 | -1.0 -3.3 -2.6 -2.2 -6.0 |

(The protocol penalty, -0.1 to -6.3, makes up the rest.) The pattern is a
trade of future for present: the Claude rows in particular spend young
players and asset value to win now. This also settles a question from the
ceiling work: `gpt-6-astra` beats the fair planner and the clairvoyant
search by winning games (three to five more a season), not through an
end-state accounting quirk.

## 2. Are the end-state terms worth what they claim?

The end-state terms stand in for the franchise's future. To check that,
`continuation` hands each final league, the model's and `pick-trader`'s on
the same seed, to one scripted manager for five more seasons and scores
the winning value that follows with C's own weights (per-season wins,
expected playoff rounds, expected titles). Both leagues continue under the
same dice, since the simulator draws them on a fixed schedule, and no
scripted policy reads the episode length. Pooled over the 384 published
episodes and 192 scripted ones (seven policies and the canaries on seeds
11-34):

| Manager | Slope, next 3 seasons | Slope, next 5 seasons | Intercept, next 5 |
|---|---|---|---|
| `pick-trader` | 0.67 (0.03) | **1.01 (0.06)** | -35.3 (3.0) |
| `strategic` | 0.66 (0.03) | **0.95 (0.05)** | -34.2 (2.7) |

(Pair-bootstrap standard errors.) One point of C's end-state score is worth
about one point of winning value over the next five seasons. The rows bear
it out one by one: Sonnet 5.5's end-state gap of -41.6 becomes -42.8 over
the next three seasons and -73.0 over five; Haiku 4.5's -79.2 becomes -74.9
and -116.6.

The intercept is the open problem. At equal end-state score, every other
team still does about 35 points worse than `pick-trader`'s over five
seasons, and the gap does not depend on who manages the continuation, so
it is not `pick-trader` running its own roster better. It is roughly the
same for every model row (residuals -28 to -44). Two explanations were
checked and ruled out, in quick exploratory runs not kept in the tool:
future picks (raising their weight sixfold barely
moves `pick-trader` - `strategic`, the pair that differs only in pick
trading) and hidden potential (valuing assets at true rather than public
potential moves the scripted gaps by 1 to 6 points). Whatever it is,
`pick-trader` leaves it and C does not see it.

Scoring the end state by simulation instead ("F": C's winning terms plus
the continuation's winning value) keeps the row order but is noisier and
moves every row:

| Score | Rows separable from `pick-trader` (Holm) | Mean MDE | Kendall tau vs C | `gpt-6-astra` lift |
|---|---|---|---|---|
| C | 8 | 18.3 | 1.00 | +44.0 |
| F, next 3 seasons | 7 | 24.4 | 0.91 | +40.3 |
| F, next 5 seasons | 10 | 30.7 | 1.00 | +4.5 |

(`pick-trader` manager; `strategic` gives the same picture.) The order of
the rows is not in question under any of these. Whether a given model
"beats `pick-trader`" depends on how far ahead the franchise is valued, and
publication should say so.

The regression also prices the end-state terms one by one, with wide
error bars: young players' asset value carries the signal (0.34 per point
of young assets over five seasons, which is what C pays in total for a
young player: 0.16 + 0.18), while veterans' asset value predicts almost
nothing (0.01 to 0.03 against C's 0.16).

## 3. How much do the exact weights matter?

Each of C's nine weights halved and raised by half, on the twelve rows
(`panels.json`, `robustness`):

- Row order: Kendall tau against C between 0.88 and 1.00 for all 18
  perturbations.
- Signs: no row changes direction except `muse-spark-1.3` (-0.3) and the
  1.18.31 `deepseek-v4.1-flash` row (-3.4), both within noise of zero.
- Separability: 8 rows under C, between 5 and 8 under the perturbations.
  The sensitive weights are young assets (halving it leaves `gpt-6-luna`,
  `composer-2.5` and `claude-opus-5-5` unseparated), total assets,
  playoff rounds and championships. Section 2 supports the current young
  asset weight.

So refining weights would move borderline significance calls, not the
picture. A few rows' verdicts rest on how young talent is valued, which
the continuation evidence supports as it stands.

## 4. What noise is left

`noise` keeps each seed's initial league and redraws every later random
draw (games, playoffs, development, injuries, market prices, draft
classes, lottery) four times, then splits the paired spread between a
scripted policy and `pick-trader` into dice and world. Seeds 11-34:

| Pair | Paired SD v1 | Paired SD C | Dice share under C | Paired SD E |
|---|---|---|---|---|
| `value` - `pick-trader` | 34.9 | 21.5 | 0.90 | 19.6 |
| `shrewd` - `pick-trader` | 57.1 | 20.4 | 0.74 | 18.6 |
| `strategic` - `pick-trader` | 37.8 | 21.8 | 0.62 | 18.9 |

Most of what C leaves is still dice, but not game dice: expected
regular-season wins (`D`) barely changes the spread. The remaining draws
(development, injuries, prices, draft classes) cannot be integrated out in
closed form the way the playoff bracket can. More seeds is the lever: at
C's mean MDE of 18.3 on 32 seeds, a 15-point difference needs about 48
seeds and a 10-point difference about 107.

## 5. Can C be gamed?

The concern: C drops wins in seasons 1 and 2 from the score (titles still
count), so a policy could sell early and buy late. `exploit` runs the fair
planner from the ceiling work (6 sampled hidden worlds per decision,
generated single moves, the 1.5-se switching rule) with C as its objective
on public seeds 101-124:

- Lift under C: **+27.1 (se 4.8)**, ahead on 22 of 24 seeds; +43.1 under
  v1 and +25.0 under E, so the gain is not specific to C.
- Where it comes from: recent wins +6.4, expected playoff rounds +5.5,
  expected titles +6.6, total assets +4.9, young assets +3.0. Expected
  titles per five seasons 0.68 against 0.49.
- No tanking: wins per season against `pick-trader` +0.1, +0.3, +1.0,
  +1.3, +1.5. It wins slightly more in the two seasons C ignores.

The planner makes one move per window from a short menu, so a multi-step
exploit could still exist, but the canaries (section 6) and this search
both find C rewarding winning and asset building together.

## 6. The records fix

`reset` installs a hook that zeroes every team's record when each season
opens (`docs/bench_v2_1_queue.md` item 15), which changes the simulation:
playoff seeding, the lottery order and the free-agent win signal now read
the season's own record. References and canaries, then the contract's
checks:

| Seeds | Records | C: asserted orderings | `pick-trader` - `strategic` (t) | `strategic` - `shrewd` (t) | `pick-trader` - `shrewd` (t) |
|---|---|---|---|---|---|
| 11-34 | current | all pass | +9.4 (2.1) | +4.1 (1.6) | +13.5 (3.2) |
| 11-34 | reset | all pass | +8.4 (2.1) | +3.1 (1.1) | +11.5 (2.6) |
| 35-130 | current | all pass | +8.8 (4.9) | +2.4 (1.8) | +11.2 (5.5) |
| 35-130 | reset | all pass | +5.0 (2.6) | +5.0 (3.2) | +10.1 (4.7) |

Every canary still trails `value` by more than the 25-point gate under C
and E with records reset, and `pick-trader`'s mean barely moves (258.3 to
256.0 on 11-34, 252.7 to 257.6 on 35-130). The fix can ship with the next
contract without recalibrating C.

## 7. Candidate E: every season's wins

C counts wins in seasons 3 to 5 only. E counts every season's own wins at
1.02, the weight that keeps `pick-trader`'s mean contribution equal (its
recent-to-all wins ratio is 0.609 on seeds 11-34). Against C:

| | C | E |
|---|---|---|
| Rows separable (Holm, 12 rows) | 8 | 8 |
| Mean MDE | 18.3 | 17.9 |
| Kendall tau vs C | 1.00 | 1.00 |
| `pick-trader` across-seed SD (11-34 / 35-130) | 32.4 / 27.2 | 30.6 / 25.8 |
| Asserted orderings, current and reset records | all pass | all pass |
| Seasons whose wins do not count | 1 and 2 | none |

The exploit search with E as the objective (same settings, seeds 101-124)
gains +29.1 (se 4.4) under E, ahead on 21 of 24 seeds, again by winning
more in every season (+0.6, +0.5, +1.5, +1.6, +1.8 wins against
`pick-trader`) and keeping more assets (total +5.5, young +3.4 under C's
weights); expected titles 0.70 against 0.49.

## What this changes

- **Keep the proposal's direction.** Expected playoffs and per-season wins
  survive every test here: the end-state terms are calibrated in aggregate,
  the weights are not fragile, the planner finds no exploit, and the
  records fix does not disturb them.
- **Prefer E over C** for pre-registration: equal or better on every
  measure and no season the score ignores.
- **Fix the records bug in the same contract.** It does not disturb the
  scoring, and C and E were checked against it.
- **Publish model order with a horizon caveat.** The rows' order holds
  under every valuation tried; the sign of a row's lift against
  `pick-trader` can depend on how far ahead the end state is valued.
- **Open question**: the ~35 points of future value `pick-trader` leaves
  that no end-state term sees. Until it is found, a row's lift against
  `pick-trader` under C or E likely flatters the model by roughly that
  much over a five-season view.
- **No paid run is needed for any of this.** A rerun becomes informative
  only once a contract with the records fix exists; its seed count should
  be set from section 4.

## Reproducing

Local CPU. The panel and continuation commands need the raw run
directories (private seeds) and cache per-episode vectors under
`~/.cache/gm-bench-deep-dive` (mode 0700); nothing seed-level is written
to the repository.

```bash
python scripts/score_deep_dive.py panels <run dirs> --out panels.json
python scripts/score_deep_dive.py continuation <run dirs> --seeds 11-34 --manager pick-trader --out continuation_pick-trader.json
python scripts/score_deep_dive.py continuation <run dirs> --seeds 11-34 --manager strategic --out continuation_strategic.json
python scripts/score_deep_dive.py noise --seeds 11-34 --draws 4 --out noise_11_34.json
python scripts/score_deep_dive.py reset --seeds 11-34 --out reset_11_34.json
python scripts/score_deep_dive.py reset --seeds 35-130 --out reset_35_130.json
python scripts/score_deep_dive.py exploit --seeds 101-124 --objective C --out exploit_C_101_124.json
python scripts/score_deep_dive.py exploit --seeds 101-124 --objective E --out exploit_E_101_124.json
```

The two exploit runs take about 30 minutes each on 12 cores; the rest
take minutes.
