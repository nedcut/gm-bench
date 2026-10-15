# How much headroom is left above `pick-trader`?

Diagnostic, recorded 2026-10-14. Nothing here is an official baseline, a
contract change, or a submission. The tool is `scripts/ceiling_search.py`;
per-seed results, including each search's chosen move path, are in
`results/diagnostics/score_ceiling/`.

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

Six of the eleven published panel rows have their raw run directory on the
machine this ran on; the other five (`claude-haiku-4-5`, `claude-sonnet-5`,
`gpt-6-luna`, `composer-2.5`, OpenCode 1.18.31 `deepseek-v4.1-flash`) were
not rescored. The 1.0 rows were not rescored either: their committed
artifacts are compact and the raw private-panel artifacts are not local.

| Row (32 private seeds) | Real lift vs `pick-trader` (se) | p | MDE | Luck-neutral lift (se) | p | MDE |
|---|---|---|---|---|---|---|
| Codex `gpt-6-astra` | +39.2 (12.3) | 0.0033 | 34.5 | +43.4 (5.8) | <0.0001 | 16.1 |
| Codex `gpt-6.1-sol` | +24.0 (11.5) | 0.0475 | 32.2 | +26.9 (5.6) | <0.0001 | 15.7 |
| OpenCode 2.0.27 `deepseek-v4.1-flash` | -4.6 (10.8) | 0.671 | 30.2 | -11.2 (7.4) | 0.140 | 20.7 |
| Claude Code `claude-sonnet-5-5` | -32.1 (12.1) | 0.0126 | 34.0 | -36.5 (7.0) | <0.0001 | 19.6 |
| Claude Code `claude-opus-5-5` | -46.7 (12.4) | 0.0009 | 34.6 | -35.5 (7.1) | <0.0001 | 19.9 |
| Claude Code `claude-haiku-5-5` | -46.5 (10.7) | 0.0002 | 29.9 | -60.2 (6.5) | <0.0001 | 18.3 |

MDE is the paired difference detectable at 80% power and two-sided 5%
(normal approximation). p is the runner's two-sided sign-flip test, which
samples 20,000 flips at 32 seeds, so "<0.0001" means no sampled flip
reached the observed mean.

- **The panel gets about 44% more sensitive.** Mean MDE falls from 32.6 to
  18.4 points with no new runs: the same 32 seeds measure what about 100
  would under the realized score.
- **No row changes direction, and the borderline calls resolve.**
  `gpt-6.1-sol`'s +24.0 at p = 0.0475 fails a Holm correction across these
  six rows; luck-neutral it is +26.9 (95% interval +15.9 to +37.9) and
  passes. Every row except DeepSeek clears Holm luck-neutral. DeepSeek
  stays "can't tell", but its interval narrows to -25.7 to +3.3.
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
- 24 seeds; the 1.5-se switching rule was picked after a 4-seed trial on
  seeds 101-104, which are inside the reported set.
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
