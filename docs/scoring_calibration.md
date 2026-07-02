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
| `cap_score` | `clamp(cap_room × 0.35, -12, 10)` | Rewards cap flexibility; penalizes severe cap stress |
| `current_strength` | Deterministic team strength of the dressed lineup (no injury noise) | Reflects present on-ice quality; responds to `set_lineup` choices |
| `roster_depth` | `min(roster_size, 24) / 24` scaled by 8 | Small bonus for maintaining a full roster |
| `protocol_penalty` | `illegal_actions × 2.5` (user team only) | Penalizes invalid or rejected actions; reported separately from strategy |

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

When changing weights, update golden-score regression tests if present.
