# Decision-model lane: typesafe/jev-1.13-20260917

Lane `decision-api`, provider `typesafe`, route `openrouter`, contract `a600b7da0c302231`, scaffold `e1fc1e298283f465`, 29-seed private panel `a21edc686a579b90`. Recomputed from the operator's local raw artifact; every number below is aggregate.

This row is not in the sota-v5 Holm family. Its score measures the model plus the question scaffold in `examples/typesafe_jev_agent.py`; the comparison it supports is against the scripted baselines, not against the headline chat-lane rows.

## Score and contrasts

Mean score 229.000 (sd 41.145) over 580 decisions, 0 failed, 8 illegal actions.

Against the baseline panel mean (175.303): paired lift 53.70 (95% CI 37.52 to 69.49), seed win rate 0.862.

Against pick-trader (247.109): mean paired lift -18.11 (sd 53.90), 9 of 29 seeds won, unadjusted exact sign-flip p 0.0812 (does not reject at 0.05, unadjusted).

| baseline | baseline mean | mean paired lift | lift sd | seeds won | sign-flip p |
| --- | ---: | ---: | ---: | ---: | ---: |
| pick-trader | 247.1 | -18.11 | 53.90 | 9/29 | 0.0812 |
| strategic | 242.3 | -13.33 | 53.42 | 11/29 | 0.1911 |
| shrewd | 228.5 | 0.53 | 55.95 | 16/29 | 0.9605 |
| win-now | 178.0 | 50.98 | 54.18 | 25/29 | 0.0000 |
| value | 173.1 | 55.93 | 56.10 | 25/29 | 0.0000 |
| conservative | 122.7 | 106.27 | 43.19 | 29/29 | 0.0000 |
| rebuild | 121.9 | 107.11 | 43.84 | 29/29 | 0.0000 |
| random | 88.8 | 140.20 | 47.02 | 29/29 | 0.0000 |

## Robustness and power (pick-trader contrast)

Leave-one-seed-out over 29 folds: fold-mean lift range 9.03, p from 0.0086 to 0.1419, 2 rejection flip(s) (fragile).

Minimum detectable difference at alpha 0.05 and power 0.8: 28.0 points observed against the 30-point figure the sota-v5 analysis assumes (within the assumed figure).

## Weight sensitivity

With 200 draws of independent uniform multipliers in [0.70, 1.30] on the score weights, the candidate's canonical rank among the nine rows is 3 (pick-trader > strategic > typesafe:typesafe/jev-1.13 > shrewd > win-now > value > conservative > rebuild > random); the highest adjacent flip probability involving the candidate is 0.425; Kendall tau mean 0.976 (p05 0.944).

## Efficiency

| model | mean score | cost USD | USD/decision | s/decision | API s/call | input tokens/decision | reported output tokens/decision |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| typesafe/jev-1.13-20260917 | 229.0 | 0.33 | 0.00057 | 0.49 | 0.42 | 13674 | 1326 |

Output tokens are reported by the gateway for a model that generates no text and are billed at zero; the recorded cost reproduces from input tokens alone.
