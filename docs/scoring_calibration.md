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
   reward, so real title contention is still worth paying for. The frozen
   `sota-v2` panel below (contract `558e8f35ea1d66b9`) shows the effect:
   `win-now` (275.834) trails the balanced `value` heuristic (354.619) and the
   asset-aware `pick-trader` (411.619). These are v2-era measurements; they have
   not been re-run under the current contract.
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

The current `sota-v4` contract (fingerprint recorded in
`config/sota_v4_lane.json`) still uses the same `score-v1` weights and clamps.
Contract economics change the simulated
rosters, and `cap_room` now correctly uses payroll including retained dead cap;
neither change modifies the published score scale itself.

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

Reference policies are calibrated on a **24-seed panel (seeds 11-34, five
seasons)**. The frozen public v2 model panel used eight seeds; the preregistered
private v3 panel uses 16. These panels are sized by different constraints and
need not share a width: every policy here is scripted and costs only CPU, while
the model-panel width is set by its power rule and API-spend boundary.

Eight seeds cannot support an ordering claim on this engine. The same two
policies, measured paired on matched seeds:

| seeds | mean difference | paired *t* |
| ---: | ---: | ---: |
| 8 (frozen v2 public width) | -0.11 | -0.004 |
| 16 (preregistered v3 width) | 36.14 | 2.015 |
| 24 (canary width) | 36.37 | 2.559 |
| 48 | 35.51 | 3.999 |

`pick-trader` wins 39 of 48 seeds. Using the 48-seed paired variance, the
approximate two-sided 80%-power requirement is 24 seeds. Neither the eight-seed
v2 slice nor the 16-seed v3 allocation supports a general reference-ordering
claim. `validate-contract` therefore gates only its narrow canary invariants on
paired *t* >= 2.0 over the wider calibration panel rather than pinning a full
ranked ladder.

Current `gm-bench-v3` reference-policy validation:

| Reference | Mean score | Illegal actions | Role |
| --- | ---: | ---: | --- |
| `shrewd` | 288.64 | 0 | Dead-cap-aware roster and development policy |
| `strategic` | 285.02 | 0 | Scouting, offers, memo, extensions, and shrewd roster core |
| `scaffold-view` | 281.88 | 0 | Pick-trader policy on the compact adapter payload |
| `pick-trader` | 279.07 | 0 | Official scripted bar |
| `win-now` | 244.37 | 0 | Short-horizon win maximizer |
| `value` | 242.70 | 0 | Public-value roster heuristic |
| `conservative` | 132.35 | 0 | Low-churn roster holder |
| `rebuild` | 130.35 | 0 | Youth-oriented tear-down |
| `exploit` | 128.03 | 71 | Unmodified red-team canary |
| `random` | 93.10 | 0 | Floor / noise baseline |

Two reference invariants are asserted: `pick-trader > value` (paired *t* =
2.559) and `shrewd > value` (paired *t* = 3.184). The four policies at the top
sit within 10 points of each other against per-seed standard deviations near 50,
so their relative order is not established and is not pinned. Reporting them as
a ranked ladder would overstate what the panel shows.

Note that contract economics cost `pick-trader` its former lead: with releases
priced and incumbents retainable, cap hygiene and retention now compete with
pick accumulation. On the frozen 8-seed v2 public panel the same run puts
`pick-trader` fifth, which is noise rather than a result -- exactly the
divergence the width table above predicts.

### Mechanic liveness

A mechanic that never fires is inert regardless of its constants, so liveness is
measured rather than assumed. Over the 24-seed panel (120 team-seasons), the
agent's own team:

| Mechanic | Count |
| --- | ---: |
| Extensions accepted | 216 |
| Contract terms signed | 4y: 163, 3y: 53, FA 1y: 769, FA 3y: 260 |
| Releases accepted | 7 |

Releases are rare by design: dead cap is a deterrent, and a policy that pays it
anyway is choosing to. Before the fix in #91 the count was **zero and could not
have been anything else** -- the release branch required a conjunction of
conditions that never co-occurred, so a working deterrent and an unreachable
branch produced the same number. They are now distinguishable.

The strategic policy's panel ablations are also deterministic:

| Policy variant | Mean score | Change vs `strategic` |
| --- | ---: | ---: |
| Full `strategic` | 285.025 | 0.000 |
| No scouting | 288.917 | +3.892 |
| No incoming-offer policy | 270.023 | -15.002 |
| No memo writes | 285.025 | 0.000 |
| `shrewd` core only | 288.643 | +3.618 |
| Pick trading enabled (`pick-trader`) | 279.066 | -5.959 |

This is intentionally not presented as causal estimation: mechanics interact
over five seasons. On this panel, removing scouting improves the mean, removing
the incoming-offer policy hurts it, and enabling the pick-sale policy lowers it.
Those are calibration results, not general causal claims about information,
negotiation, or trading. Memo persistence has zero direct effect for this
deterministic reference, which can reconstruct its policy from the observation.
`validate-contract` asserts `pick-trader > value` and `shrewd > value`. Both keep
the mean-margin check and additionally require the per-seed paired difference to
clear a t ratio of 2.0. The adjacent `pick-trader`/`strategic` and
`strategic`/`shrewd` comparisons remain calibration rows: their paired t ratios
are -0.494 and -0.326, respectively, both reversed in sign from the historical
ordering and neither resolvable. The validator separately
requires accepted memo, scout, offer-response, offer-acceptance, pick-trade,
and extension actions across minimum fractions of the official panel, so these
mechanics cannot silently become dead protocol surface.

### Hidden-information diagnostic

`oracle` is a diagnostic-only hidden-information reference, not an official
baseline and not part of the `sota-v3` baseline panel. On the public leaderboard
panel (seeds 11-18, five seasons), it scores **274.789**, versus **267.875** for
`pick-trader` — so perfect knowledge of draft-class `true_potential` is still
worth something under contract economics.

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
python scripts/power_analysis.py --result results/leaderboard/ollama-gemma4-e4b.json
python scripts/weight_sensitivity.py
```

On the current reference panel (seeds 11-18, five seasons), power analysis
uses the scripted policies' centred same-seed differences as the empirical
paired-noise distribution.  It uses three repeats and the supplied artifact's
observed within-seed score SD of 15.037, simulates two model rows with a true
gap, and tests the synthetic paired lifts at p < 0.05 using a normal
approximation to the sign-flip null.  At eight seeds the exact sign-flip test
also has minimum p-value `2 / 2^8 = 0.0078125` (resolution `1 / 2^8`).

| Seed count | MDD at 80% simulated detection rate |
| ---: | ---: |
| 8 | 62 points |
| 12 | 46 points |
| 16 | 40 points |
| 24 | 30 points |

The 12-, 16-, and 24-seed entries resample the observed eight-seed paired
residuals, so they are design extrapolations rather than claims that new seed
panels were directly measured.  Re-run the script with a different result JSON
when evaluating a model with materially different repeat noise.

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
