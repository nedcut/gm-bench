# GM-Bench Scoring Calibration

This document explains the objective score computed by `gm_bench/scoring.py` at the
end of each episode. The function is hand-tuned for this benchmark to reward winning,
sustainable roster building, and legal play.

## Formula

For the user-controlled team:

```text
strategy_score =
    recent_wins        × 0.42
  + recent_rounds      × 9.0
  + championships      × 35.0
  + total_assets       × 0.16
  + young_assets       × 0.18
  + future_pick_assets × 0.16
  + cap_score
  + current_strength   × 0.28
  + roster_depth       × 8.0

protocol_penalty = illegal_actions × 2.5

final_score = strategy_score - protocol_penalty
```

`strategy_score` and `protocol_penalty` are reported separately in episode
results, run summaries, and `evaluate` output so roster-management skill is
not conflated with an agent's ability to emit valid JSON. `final_score`
remains the headline objective.

Where:

| Term | Definition | Rationale |
| --- | --- | --- |
| `recent_wins` | Wins in the last 3 simulated seasons | Rewards near-term competitiveness without overweighting a single season |
| `recent_rounds` | Playoff rounds reached in the last 3 seasons | Values postseason success below a title but above regular-season wins |
| `championships` | Career titles for the franchise | Largest single reward; encodes the ultimate GM goal |
| `total_assets` | Sum of hidden `asset_value` across the roster | Encourages accumulating valuable players |
| `young_assets` | Asset value of players age ≤ 24 | Rewards sustainable, future-oriented roster construction |
| `future_pick_assets` | Discounted value of future draft picks owned | Keeps pick trades on the same asset scale as player trades |
| `cap_score` | `clamp(cap_room × 0.35, -12, 10)` | Rewards cap flexibility; penalizes severe cap stress |
| `current_strength` | Deterministic team strength of the dressed lineup (no injury noise) | Reflects present on-ice quality; responds to `set_lineup` choices |
| `roster_depth` | `min(roster_size, 24) / 24` scaled by 8 | Small bonus for maintaining a full roster |
| `protocol_penalty` | `illegal_actions × 2.5` (user team only) | Penalizes invalid actions (malformed, impossible, cap/roster violations); reported separately from strategy |
| `rejected_offers` | Count of legal-but-declined trade/FA offers (informational, zero weight) | Probing hidden valuations is negotiation, not a protocol failure; walk-away limits prevent free binary search |

## Design intent

1. **Championships dominate** — A title is worth more than a strong regular season.
2. **Multi-season memory** — Recent performance uses a 3-season window so agents
   cannot optimize a single lucky year.
3. **Asset building matters** — Even losing rebuilds can score reasonably if young
   talent and cap space are preserved.
4. **Sustainable accumulation beats win-now mortgaging** — This is the primary
   composite's deliberate bias. `recent_wins` and `recent_rounds` read only the
   trailing three seasons (`league.summaries[-3:]`), while `total_assets`,
   `young_assets`, `future_pick_assets`, and `cap_score` are computed from
   end-of-episode state. Shipping youth and picks for one strong season is
   therefore credited once and charged against the stock terms for every season
   that follows. Only `championships` — a career count — is a permanent win
   reward, so real title contention is still worth paying for. The v6 48-seed
   panel below (contract `a600b7da0c302231`) shows the accumulation half of
   this: the asset-aware `pick-trader` (254.565) beats the balanced `value`
   heuristic (186.587) by a paired *t* of 10.38. It does not show the win-now
   half — `win-now` (179.979) and `value` are unresolved against each other
   (paired *t* = 1.12), so the panel says nothing either way about short-horizon
   mortgaging being punished relative to a balanced policy.
5. **Legality is enforced economically** — Illegal actions directly reduce score.

## Baseline normalization

The `evaluate` command reports:

```text
score_lift = candidate_mean_score - baseline_panel_mean_score
```

This normalizes against scripted baselines on identical seeds so small benchmark
runs are less sensitive to league-generation luck.

## Calibration notes

Weights are not derived from a formal optimization process. They were
chosen so that:

- Scripted `value` clearly outperforms `random` on shared seeds.
- `win-now` can spike on short horizons via wins but often trails on asset terms.
- `rebuild` remains viable through young-asset and cap components.

The asset terms are also guarded against accumulation exploits at the rules
level: trades face hidden per-partner valuation noise, a per-partner limit per
season, and roster minimums, so asset totals can no longer be pumped through
repeated favorable trades. The `exploit` baseline agent and its regression
test (`test_exploit_agent_no_longer_beats_honest_baselines`) pin this: if a
rules or weight change makes asset hoarding dominant again, that test fails.

## Versioned scale and marginal values

The active scale is `score-v1`, fingerprint `05a60ff4f691e734`. The fingerprint
is derived only from the published weights and clamps. GM-Bench validates it at
import time, so changing a weight without declaring a new score version fails
immediately instead of silently changing leaderboard meaning.

The frozen `sota-v2` benchmark contract (fingerprint `558e8f35ea1d66b9`, see
[production_benchmark.md](production_benchmark.md)) does not touch `score-v1`:
no scoring weight or clamp changed. The `sota-v1` → `sota-v2` bump was a
protocol/simulator fix (`scout` accepting `prospect_id`) and a reporting
addition (`failed_queries`), both orthogonal to `scoring.py`. `failed_queries`
is not a scoring term — declined query actions carry zero weight, the same as
before, because querying is meant to be free. It is now reported in episode
results, run summaries, and comparison blocks, but that is a visibility fix,
not a scale change: two rows with the same `score-v1` fingerprint remain
comparable regardless of how many queries either one failed.

The current `sota-v5` contract (fingerprint recorded in
`config/sota_v5_lane.json`) still uses the same `score-v1` weights and clamps.
Contract economics change the simulated
rosters, and `cap_room` now correctly uses payroll including retained dead cap;
neither change modifies the published score scale itself.

The v6 simulator work (draft lottery, free-agent willingness, centre-aware
lineups, expiring contracts, inert-field removal, and the released-player
re-signing fix) likewise leaves `score-v1` untouched: contract fingerprint
`a600b7da0c302231`, scoring-scale fingerprint `05a60ff4f691e734`. The Phase 2b
re-calibration below found no reason to change a weight — the sensitivity
ladder separates every intended rung by more than the 30-point MDD target on
its own, so re-weighting would only be fitting noise.

Reproduce the complete machine-readable scale and calibration:

```bash
python -m gm_bench calibrate-score --json
```

| Counterfactual change | Score delta |
| --- | ---: |
| One championship | +35.0 |
| Ten recent wins | +4.2 |
| One playoff round | +9.0 |
| Twenty veteran asset value | +3.2 |
| Twenty young asset value | +6.8 |
| Ten future-pick asset value | +1.6 |
| Ten cap room, while the cap term is unclamped | +3.5 |
| Ten current-strength points | +2.8 |
| One illegal action | -2.5 |

These are local score-scale marginals, not claims that the underlying roster
changes are causally independent. Acquiring a young player, for example, may
also change strength, cap room, and wins.

## Reference-policy calibration

Everything in this section and the two that follow was measured on
2026-08-31 against **contract fingerprint `a600b7da0c302231`** (scoring scale
`score-v1`, `05a60ff4f691e734`) — the v6 simulator with the draft lottery,
free-agent willingness, centre-aware lineups, expiring contracts, inert-field
removal, and the released-player re-signing fix. Any edit to a file in
`_CONTRACT_SOURCES` invalidates these numbers.

Re-measured from `a600b7da0c302231` because the compact observation render, the
one-call execution rules, and the adapter/repair split all moved the fingerprint
after the first measurement. Only `scaffold-view` changed, and only because it
is the one reference whose whole result is a function of the model view: it
reads the compact payload, and `gm_bench/scaffold_view.py` is in
`_CONTRACT_SOURCES` for exactly that reason. Every other scripted policy scores
the simulator state directly and reproduced its previous mean, standard
deviation, and illegal-action count exactly.

Reference policies are calibrated on a **48-seed panel (seeds 11-58, five
seasons)**; `validate-contract` gates on the 24-seed slice (11-34), and the v6
model panel uses 29 seeds. These panels are sized by different constraints and
need not share a width: every policy here is scripted and costs only CPU, while
the model-panel width is set by its power rule and API-spend boundary.

Panel width still decides which orderings can be claimed, but v6 moved the
threshold. The `pick-trader` over `value` contrast, measured paired on matched
seeds under contract `a600b7da0c302231`:

| seeds | mean difference | paired *t* | seeds won |
| ---: | ---: | ---: | ---: |
| 8 (frozen v2 public width) | 44.62 | 3.76 | 7/8 |
| 16 (preregistered v3 width) | 68.06 | 7.11 | 15/16 |
| 24 (canary width) | 63.64 | 8.93 | 23/24 |
| 48 | 67.98 | 10.38 | 44/48 |

Under the v5 contract this same contrast was effectively zero at eight seeds
(paired *t* = -0.004) and only reached *t* = 2.559 at 24. The v6 mechanics
widened the gap rather than the noise, so it now resolves at every width above.
That is a statement about this one large contrast, not a licence to rank
adjacent policies on a narrow panel: the top four references remain mutually
unresolved even at 48 seeds (see the ladder below). `validate-contract` still
gates only its narrow canary invariants on paired *t* >= 2.0 over the 24-seed
panel rather than pinning a full ranked ladder.

Current v6 reference-policy validation (48 seeds, 11-58, five seasons,
contract `a600b7da0c302231`; `sd` is the across-seed standard deviation):

| Reference | Mean score | sd | Illegal actions | Role |
| --- | ---: | ---: | ---: | --- |
| `scaffold-view` | 257.42 | 52.21 | 2 | Pick-trader policy on the compact adapter payload |
| `shrewd` | 256.27 | 47.45 | 0 | Dead-cap-aware roster and development policy |
| `pick-trader` | 254.57 | 48.88 | 1 | Official scripted bar |
| `strategic` | 246.31 | 41.16 | 1 | Scouting, offers, memo, extensions, and shrewd roster core |
| `value` | 186.59 | 38.92 | 0 | Public-value roster heuristic |
| `win-now` | 179.98 | 30.79 | 0 | Short-horizon win maximizer |
| `rebuild` | 135.91 | 26.69 | 0 | Youth-oriented tear-down |
| `conservative` | 130.38 | 19.01 | 0 | Low-churn roster holder |
| `exploit` | 128.17 | 22.48 | 193 | Unmodified red-team canary |
| `random` | 95.32 | 16.34 | 0 | Floor / noise baseline |

Two reference invariants are asserted: `pick-trader > value` (24-seed paired
*t* = 8.93) and `shrewd > value` (24-seed paired *t* = 6.46). The four policies
at the top sit within 13 points of each other against per-seed standard
deviations near 50, so their relative order is still not established and is not
pinned. Reporting them as a ranked ladder would overstate what the panel shows.

### v6 sensitivity ladder

Measured 2026-08-31 against contract `a600b7da0c302231`, 48 paired seeds
(11-58), five seasons, one run per seed — every policy here is deterministic,
so a seed is a complete observation. Differences are **paired per seed**, not
differences of means. `sd` is the standard deviation of the per-seed
difference, which is the quantity the MDD projection uses.

| Pairing | Paired mean | sd | paired *t* | seeds won |
| --- | ---: | ---: | ---: | ---: |
| `scaffold-view` > `value` | 70.84 | 55.38 | 8.86 | 43/48 |
| `shrewd` > `value` | 69.68 | 54.46 | 8.86 | 44/48 |
| `pick-trader` > `value` | 67.98 | 45.38 | 10.38 | 44/48 |
| `strategic` > `value` | 59.73 | 45.03 | 9.19 | 43/48 |
| `shrewd` > `win-now` | 76.29 | 54.23 | 9.75 | 45/48 |
| `shrewd` > `random` | 160.95 | 46.91 | 23.77 | 48/48 |
| `win-now` > `random` | 84.66 | 30.54 | 19.20 | 48/48 |
| `conservative` > `random` | 35.06 | 22.40 | 10.84 | 46/48 |
| `value` > `random` | 91.27 | 38.78 | 16.30 | 48/48 |
| `value` > `rebuild` | 50.67 | 34.16 | 10.28 | 45/48 |
| `value` > `conservative` | 56.21 | 39.55 | 9.85 | 47/48 |
| `value` > `exploit` (damaged) | 58.42 | 41.86 | 9.67 | 46/48 |
| `value` > `pick-hoard` (damaged) | 51.40 | 33.57 | 10.61 | 47/48 |
| `value` > `cap-hoard` (damaged) | 65.11 | 34.35 | 13.13 | 48/48 |
| `value` > `accept-everything` (damaged) | 50.87 | 45.56 | 7.74 | 45/48 |
| `value` > `win-now` | 6.61 | 40.70 | 1.12 | 28/48 | 
| `pick-trader` > `strategic` | 8.25 | 43.12 | 1.33 | 29/48 |
| `shrewd` > `strategic` | 9.95 | 35.42 | 1.95 | 28/48 |
| `shrewd` > `pick-trader` | 1.70 | 53.88 | 0.22 | 20/48 |

The four damaged agents are the existing `validate-contract` canaries
(`exploit`, `pick-hoard`, `cap-hoard`, `accept-everything`); no new agent was
written for this ladder. Every rung the design intends to separate — strong
over mid, mid over weak, honest over damaged — clears 35 paired points at a
paired *t* of 7.7 or better, so the tiers separate cleanly. That is the only
claim the ladder makes. These are 48-seed scripted-policy gaps, a different
quantity from the 30-point MDD, which is a statement about what a 29-seed model
row can resolve; every intended rung but one sits far above the MDD band
(`conservative` > `random` at 35.06 is the sole rung anywhere near it), so the
ladder cannot corroborate that figure either way and the MDD rests on the power
simulation below. The last four rows are the rungs the design does
**not** claim: `value`/`win-now` are two different mid policies rather than a
tier step, and the top three references are deliberately close variants of one
another. They are reported so their non-separation stays visible.

Note that contract economics cost `pick-trader` its former lead: with releases
priced and incumbents retainable, cap hygiene and retention now compete with
pick accumulation. Its position among the top four moves with panel width, which
is noise rather than a result.

### Mechanic liveness

A mechanic that never fires is inert regardless of its constants, so liveness is
measured rather than assumed. Over the 24-seed panel (120 team-seasons), the
agent's own team:

| Mechanic | Count | Seeds covered |
| --- | ---: | ---: |
| Memo writes accepted | 120 | 24/24 |
| Scouting accepted | 360 | 24/24 |
| Offer responses accepted | 359 | 24/24 |
| Incoming offers accepted | 17 | 12/24 |
| Pick trades accepted | 72 | 23/24 |
| Extensions accepted | 223 | 24/24 |
| Releases accepted | 11 | 8/24 |
| Contract terms signed | ext 4y: 161, ext 3y: 62, FA 1y: 1065, FA 3y: 253 | — |

Releases are rare by design: dead cap is a deterrent, and a policy that pays it
anyway is choosing to. Before the fix in #91 the count was **zero and could not
have been anything else** -- the release branch required a conjunction of
conditions that never co-occurred, so a working deterrent and an unreachable
branch produced the same number. They are now distinguishable.

The strategic policy's panel ablations are also deterministic:

| Policy variant | Mean score | Change vs `strategic` |
| --- | ---: | ---: |
| Full `strategic` | 256.630 | 0.000 |
| No scouting | 263.978 | +7.348 |
| No incoming-offer policy | 259.607 | +2.977 |
| No memo writes | 256.630 | 0.000 |
| `shrewd` core only | 264.049 | +7.419 |
| Pick trading enabled (`pick-trader`) | 251.328 | -5.302 |

These are measured on the 24-seed panel (seeds 11-34) under contract
`a600b7da0c302231`. This is intentionally not presented as causal estimation:
mechanics interact over five seasons. On this panel every ablation of
`strategic` lands within about seven points of the full policy, which is inside
the noise the 48-seed ladder above reports for adjacent references, so the
signs should not be read as effects. Only the pick-sale policy is a consistent
small cost. Memo persistence has zero direct effect for this
deterministic reference, which can reconstruct its policy from the observation.
`validate-contract` asserts `pick-trader > value` and `shrewd > value`. Both keep
the mean-margin check and additionally require the per-seed paired difference to
clear a t ratio of 2.0; the `shrewd > value` mean-margin floor moved back to 25
points now that the contrast measures 76.4. That floor had been dropped to 15
when the same contrast read 24.5 after the draft lottery landed, and it was the
v6 mechanic work as a whole that brought it back — 24.50, then 36.80 with
free-agent willingness, 41.83 with the center lineup, 56.15 with expiring
contracts, 84.51 once the inert fields were removed, and 76.36 with the
release-then-re-sign block on top, which costs `shrewd` more than `value` and so
gives back about 8 points of the gap (see `gm_bench/validity.py`). The
adjacent `pick-trader`/`strategic` and `strategic`/`shrewd` comparisons remain
calibration rows: their 48-seed paired t ratios are 1.33 and 1.95, neither
resolvable. The validator separately
requires accepted memo, scout, offer-response, offer-acceptance, pick-trade,
and extension actions across minimum fractions of the official panel, so these
mechanics cannot silently become dead protocol surface.

### Hidden-information diagnostic

`oracle` is a diagnostic-only hidden-information reference, not an official
baseline and not part of the `sota-v3` baseline panel. On the public leaderboard
panel (seeds 11-18, five seasons), it scores **274.789**, versus **267.875** for
`pick-trader` — so perfect knowledge of draft-class `true_potential` is still
worth something under contract economics. These two numbers were measured under
an earlier contract and were not re-run for v6.

Read that gap with the panel-width caveat above in mind: eight seeds cannot
resolve a difference of this size, and the number is quoted as a diagnostic
reading rather than an established ordering.

The oracle begins with the `pick-trader` policy, then regenerates a draft
class's deterministic `true_potential` from its seed and uses it only for
material latent-upside substitutions at the draft. It also recomputes the
deterministic free-agent reservation price before retaining an offer, and the
partner-specific trade-valuation bias before retaining a pick trade. Initial
league players and every yearly draft class are deterministically regenerable;
therefore players who later surface as free agents or waivers can also be
traced to an initial or draft population. This partial reference deliberately
does not use their latent potential for its free-agent roster policy, so the
measured result is conservative rather than a claim of globally optimal play.

It does not predict injury draws, player-development rolls, game and playoff
outcomes, contract decisions, or opponents' future actions. Under the current
contract it is a behaviorally distinct hidden-draft diagnostic, not an
optimization ceiling or a target for valid model submissions.

This gap is narrower than the 8-seed minimum detectable difference reported
in the Robustness section below: at the current panel size, scores inside the
pick-trader-to-oracle band cannot be statistically separated from each other.
The band marks where strategic headroom exists, not where the current design
can rank models; separating models inside it is a larger-panel concern for a
future contract lane (`sota-v2` kept the 8-seed panel; not addressed yet).

## Robustness

The diagnostic scripts make the uncertainty around the hand-tuned scale
explicit.  They are intentionally separate from the benchmark contract:

```bash
python scripts/power_analysis.py --result results/leaderboard/archive-v1/ollama-gemma4-e4b.json
python scripts/weight_sensitivity.py
```

Power analysis uses the scripted policies' centred same-seed differences as the
empirical paired-noise distribution, adds independent Gaussian repeat noise for
the model row, and tests the synthetic paired lifts at p < 0.05 using a normal
approximation to the sign-flip null.

### v6 power analysis

Re-measured 2026-08-31 against contract `a600b7da0c302231` on the full 48-seed
residual panel, so the seed counts below are resampled from 48 directly
measured seeds rather than extrapolated from eight:

```bash
python scripts/power_analysis.py --seeds $(seq 11 58) --repeats 1 \
  --within-seed-stddev 15.037 --seed-counts 8 12 16 24 29 48 \
  --trials 2000 --gap-step 1.0
```

Observed paired-residual SD across the eight reference policies is **40.146**
(mean per-pair paired SD 39.52). The v6 spec hoped simulator fixes would shrink
paired variance; they did not. What improved instead is the size of the real
gaps, which is why the ladder above separates far more cleanly than the v5
ladder did. The MDD is what it is because of that SD, not because of a
variance win.

`repeats=1` matches the v6 panel design (29 seeds, one episode per seed), so
model repeat noise does not average down and enters the paired difference at
`sqrt(2) x within_seed_sd`.

| Seed count | MDD at 80% simulated detection rate |
| ---: | ---: |
| 8 | 58 points |
| 12 | 44 points |
| 16 | 36 points |
| 24 | 29 points |
| **29 (v6 panel width)** | **26 points** |
| 48 | 20 points |

**The 30-point MDD target in `docs/bench_v6_spec.md` holds at 29 paired seeds,
with 4 points of margin.** The v6 spec's anchor of "MDD ~40 at 16 seeds" now
measures 36, so the spec's 29.7-point projection was slightly conservative.

This projection is sensitive to the model row's within-seed repeat noise, which
is a property of the model rather than of the simulator and therefore cannot be
measured from scripted policies. At 29 seeds:

| Assumed within-seed repeat SD | MDD at 29 seeds |
| ---: | ---: |
| 0 (deterministic row) | 22 points |
| 15.0 (v5 anchor artifact) | 26 points |
| 25.0 | 30 points |
| 35.0 | 35 points |

The 30-point target therefore holds for any model whose within-seed score SD is
at or below about 25. Saved v5-era leaderboard artifacts span 19.9 to 56.7 on
that statistic, so a high-variance model row can still fail to separate at 29
seeds even though the simulator does. That is a reporting obligation, not a
blocker: record each row's `within_seed_score_stddev` and do not claim
separation for a pair whose noisiest member exceeds the band.

`scripts/analyze_publication_panel.py` enforces that obligation rather than
leaving it to prose. Every eligible row carries its own
`within_seed_score_stddev`, and the analysis output carries a
`within_seed_noise` block naming the rows above the threshold, the model pairs
whose separation is therefore unclaimable, and — where the analyzer does assign
tiers — the same caveat attached to `model_tiering`. A row that never reports
the statistic counts as unclaimable too: an unmeasured spread cannot clear a
bound. The threshold defaults to 25 and is read from the frozen analysis plan's
`statistical_analysis_plan.within_seed_noise_caveat.threshold` when one is
committed. Nothing here withholds a row: a noisy model publishes its score and
its reference contrast exactly as a quiet one does.

Two quantities are easy to confuse and are not the same thing:

- **Canary margins** (`gm_bench/validity.py`, run by `validate-contract`) are
  fixed thresholds on *scripted* policy contrasts on the 24-seed panel. They
  ask "is the simulator still scoring honest play above degenerate play?" and
  are pass/fail gates on a deterministic quantity.
- **The MDD** is a projection about *model* rows on the 29-seed panel. It asks
  "how far apart must two models be before this panel can tell them apart?" A
  canary margin of 76 points says nothing about whether two models 20 points
  apart are distinguishable.

For scale sensitivity, `weight_sensitivity.py` runs the scripted panel once and
reads the raw end-of-episode components straight off each episode row.
It then applies 200 independent draws, multiplying each score weight uniformly
between 0.70 and 1.30.

The published sweep below was measured under `sota-v2` (contract
`558e8f35ea1d66b9`) using the earlier in-process capture, and has **not** been
re-run under `sota-v3`.  Treat it as v2-era evidence: change 0B in `1e5cd44`
made negotiation walk-aways persist for a whole decision window, which can move
scripted trade outcomes and therefore these flip rates.  The canonical ordering
was `pick-trader > strategic > shrewd > value > win-now > conservative >
rebuild > random`.  Adjacent-pair rank-flip rates were 0% for every pair except
`conservative > rebuild`, which flipped in 40% of draws.  Kendall tau against
the canonical full ranking had mean 0.971, median 1.000, and 5th--95th
percentile range 0.929--1.000.

From `sota-v3` onward every episode row carries a `score_components` block: the
nine raw end-of-episode metrics, the protocol penalty, and the nine weighted
`*_contribution` terms, each rounded to six decimals.  Both halves are stored
because the contributions alone cannot be reweighted --- `cap_room` is clamped,
so its contribution is not a linear function of its weight.  `sota-v3`
validation requires the block, checks every term is finite, and checks the
contributions still sum to the row's `strategy_score`; `sota-v2` and the v1
archive predate the field and validate without it.  Run
`weight_sensitivity.py --result <artifact.json>` to reweight a saved model row
post-hoc without re-running the panel; a pre-v3 artifact has no components and
the script exits with an explicit message rather than guessing.
