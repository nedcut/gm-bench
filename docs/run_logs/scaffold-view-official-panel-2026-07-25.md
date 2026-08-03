# scaffold-view official panel — 2026-07-25

Deterministic measurement for Issue [#93](https://github.com/nedcut/gm-bench/issues/93):
`scaffold-view` versus `pick-trader` on the official held-back leaderboard
panel under the current contract. This bounds observation-asymmetry between
the truncated model view and the full scripted reference; it does **not**
re-rank models or change the public leaderboard.

## Run configuration

| Field | Value |
| --- | --- |
| Contract fingerprint | `4f6ddddd6a6dd81c` |
| Seeds | 11, 12, 13, 14, 15, 16, 17, 18 |
| Seasons | 5 |
| Preset alignment | Same seed panel and season count as `PRESETS["leaderboard"]` |
| Command | `python3 -m gm_bench compare --agents scaffold-view pick-trader --seeds 11 12 13 14 15 16 17 18 --seasons 5 --no-log` |
| Branch / commit | `feat/contract-economics` at `2f3e945c78c45b3699839f43561db7710d4429af` (fingerprint `4f6ddddd6a6dd81c`) |

Both agents are scripted, CPU-only, and deterministic (one repeat per seed).

## Headline means

| Agent | Mean score |
| ---: | ---: |
| `scaffold-view` | 270.675 |
| `pick-trader` | 267.875 |
| Paired mean difference (`scaffold-view` − `pick-trader`) | +2.800 |

## Per-seed scores

| Seed | `scaffold-view` | `pick-trader` | Difference |
| ---: | ---: | ---: | ---: |
| 11 | 261.148 | 261.148 | 0.000 |
| 12 | 242.660 | 242.660 | 0.000 |
| 13 | 209.122 | 209.122 | 0.000 |
| 14 | 266.151 | 266.151 | 0.000 |
| 15 | 328.967 | 328.967 | 0.000 |
| 16 | 330.780 | 330.780 | 0.000 |
| 17 | 298.696 | 228.761 | +69.935 |
| 18 | 227.874 | 275.407 | −47.533 |

Six of eight seeds are identical under the shared `pick-trader` policy; the
remaining two seeds (17 and 18) diverge because truncation changes which
candidates the policy can see. The +2.8 headline mean is therefore entirely
driven by those two seeds (seeds 11–16 are exact ties).

## Paired comparison

- **Paired mean difference:** +2.800 (same as the gap in headline means on this
  balanced 8-seed panel).
- **Paired *t* (one-sample on seed differences, *n* = 8):** 0.249 — far from
  conventional significance; with only two non-zero differences the test has
  almost no power.
- **Sign summary:** 1 seed higher, 1 seed lower, 6 seeds tied (exact zero
  difference).

## Interpretation

Under contract `4f6ddddd6a6dd81c`, running the transparent `pick-trader`
heuristic on the same truncated observation a model adapter receives
(`scaffold-view`) versus the full simulator observation (`pick-trader`) moves
the 8-seed panel mean by **+2.8 points** (~1.0% of the `pick-trader` mean).

That gap is a **diagnostic bound on observation asymmetry** for the official
panel. It is not evidence that any model should move up or down the leaderboard:
model rows still mix policy quality with this asymmetry, and this run does not
substitute for a model evaluation. Quote these numbers only alongside the
fingerprint above; any contract-source change invalidates the comparison.

## Re-measurement note (2026-07-25)

PR [#92](https://github.com/nedcut/gm-bench/pull/92) absorbed contract-economics
polish fixes that moved the fingerprint from `0a5f0434dca31ac5` to
`4f6ddddd6a6dd81c`. This branch was rebased onto the updated
`feat/contract-economics` tip and the compare was re-run. Headline means,
per-seed scores, and paired *t* are unchanged on the official panel; only the
fingerprint and economics commit reference above were updated.

## Revalidation under the `sota-v3` candidate fingerprint (2026-08-03)

`docs/PUBLISH_READINESS.md` requires this diagnostic to be rerun or explicitly
revalidated under the fingerprint a paid smoke would actually run on. The
figures above were measured under `4f6ddddd6a6dd81c`; the `sota-v3` candidate
contract is `a523bdfcebe47bbd`. The compare was therefore re-run unchanged:

| Field | Value |
| --- | --- |
| Contract fingerprint | `a523bdfcebe47bbd` |
| Branch / commit | `amend/sota-v3-cohort-10` at `88ab7df191ef4d8e3ec4921a3e374e51d7fcc91c` |
| Command | `python3 -m gm_bench compare --agents scaffold-view pick-trader --seeds 11 12 13 14 15 16 17 18 --seasons 5 --no-log` |
| Spend | $0.00 — both agents are scripted and CPU-only |

**Every number above reproduces exactly.** Headline means 270.675 and 267.875,
paired mean difference +2.800, paired *t* 0.249, and all eight per-seed scores
match the `4f6ddddd6a6dd81c` measurement to the recorded precision, including
the two divergent seeds (17: +69.935, 18: −47.533) and the six exact ties.
Neither agent reads a field the intervening contract changes touched, so the
observation-asymmetry bound carries forward unaltered.

This revalidates the bound; it does not widen the claim. The +2.8 gap remains
diagnostic, remains driven entirely by seeds 17 and 18, and still may not be
used to re-rank any model. `scaffold-view` stays outside
`PRESETS["leaderboard"]`.
