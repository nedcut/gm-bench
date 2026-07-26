# Gap decomposition and panel power — 2026-07-26

Diagnostic run log. Every number here comes from committed artifacts or from
scripted runs on the current contract (`4f6ddddd6a6dd81c`). **No contract source
was modified**, no paid model run was made, and no published number changes.

Context: the phase-one study reports that all eight eligible model systems
trailed the `pick-trader` reference. The obvious objections to that claim are
that the gap is an artefact of the scaffold rather than of policy quality. This
log closes the free ones.

## 1. Protocol friction explains at most 9% of the gap

`strategy_score` is the score with invalid-action penalties removed, so the
difference between it and `final_score` is exactly what protocol discipline
costs. Over 24 episodes per model:

| model | score | gap to `pick-trader` | protocol cost/episode | share of gap |
|---|---:|---:|---:|---:|
| `meta/muse-spark-1.1` | 231.9 | 179.8 | 5.31 | 3.0% |
| `z-ai/glm-5.2` | 217.5 | 194.1 | 17.50 | 9.0% |
| `google/gemini-3.5-flash` | 215.6 | 196.0 | 1.88 | 1.0% |
| `tencent/hy3:free` | 195.8 | 215.8 | 1.04 | 0.5% |
| `qwen/qwen3.7-plus` | 175.5 | 236.1 | 14.17 | 6.0% |
| `openai/gpt-5.6-luna` | 173.9 | 237.7 | 13.12 | 5.5% |
| `anthropic/claude-sonnet-5` | 142.1 | 269.5 | 4.58 | 1.7% |
| `minimax/minimax-m3` | 129.9 | 281.7 | 1.46 | 0.5% |

**0.5%–9.0%.** A model that emitted perfectly legal JSON on every decision would
still trail `pick-trader` by 174–280 points. "The models just can't format
actions" is not available as an explanation.

Adapter reliability is not the explanation either: `failed_decisions` totals
0–8 out of 480 decisions per model, so the fallback policy is not carrying or
sinking any row.

## 2. Cross-decision continuity costs the references exactly zero

Model rows run fresh-spawned with only a 2,000-character memo between decision
points. The scripted references are ordinary Python objects and could in
principle accumulate state across an episode, which would make part of the gap
"the reference remembered things the model was not allowed to remember".

Measured directly by re-instantiating the agent before every single decision:

| agent | persistent | fresh-spawn every decision | delta |
|---|---:|---:|---:|
| `pick-trader` seed 11 | 261.148 | 261.148 | 0.000 |
| `pick-trader` seed 12 | 242.660 | 242.660 | 0.000 |
| `pick-trader` seed 13 | 209.122 | 209.122 | 0.000 |

Bit-identical. All ten registered agents hold **zero** mutable instance state
and score identically when rebuilt each turn — the scripted policies rebuild
their plan from the observation every time, so they never had a continuity
advantage to remove.

This is now enforced rather than documented:
`tests/test_reference_statelessness.py` fails if any registered agent starts
carrying state, including a guard test that deliberately makes an agent stateful
to prove the check can fail.

**Consequence:** of the three scaffold factors named as uncontrolled in the
`ScaffoldViewAgent` docstring — view truncation, fresh-spawn/memo-only
continuity, and the output-token cap plus protocol repair — the first two are now
measured at approximately zero (view truncation: +2.8, *t* = 0.249, per the
2026-07-25 scaffold-view log). Only the output cap and repair budget remain
uncontrolled, and §1 bounds the repair-related part of that at under 9%.

## 3. Memo usage does not predict score

If cross-decision memory were the binding constraint, heavier memo use should
track higher scores. It does not:

| model | memo writes / 480 decisions | score |
|---|---:|---:|
| `z-ai/glm-5.2` | 568 | 217.5 |
| `anthropic/claude-sonnet-5` | 361 | 142.1 |
| `tencent/hy3:free` | 318 | 195.8 |
| `openai/gpt-5.6-luna` | 326 | 173.9 |
| `meta/muse-spark-1.1` | 229 | 231.9 |
| `qwen/qwen3.7-plus` | 219 | 175.5 |
| `minimax/minimax-m3` | 174 | 129.9 |
| `google/gemini-3.5-flash` | 3 | 215.6 |

The model that wrote 3 memos in 480 decisions placed third; the model that wrote
568 placed second; the heaviest-writing frontier model placed seventh. Taken with
§2 — references score 411.6 while using no cross-decision memory at all — the
evidence does not support memory as the bottleneck on this benchmark.

## 4. Panel power: within-seed noise dominates, and the split barely matters

`scripts/panel_power.py` decomposes committed episode scores into variance
components (8 models × 8 seeds × 3 repeats):

| component | sd (score points) | behaviour under matched-seed pairing |
|---|---:|---|
| seed difficulty | 13.45 | cancelled by pairing |
| model × seed | 0.00 | not distinguishable from zero |
| within-seed noise | 53.39 | survives pairing |

**Model run-to-run noise is ~4× league-difficulty variance.** The matched-seed
design — the central statistical device here — is cancelling the smaller of the
two components. This also means any single-run evaluation on this benchmark is
close to uninformative.

Because the interaction term is ~0, reallocating the 24-episode budget between
seeds and repeats does **not** change the standard error (15.41 in every split).
It changes only the degrees of freedom. Powers below are for a **single**
pairwise two-sided test at α=0.05:

| seeds × repeats | paired SE | min. detectable difference | power at Δ=40 |
|---|---:|---:|---:|
| 24 × 1 | 15.41 | 31.9 | **0.701** |
| 12 × 2 | 15.41 | 33.9 | 0.653 |
| 8 × 3 (current) | 15.41 | 36.4 | 0.591 |
| 6 × 4 | 15.41 | 39.6 | 0.510 |

So 24 × 1 is the better split at identical cost, but the gain is +0.11 power, not
a transformation. Observed pairwise model gaps run 1.6–102.0 with a median of
41.7, so at the current budget roughly half the pairs sit near or below the
detection threshold under any split.

Getting the median pair reliably separable needs budget, not just rebalancing:

| budget/model | best split | min. detectable | power at Δ=40 |
|---|---|---:|---:|
| 24 | 24 × 1 | 31.9 | 0.701 |
| 48 | 48 × 1 | 21.9 | 0.951 |
| 96 | 96 × 1 | 15.3 | 0.999 |

**Those single-test figures are not the bar `model_tiers.py` uses.** Tiering
defaults to Holm across every model pair (C(8,2) = 28 here). Planning under
that correction uses the first-step threshold α/28 ≈ 0.00179
(`scripts/panel_power.py --correction holm`):

| budget/model | best split | Holm min. detectable | Holm power at Δ=40 |
|---|---|---:|---:|
| 24 | 24 × 1 | 54.4 | 0.175 |
| 48 | 48 × 1 | 36.1 | 0.640 |
| 96 | 96 × 1 | 24.8 | **0.976** |

So a panel sized for publication tiering needs ~96 episodes/model at Δ=40, not
48. The seeds-versus-repeats ranking is unchanged (widest seed panel still
wins); only the budget call moves.

**Caveat that must travel with this:** repeats are the only way to estimate
within-seed sampling noise, which is a reported quantity (`within_seed_score_stddev`)
and is the largest component on this panel. A panel that wants both should keep
repeats on a small subset of seeds rather than dropping them entirely.

## What this does and does not authorise

- It does **not** pre-register a v3 panel or authorise spend. Changing
  `PRESETS["leaderboard"]` would move the contract fingerprint and invalidate the
  scaffold-view alignment established on 2026-07-25, so any panel change must be
  sequenced with a re-run of that free diagnostic.
- It does support stating the capability claim more strongly than the current
  framing: the gap is not protocol discipline (§1), not continuity (§2), not
  memory (§3), and not view truncation (2026-07-25 log).

## Reproduction

```bash
python3 scripts/panel_power.py                                      # §4 single-test table
python3 scripts/panel_power.py --correction holm --budget 96        # §4 Holm sizing
python3 scripts/panel_power.py --budget 48 --json
python3 -m pytest tests/test_panel_power.py tests/test_reference_statelessness.py -q
```
