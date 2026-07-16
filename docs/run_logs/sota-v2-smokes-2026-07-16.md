# sota-v2 fixed-cap smoke ledger — 2026-07-16

This ledger summarizes the serial pre-panel smokes under the frozen 1,024-token,
reasoning-disabled API lane. Raw artifacts, checkpoints, and provider-attempt
evidence remain under
`data/publication-runs/smoke-fixed-1024-2026-07-16/` outside Git. A valid but
poor model response is never rerun merely to obtain a cleaner result.

| Model | Route | Outcome | Cost | Evidence |
| --- | --- | --- | ---: | --- |
| Qwen 3.5 9B | DeepInfra | Accepted | $0.004227 | 4/4 decisions, zero failures or repairs, 5/5 finish reasons, zero truncations or reasoning tokens, peak 428 output tokens. Recorded in `config/sota_v2_smoke_manifest.json`. |
| Nemotron 3 Nano 30B A3B | DeepInfra | Infrastructure attempt 1 aborted | $0 incremental | Two consecutive `HTTP 405 Method Not Allowed` responses before a complete episode. The exact endpoint still appeared healthy and parameter-capable in the live OpenRouter catalog. Checkpoint retained; one infrastructure retry remains. |
| MiniMax M3 | MiniMax | Completed, ineligible | $0.011866 | 4/4 metered decisions but one failed decision: the draft response was not a JSON action array and the one bounded repair also failed, causing one fallback. Zero truncations or reasoning tokens; peak 261 output tokens. Frozen policy forbids a rerun for this model behavior. |
| Qwen 3.7 Plus | Alibaba | Accepted | $0.013661 | 4/4 decisions, zero failures or repairs, 5/5 finish reasons, zero truncations or reasoning tokens, peak 271 output tokens. Recorded in `config/sota_v2_smoke_manifest.json`. |
| Kimi K2.6 | DeepInfra | Accepted | $0.024844 | 4/4 decisions, zero failures or repairs, 4/4 finish reasons, zero truncations or reasoning tokens, peak 289 output tokens. The changed route passed and was recorded in `config/sota_v2_smoke_manifest.json`. |
| GLM 5.2 | StreamLake | Completed, ineligible | $0.021550 | 4/4 metered decisions but one failed decision: the model JSON did not contain typed actions and the one bounded repair also failed, causing one fallback. Zero truncations or reasoning tokens; peak 414 output tokens. Frozen policy forbids a rerun for this model behavior. |
| DeepSeek V4 Pro | DeepInfra | Accepted on infrastructure attempt 2 | $0.051511 | Attempt 1 received two consecutive `HTTP 429 Too Many Requests` responses with no incremental spend and retained its checkpoint. The resumed final infrastructure attempt completed with 4/4 decisions, zero failures or repairs, 5/5 finish reasons, zero truncations or reasoning tokens, and a peak of 305 output tokens. Recorded in `config/sota_v2_smoke_manifest.json`. |
| GPT-5.6 Luna | OpenAI | Accepted | $0.039452 | 4/4 decisions, zero failures or repairs, 4/4 finish reasons, zero truncations or reasoning tokens, peak 144 output tokens. Recorded in `config/sota_v2_smoke_manifest.json`. |
| Mistral Medium 3.5 | Mistral | Accepted | $0.056330 | 4/4 decisions, zero failures or repairs, 4/4 finish reasons, zero truncations or reasoning tokens, peak 299 output tokens. One illegal action remains measured model behavior and does not invalidate smoke infrastructure. Recorded in `config/sota_v2_smoke_manifest.json`. |
| Claude Sonnet 5 | Anthropic | Preflight attempt 1 blocked | $0 | The exact registered Anthropic endpoint remains in the catalog but currently reports unhealthy status `-2`; healthy Azure, Bedrock, and Google routes are not permitted substitutes. No reservation or model request was made. Retry only if the pinned Anthropic endpoint returns healthy. |

Current artifact-reported run-directory spend: **$0.223441**. The conservative
reservation ledger additionally retains the failed Nemotron attempt.
