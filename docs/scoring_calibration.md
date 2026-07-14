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
4. **Legality is enforced economically** — Illegal actions directly reduce score.

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

The `sota-v2` benchmark contract (fingerprint `a65a4359ca3c6e64`, see
[production_benchmark.md](production_benchmark.md)) does not touch `score-v1`:
no scoring weight or clamp changed. The `sota-v1` → `sota-v2` bump was a
protocol/simulator fix (`scout` accepting `prospect_id`) and a reporting
addition (`failed_queries`), both orthogonal to `scoring.py`. `failed_queries`
is not a scoring term — declined query actions carry zero weight, the same as
before, because querying is meant to be free. It is now reported in episode
results, run summaries, and comparison blocks, but that is a visibility fix,
not a scale change: two rows with the same `score-v1` fingerprint remain
comparable regardless of how many queries either one failed.

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

The current `sota-v2` public panel (seeds 11-18, five seasons; contract
fingerprint `a65a4359ca3c6e64`, protocol `gm-bench-v2` with midseason)
produces:

| Reference | Mean score | Illegal actions | Role |
| --- | ---: | ---: | --- |
| `pick-trader` | 411.619 | 0 | Strongest official scripted bar |
| `strategic` | 402.025 | 0 | Scouting, offers, memo, and shrewd roster core |
| `shrewd` | 371.769 | 0 | Cap hygiene and development-aware lineup core |
| `value` | 354.619 | 0 | Public-value roster heuristic |
| `win-now` | 275.834 | 0 | Short-horizon win maximizer |
| `conservative` | 139.030 | 0 | Low-churn roster holder |
| `rebuild` | 138.745 | 0 | Youth-oriented tear-down |
| `random` | 96.715 | 0 | Floor / noise baseline |

The strategic policy's panel ablations are also deterministic:

| Policy variant | Mean score | Change vs `strategic` |
| --- | ---: | ---: |
| Full `strategic` | 402.025 | 0.000 |
| No scouting | 371.284 | -30.741 |
| No incoming-offer policy | 395.539 | -6.486 |
| No memo writes | 402.025 | 0.000 |
| `shrewd` core only | 371.769 | -30.256 |
| Pick trading enabled (`pick-trader`) | 411.619 | +9.594 |

This is intentionally not presented as causal estimation: mechanics interact
over five seasons. It is a regression calibration showing that scouting and
selective offer handling have measurable decision value. The cap-aware pick
policy also improves the panel mean, but remains separate so its marginal effect
stays visible rather than being hidden inside `strategic`. Memo persistence is
covered as protocol behavior but has zero direct effect for this deterministic
reference, which can reconstruct its policy from the observation; its value as
an LLM memory channel still requires model-backed evaluation.
`validate-contract` separately requires accepted
memo, scout, offer-response, offer-acceptance, and pick-trade actions across
minimum fractions of the official panel, so these mechanics cannot silently
become dead protocol surface.

### Ceiling reference

`oracle` is a diagnostic-only hidden-information reference, not an official
baseline and not part of the `sota-v2` baseline panel. On the same public panel
(seeds 11-18, five seasons), it scores **431.150**, versus **411.619** for
`pick-trader`: a **19.531-point** pick-trader-to-oracle gap.

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
outcomes, or opponents' future actions. The gap is the strategic headroom that
the benchmark can discriminate beyond its strongest public-information scripted
policy; it is a ceiling reference, not a target for valid model submissions.

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

For scale sensitivity, `weight_sensitivity.py` runs the scripted panel once,
captures raw end-of-episode components through a diagnostic-only temporary
wrapper around `runner.score_breakdown`, and restores the wrapper immediately.
It then applies 200 independent draws, multiplying each score weight uniformly
between 0.70 and 1.30.  The canonical ordering is `pick-trader > strategic >
shrewd > value > win-now > conservative > rebuild > random`.  Adjacent-pair
rank-flip rates were 0% for every pair except `conservative > rebuild`, which
flipped in 40% of draws.  Kendall tau against the canonical full ranking had
mean 0.971, median 1.000, and 5th--95th percentile range 0.929--1.000.

Per-episode score components are not persisted in result artifacts, so weight
sensitivity for model rows cannot be recomputed post-hoc.  Persisting them
would touch the frozen runner contract and is therefore a future contract-lane
item (not part of `sota-v2`), not part of this score-v1 analysis tooling.