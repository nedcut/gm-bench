# How much headroom is left above `pick-trader`?

Diagnostic, recorded 2026-10-14. Nothing here is an official baseline, a
contract change, or a submission. The tool is `scripts/ceiling_search.py`;
per-seed results, including each search's chosen move path, are in
`results/diagnostics/score_ceiling/`.

**Update, 2026-10-26:** the searches were rerun under the current contract
(GM-Bench 2.1 rules, score-v2); see [the 2.1 section](#2026-10-26-rerun-under-gm-bench-21-and-score-v2)
at the end. Everything between here and that section is the 2026-10-14
measurement under 1.0 and is left as recorded.

Every number below is on public seeds 101-124, five seasons, the current
1.0 simulator and `score-v1`. Lifts are paired against `pick-trader` on the
same seed (`pick-trader` mean 232.2 on these seeds; se is the standard error
of the paired lift).

## Question

The models published so far land around 200 to 273, and the best scripted
reference, `pick-trader`, sits near 247 on the panels. Is that close to the
best achievable score, or is there room above it for a benchmark to measure?

For one seed the simulator is a deterministic function of the 20 decisions:
every random draw (games, injuries, development, lottery, reservation prices,
partner valuations) comes from streams keyed by the seed and the schedule,
not by what the GM does. So a per-seed optimum exists. It cannot be
enumerated, so this diagnostic brackets it from below with search.

## Method

Two searches, both choosing at each of the 20 decision windows from a menu
of moves and scoring each move by playing the rest of the episode with
`pick-trader`:

- **Hindsight** (beam width 4) plays every move on a copy of the real league,
  so it sees the dice before it commits. It is clairvoyant, not a fair
  agent.
- **Fair** (6 sampled worlds per decision) never reads the seed or any hidden
  value. Before scoring moves it redraws everything a GM cannot observe: the
  seed (future dice, reservation prices, partner valuation bias, scout
  noise, future draft classes), every player's latent potential (from a
  posterior on the public potential or the scout report), and current
  injuries. It leaves `pick-trader`'s move only when another move's gain,
  paired world by world, clears 1.5 standard errors. A test checks that two
  leagues with the same public state but different hidden state produce
  identical sampled worlds.

The menu: eight public scripted policies, `pick-trader` with one action
family suppressed, and (fair `--generated` only) single moves built from the
public observation (sign one of the top free agents at the published quote,
buy a listed player for picks, sell a veteran for a pick, accept an incoming
offer, claim a waiver, release the weakest player), after which
`pick-trader` finishes the window. Hindsight also gets `oracle`.

**Luck-neutral score.** The playoffs are single games, and playoff rounds
plus championships are worth up to 81 + 175 points. The tool records, at
each season's playoffs, the user team's exact expected rounds won and title
probability given the ratings the simulator used, and the luck-neutral score
swaps the realized playoff terms for those expectations. Over seeds 101-160
`pick-trader` averages 245.4 realized and 249.2 luck-neutral (difference
-3.9 +/- 4.2, so no bias), and the across-seed SD falls from 42.3 to 25.5:
**about 64% of score variance is playoff dice.**

## Results

| Search | Real score | Real lift (se) | Luck-neutral lift (se) | Seeds ahead (luck-neutral) |
|---|---|---|---|---|
| Hindsight, realized objective | 362.0 | +129.8 (8.8) | n/a | 24 / 24 (real) |
| Hindsight, luck-neutral objective | 280.9 | +48.7 (9.5) | **+41.2 (3.4)** | 24 / 24 |
| Fair, scripted menu only | 244.1 | +11.9 (7.6) | n/a | 12 / 24 (real) |
| Fair, with generated moves | 255.3 | +23.2 (7.1) | **+26.2 (4.2)** | 22 / 24 |

(The two runs without a luck-neutral column predate the luck-neutral
objective; the scripted-only fair run used the realized score in its
rollouts and 8 worlds.)

**Replication on fresh seeds 125-172** (48 seeds, after every setting
above was fixed; `fair_generated_125_172.json`): the fair planner with
generated moves beats `pick-trader` by **+25.4 luck-neutral (se 3.2),
ahead on 44 of 48 seeds** (+31.9 real, se 8.8), and expected titles per
five seasons rise from 0.68 to 0.88. The 1.5-se switching rule tuned on
seeds 101-104 did not inflate the first estimate.

What the rows say:

1. **Seeing the dice is worth about 130 points, and almost all of it is the
   playoffs.** Of the realized-objective hindsight lift, 128 points are
   playoff rounds and championships; regular-season wins add 1.4 and team
   strength 0.2. The search reshuffles the roster to flip single-game
   playoff coin flips it can see coming (2 to 4 titles per seed, against
   `pick-trader`'s 0 to 1).
2. **Without playoff luck, clairvoyance is worth about 41 points.** That is
   what knowing the regular-season dice, development rolls and hidden
   prices buys, plus whatever the menu itself allows.
3. **A fair planner gets about 26 of those 41.** With generated moves it
   beats `pick-trader` on 22 of 24 seeds in luck-neutral terms. The gain is
   spread across components (wins +4.4, playoff +10.0, assets +8.7, depth
   +1.2) and comes mostly from extra free-agent signings (104 of 480
   windows), veteran sales and releases; it still keeps `pick-trader`'s
   own move in 197 windows. Expected titles per five seasons rise from 0.49
   to 0.70.
4. **The scripted policies alone are close to a local optimum.** Choosing
   only among them gained 11.9 (se 7.6), not separable from zero.

So, under the current contract: `pick-trader` is about 25 points below what
a public-information planner reaches with a modest move menu, and that
planner is itself a lower bound. Real headroom exists above `pick-trader`,
roughly the size of the panel's minimum detectable difference (about 30
points on 32 seeds), and most of the remaining spread between seeds is
playoff luck no agent controls.

## Rescoring the published 2.0 rows

`scripts/score_v2.py panels` replays each episode ledger of a raw 2.0
panel run through the frozen engine (the replay `agentic-validate` does),
records the expected playoff outcome each season, and plays `pick-trader`
on the same private seed. No model is called. Every replay reproduced its
recorded score and every row's published mean and `pick-trader` mean
(249.18). The luck-neutral columns below are its candidate `A`; aggregates
only (no seeds, no per-episode scores) are in
`results/diagnostics/score_ceiling/score_v2_panels.json`. The candidate
scoring rule these results led to is in
[score_v2_proposal.md](score_v2_proposal.md).

All eleven published panel rows were rescored (five from raw run
directories copied from the machine that played them). The 1.0 rows were
not: their committed artifacts are compact and the raw private-panel
artifacts were not available.

| Row (32 private seeds) | Real lift vs `pick-trader` (se) | p | MDE | Luck-neutral lift (se) | p | MDE |
|---|---|---|---|---|---|---|
| Codex `gpt-6-astra` | +39.2 (12.3) | 0.0033 | 34.5 | +43.4 (5.8) | <0.0001 | 16.1 |
| Codex `gpt-6.1-sol` | +24.0 (11.5) | 0.0475 | 32.2 | +26.9 (5.6) | <0.0001 | 15.7 |
| Codex `gpt-6-luna` | -21.8 (11.2) | 0.0620 | 31.4 | -16.3 (5.2) | 0.0043 | 14.7 |
| OpenCode 1.18.31 `deepseek-v4.1-flash` | -2.0 (10.5) | 0.847 | 29.3 | -3.4 (6.4) | 0.606 | 18.0 |
| OpenCode 2.0.27 `deepseek-v4.1-flash` | -4.6 (10.8) | 0.671 | 30.2 | -11.2 (7.4) | 0.14 | 20.7 |
| Cursor `composer-2.5` | -18.6 (9.0) | 0.0441 | 25.1 | -18.0 (5.3) | 0.0019 | 14.9 |
| Claude Code `claude-sonnet-5` | -21.8 (13.2) | 0.111 | 36.9 | -14.9 (7.8) | 0.0648 | 21.8 |
| Claude Code `claude-sonnet-5-5` | -32.1 (12.1) | 0.0126 | 34.0 | -36.5 (7.0) | <0.0001 | 19.6 |
| Claude Code `claude-opus-5-5` | -46.7 (12.4) | 0.0009 | 34.6 | -35.5 (7.1) | <0.0001 | 19.9 |
| Claude Code `claude-haiku-5-5` | -46.5 (10.7) | 0.0002 | 29.9 | -60.2 (6.5) | <0.0001 | 18.3 |
| Claude Code `claude-haiku-4-5` | -119.1 (7.3) | <0.0001 | 20.5 | -119.5 (6.9) | <0.0001 | 19.3 |

MDE is the paired difference detectable at 80% power and two-sided 5%
(normal approximation). p is the runner's two-sided sign-flip test, which
samples 20,000 flips at 32 seeds, so "<0.0001" means no sampled flip
reached the observed mean.

- **The panel gets about 40% more sensitive.** Mean MDE across the eleven
  rows falls from 30.8 to 18.1 points with no new runs: the same 32 seeds
  measure about what 90 would under the realized score.
- **No row changes direction, and most borderline calls resolve.** Under a
  Holm correction across the eleven rows, 4 differ from `pick-trader` on
  the realized score and 8 luck-neutral. The four newly resolved are
  `gpt-6.1-sol` (ahead), and `gpt-6-luna`, `composer-2.5` and
  `claude-sonnet-5-5` (behind). The three still "can't tell" are
  `claude-sonnet-5` (-14.9, interval -30.2 to +0.3) and both DeepSeek rows,
  whose intervals narrow to about -16 to +9 (1.18.31) and -26 to +3
  (2.0.27).
- **Playoff luck moved individual rows by up to 14 points.** `haiku-5-5`
  won 26 titles against 18.0 expected and its gap widens from -46.5 to
  -60.2; `opus-5-5` won 23 against 30.2 expected and its gap narrows from
  -46.7 to -35.5. Realized, Opus trails Sonnet 5.5 by 14.6 points;
  luck-neutral the two are level (213.0 and 212.0). The 2.0 lane publishes
  no model-to-model ranking, but this is the kind of ordering the playoff
  dice decide.

Because the luck-neutral score changes no simulation, only the scoring, it
could be adopted for existing ledgers without re-running any model. That is
still a scoring-contract change, and it was chosen after seeing these
results, so it belongs in the next contract, pre-registered, not applied to
published rows.

## Caveats

- **The fair planner uses the simulator as its model.** It knows the rules
  and opponents' code exactly and only resamples hidden values. That is
  public information in principle (the code is open), but no model under
  test gets to run thousands of simulated rollouts per decision, so this is
  a ceiling reference, not a fair comparison row.
- Both searches are lower bounds on their respective optima: one move per
  window from a short menu, `pick-trader` rollouts, beam 4, 6 worlds, one
  planner seed. The latent-potential posterior uses one pooled prior.
- The realized-objective hindsight run and the scripted-only fair run used
  an earlier menu in which the "no offer accepts" variant filtered the
  wrong action name and so duplicated `pick-trader`; the later runs use the
  fixed menu.
- The 1.5-se switching rule was picked after a 4-seed trial on seeds
  101-104, inside the first 24-seed set; the 48-seed replication on
  125-172 is clear of it.
- Under the wins-never-reset bug (`docs/bench_v2_1_queue.md` item 15) the
  `recent_wins` term weights early seasons most, which these searches
  optimize like any other term. A fixed contract would move every number
  here.

## Reproducing

Local CPU only (no model calls). Each line takes about 15 to 40 minutes
on 12 cores.

```bash
python scripts/ceiling_search.py hindsight --seeds 101-124 --beam 4 --jobs 6 --out hindsight.json
python scripts/ceiling_search.py hindsight --luck-neutral --seeds 101-124 --beam 4 --jobs 6 --out hindsight_neutral.json
python scripts/ceiling_search.py fair --seeds 101-124 --worlds 8 --jobs 12 --out fair.json
python scripts/ceiling_search.py fair --generated --seeds 101-124 --worlds 6 --jobs 12 --out fair_generated.json
```

The scripted-only fair row above was produced before the fair rollouts
switched to the luck-neutral objective, so rerunning the third line now
gives a luck-neutral-objective version of it.

## 2026-10-26: rerun under GM-Bench 2.1 and score-v2

The table above was measured on the 1.0 simulator under score-v1. The
published 2.1 rows are played on `League21` (records reset each season,
the opponent-draft fix) and scored with score-v2, and the top one,
`gpt-6-astra`, is +46.9 over `pick-trader`: above both old bounds. The
seeds and rules differed, so the comparison was not clean. This rerun
plays both searches under the 2.1 rules and scores them with score-v2
(`scripts/ceiling_search.py --contract 2.1`), on public seeds only, with
every other setting as in the 1.0 rows: fair planner with generated moves,
6 worlds, 1.5-se switching rule, planner seed 0; hindsight beam 4. Files:
`v21_fair_generated.json`, `v21_hindsight.json` and
`v21_fair_generated_125_172.json` in `results/diagnostics/score_ceiling/`.

### Luck-neutral and score-v2

Under 2.1 there is no separate luck-neutral objective, because score-v2
already is one. Its two playoff terms are the 1.0 luck-neutral terms: the
same exact bracket odds (`League21` records them with a function equal to
the tool's; a test asserts the two agree), the same weights (9 a round, 35
a title) and the same windows (rounds over the last three seasons, titles
over all five). Only the wins term differs (every season's own wins at
1.02, against 0.42 times the running totals), and the 2.1 simulator
differs. So the 2.1 hindsight search optimizing score-v2 is the analogue
of the 1.0 `--luck-neutral` hindsight row, and the fair planner's rollout
objective is score-v2 itself. On seeds 101-124 `pick-trader` scores 243.3
luck-neutral under 1.0 and 249.1 under 2.1, with 0.49 and 0.51 expected
titles per five seasons. The "realized playoffs" column below puts the
single-game playoff results back into score-v2. It moves each lift by a few
points with a standard error two to four times larger, as the 1.0 "real"
column did.

### Results

Lifts are paired against `pick-trader` played under 2.1 on the same seed;
se is the standard error of the paired lift.

| Search (2.1, score-v2) | Seeds | `pick-trader` mean | Search mean | Lift (se) | Seeds ahead | Lift, realized playoffs (se) | 1.0 counterpart, luck-neutral |
|---|---|---|---|---|---|---|---|
| Hindsight (clairvoyant), beam 4 | 101-124 | 249.1 | 282.2 | **+33.1 (2.7)** | 24 / 24 | +22.1 (11.2) | +41.2 (3.4) |
| Fair, with generated moves | 101-124 | 249.1 | 269.2 | **+20.1 (4.1)** | 20 / 24 | +23.8 (9.3) | +26.2 (4.2) |
| Fair, with generated moves | 125-172 | 250.8 | 273.9 | **+23.1 (2.9)** | 43 / 48 | +33.5 (8.2) | +25.4 (3.2) |

Next to them, the published 2.1 rows (`results/agentic_v21/*.json`,
`reference` block; se = paired SD / sqrt(32)). **These are on the 32-seed
private panel, not on these public seeds,** so the comparison is between
seed sets, not paired. `pick-trader` averages 249.6 on the panel against
249.1 and 250.8 on the two public sets.

| Published 2.1 row (private panel) | Lift (se) | Seeds ahead |
|---|---|---|
| Codex `gpt-6-astra` | +46.9 (5.2) | 32 / 32 |
| OpenCode `minimax-m3.1-flash-free` | +23.0 (5.6) | 25 / 32 |
| OpenCode `mimo-v2.6-pro` | +20.7 (6.0) | 25 / 32 |
| Codex `gpt-6.1-sol` | +19.1 (4.4) | 24 / 32 |
| OpenCode `mimo-v2.6-flash` | +18.7 (6.1) | 24 / 32 |
| The other seven rows | -53.1 to +1.9 | 2 to 21 / 32 |

### What the numbers say

1. **Astra's +46.9 is above both bounds.** It is 27 points above the
   fair planner (+20.1 on the same seed range, +23.1 on 48 fresh seeds)
   and 14 points above the clairvoyant search (+33.1). The second gap is
   about 2.3 standard errors if the two seed sets are treated as
   independent samples. Four more rows (+18.7 to +23.0) land at the fair
   planner's level.
2. **So the searches are weak lower bounds, not a ceiling.** The
   hindsight search sees the dice, yet a model that plays fair and can't
   see them beats it on every one of its 32 seeds. The search is bounded
   by its move menu, not by information. These numbers don't show the top
   of the scale near saturation. The best measured result is +47, and
   nothing here bounds the reachable score from above.
3. **The gap is winning games.** Astra's row averages 106.3 wins and 1.38
   titles per five-season game. On the public seeds `pick-trader` wins
   85.0 (101-124) and 87.4 (125-172) with 0.51 and 0.59 expected titles.
   That gap of about 20 wins is worth about 20 points from the wins term
   alone, before the playoff value of a stronger team. The searches add
   only 4.4 (fair), 5.3 (fair, 125-172) and 6.9 (hindsight) wins per game.
   Their lifts are spread across terms. Fair: wins +4.5, expected playoff
   rounds +4.1, expected titles +6.9, assets +3.8, depth +1.3. Hindsight:
   wins +7.0, rounds +10.1, titles +10.2, assets +6.1. The 2.0 rows
   replayed under score-v2 showed the same thing for Astra:
   +67.4 from winning terms and -18.8 from end-state terms
   ([score_deep_dive.md](score_deep_dive.md) section 1). It trades future
   value for wins now, at a scale the searches never reach.
4. **Why the menu can't reach it (a reading of the method, not
   measured).** Every candidate is a one-window deviation from
   `pick-trader`, judged by a rollout in which `pick-trader` plays every
   later window. A plan that only pays off when it is kept up for several
   seasons gets credit for one window at a time. None of the macro
   policies is a good win-now policy: under 2.1 each one scores below
   `pick-trader` (`validate-contract --contract 2.1`,
   [bench_v2_1_spec.md](bench_v2_1_spec.md)), and the generated menu has
   no contract extension. Astra extends 25 contracts a game
   (`results/diagnostics/v21_behavior/behavior.json`), where the scripted
   policies extend at most two players a preseason. It also makes about
   155 tool calls a game, so many moves land in each window.
5. **2.1 leaves a little less for these searches than 1.0 did.** Paired
   by seed against the 1.0 luck-neutral rows: fair -6.1 (se 4.7) on
   101-124 and -2.4 (se 3.4) on 125-172, hindsight -8.1 (se 4.4). The
   same fair planner optimizing score-v2's formula (E) on the 1.0
   simulator gained +29.1 on 101-124
   (`results/diagnostics/score_deep_dive/exploit_E_101_124.json`). On
   `League21` it gains +20.1, a difference of -9.0 (se 4.6). Taken with
   the replication, the fair bound is about +20 to +23 under 2.1, against
   +25 to +26 under 1.0. Whether records reset, the draft fix or noise
   accounts for the rest was not separated.

**What it implies.** `pick-trader` is still well below the best
achievable play under 2.1. A public-information planner beats it by about
22 points across 72 seeds, and a model beats it by 47 on the private
panel. These searches can't say how much further the scale goes. A
ceiling estimate that means anything above +47 needs a stronger search:
multi-move windows, extensions in the generated menu, and rollouts with a
continuation policy that keeps a win-now plan going instead of reverting
to `pick-trader`. Until then, the honest reading of the leaderboard's top
is "at least +47 is reachable, upper end unmeasured", not "near the
ceiling".

### Caveats

- The public seeds and the private panel are different seed sets. The
  `pick-trader` means agree within 2 points, but the model rows and the
  searches are not paired.
- Each search ran once (one planner seed, beam 4, 6 worlds), with the
  1.0 rows' settings unchanged so the two contracts can be compared. Any
  of those settings could be raised; this rerun did not tune them.
- Under 2.1, `--luck-neutral` is refused: score-v2 is already the
  luck-neutral objective.

### Reproducing (2.1)

Local CPU only, no model calls. On 12 cores with `--jobs 10`, the first
and third lines take about 30 and 50 minutes and the second about 15.

```bash
python scripts/ceiling_search.py fair --contract 2.1 --generated --seeds 101-124 --worlds 6 --jobs 10 --out v21_fair_generated.json
python scripts/ceiling_search.py hindsight --contract 2.1 --seeds 101-124 --beam 4 --jobs 10 --out v21_hindsight.json
python scripts/ceiling_search.py fair --contract 2.1 --generated --seeds 125-172 --worlds 6 --jobs 10 --out v21_fair_generated_125_172.json
```
