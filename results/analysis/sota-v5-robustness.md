# sota-v5 robustness, power, and efficiency

Primary contrast: paired lift versus pick-trader. 29 paired seeds, Holm family size 16. Recomputed from the operator's local raw artifacts; every number below is aggregate.

## Minimum detectable difference

At alpha 0.05 and power 0.8 over 29 paired seeds, the observed per-model detectable difference runs 22.356 to 31.488 points (median 24.374), against the 30.0-point figure the analysis assumes.

Rows above the assumed figure: openrouter-gpt-5.6-luna-openai.

## Leave-one-seed-out

Each of the 29 folds drops one panel position from every model at once and recomputes the exact sign-flip test on the remaining 28 seeds, with the Holm family held at 16. Rejection status flips for: openrouter-gemini-3.7-flash-google-ai-studio.

google/gemini-3.7-flash is the fragile row: its Holm-adjusted p is 0.221066 on the full panel, but across the 29 folds it ranges 0.028274 to 0.424192, and 1 fold(s) cross 0.05. A single seed sustains the non-rejection.

| model | mean lift | lift sd | Holm reject | LOO mean lift range | flips | MDD |
| --- | ---: | ---: | :---: | ---: | ---: | ---: | ---: | ---: |
| google/gemini-3.7-flash | -23.40 | 57.54 | no | 9.93 | 1 | 29.9 |
| x-ai/grok-4.6 | -43.58 | 49.34 | yes | 8.32 | 0 | 25.7 |
| openai/gpt-5.6-luna | -75.81 | 60.53 | yes | 8.81 | 0 | 31.5 |
| z-ai/glm-5.3-flash | -83.87 | 46.85 | yes | 6.31 | 0 | 24.4 |
| moonshotai/kimi-k2.5 | -97.88 | 45.93 | yes | 7.32 | 0 | 23.9 |
| google/gemini-3.1-flash-lite | -101.52 | 43.38 | yes | 6.31 | 0 | 22.6 |
| x-ai/grok-4.3 | -112.09 | 42.97 | yes | 6.83 | 0 | 22.4 |
| deepseek/deepseek-v4-flash-0731 | -122.21 | 44.12 | yes | 6.89 | 0 | 23.0 |
| openai/gpt-5.4-mini | -123.12 | 48.12 | yes | 7.22 | 0 | 25.0 |
| minimax/minimax-m3 | -130.11 | 43.17 | yes | 7.20 | 0 | 22.5 |
| qwen/qwen3.5-27b | -133.41 | 47.11 | yes | 6.38 | 0 | 24.5 |

## Efficiency

| model | mean score | cost USD | USD/decision | s/decision | tokens/decision | out tokens/decision |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| google/gemini-3.7-flash | 223.7 | 1.88 | 0.00325 | 2.34 | 6729 | 481 |
| x-ai/grok-4.6 | 203.5 | 9.18 | 0.01582 | 12.76 | 6541 | 742 |
| openai/gpt-5.6-luna | 171.3 | 0.43 | 0.00073 | 3.13 | 5418 | 119 |
| z-ai/glm-5.3-flash | 163.2 | 0.60 | 0.00104 | 15.04 | 5878 | 451 |
| moonshotai/kimi-k2.5 | 149.2 | 1.58 | 0.00272 | 5.12 | 5507 | 158 |
| google/gemini-3.1-flash-lite | 145.6 | 0.46 | 0.00079 | 1.09 | 5879 | 90 |
| x-ai/grok-4.3 | 135.0 | 3.52 | 0.00607 | 0.91 | 5073 | 39 |
| deepseek/deepseek-v4-flash-0731 | 124.9 | 0.44 | 0.00075 | 1.70 | 5332 | 87 |
| openai/gpt-5.4-mini | 124.0 | 2.45 | 0.00422 | 1.56 | 5124 | 102 |
| minimax/minimax-m3 | 117.0 | 2.10 | 0.00363 | 2.01 | 5314 | 115 |
| qwen/qwen3.5-27b | 113.7 | 0.99 | 0.00170 | 6.70 | 5888 | 130 |

Season- and mechanic-held-out robustness is not possible for v5: publication.mechanic_breakdown carries accepted/rejected counts only, and no per-seed score decomposition by season or mechanic is persisted, so a mechanic-held-out lift cannot be formed.
