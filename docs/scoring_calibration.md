# GM-Bench Scoring Calibration

This document explains the objective score computed by `gm_bench/scoring.py` at the
end of each episode. The function is hand-tuned for the MVP to reward winning,
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

Weights are not derived from a formal optimization process in the MVP. They were
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

The current `sota-v3` contract (fingerprint `9ae26dbed754f94b`) still uses the
same `score-v1` weights and clamps. Contract economics change the simulated
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

The current `sota-v3` development panel (seeds 11-18, five seasons; contract
fingerprint `9ae26dbed754f94b`, protocol `gm-bench-v3`)
produces:

| Reference | Mean score | Illegal actions | Role |
| --- | ---: | ---: | --- |
| `scaffold-view` | 286.935 | 0 | Pick-trader policy on the compact adapter payload |
| `pick-trader` | 285.211 | 0 | Strongest official scripted bar |
| `strategic` | 277.393 | 0 | Scouting, offers, memo, extensions, and shrewd roster core |
| `shrewd` | 266.941 | 0 | Dead-cap-aware roster and development policy |
| `value` | 265.631 | 0 | Public-value roster heuristic |
| `win-now` | 250.895 | 0 | Short-horizon win maximizer |
| `rebuild` | 135.057 | 0 | Youth-oriented tear-down |
| `conservative` | 133.649 | 0 | Low-churn roster holder |
| `exploit` | 131.561 | 24 | Unmodified red-team canary |
| `random` | 92.338 | 0 | Floor / noise baseline |

The strategic policy's panel ablations are also deterministic:

| Policy variant | Mean score | Change vs `strategic` |
| --- | ---: | ---: |
| Full `strategic` | 277.393 | 0.000 |
| No scouting | 283.601 | +6.208 |
| No incoming-offer policy | 255.127 | -22.266 |
| No memo writes | 277.393 | 0.000 |
| `shrewd` core only | 266.941 | -10.452 |
| Pick trading enabled (`pick-trader`) | 285.211 | +7.818 |

This is intentionally not presented as causal estimation: mechanics interact
over five seasons. On this panel, the deterministic scouting policy is
counterproductive while selective offer handling and contract-aware pick sales
improve the mean. That is a calibration result, not a claim that information is
harmful in general. Memo persistence has zero direct effect for this
deterministic reference, which can reconstruct its policy from the observation.
`validate-contract` separately requires accepted
memo, scout, offer-response, offer-acceptance, pick-trade, and extension actions
across minimum fractions of the official panel, so these mechanics cannot
silently become dead protocol surface.

### Hidden-information diagnostic

`oracle` is a diagnostic-only hidden-information reference, not an official
baseline and not part of the `sota-v3` baseline panel. On the same public panel
(seeds 11-18, five seasons), it scores **274.947**, versus **285.211** for
`pick-trader`.

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
