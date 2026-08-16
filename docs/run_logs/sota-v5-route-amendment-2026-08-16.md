# SOTA-v5 pre-data Gemini route amendment — 2026-08-16

This is a pre-data preregistration amendment. Authenticated OpenRouter metadata
was read for this decision, including the credits endpoint and the Gemini route
catalog; no completion, smoke, panel, Keychain, private-seed, or provider model
call was made. The failed all-route collector stopped before writing an
acceptance artifact, so exact-route acceptance remains pending.

## Decision

The registered `google/gemini-3.7-flash` identity moves from the provisional
`google-vertex/global` route to the exact `google-ai-studio` route:

| Field | Frozen value |
| --- | --- |
| Model id | `openrouter-gemini-3.7-flash-google-ai-studio` |
| Upstream provider | `Google AI Studio` |
| Provider slug / endpoint tag | `google-ai-studio` |
| Endpoint name | `Google AI Studio | google/gemini-3.7-flash-20260813` |
| Route status | `0` |
| Quantization | `unknown` |
| Maximum completion tokens | `65,536` |
| Last-30-minute uptime | `99.31597947938438` |
| Last-24-hour uptime | `99.6568375762854` |
| Prompt rate | `$0.00000075/token` |
| Completion rate | `$0.00000375/token` |
| Internal-reasoning rate | `$0.00000375/token` |
| Catalog discount | `0` |

Google AI Studio is selected because it has the highest supplied public
24-hour uptime among the eligible exact routes for this model identity:
`99.6568375762854` versus `99.46602224161464` for `google-vertex/global`.
Price is explicitly excluded from the route-selection rule. The common
reasoning-disabled policy, 4,096-token request cap, eight-model family, seed
commitment, and statistical plan are unchanged.

## Authorization boundary

This amendment changes only pre-data route identity and planning-price
metadata. Exact-route acceptance remains pending authenticated zero-call
preflight. Spend, strict smoke, panel, analysis, release, and publication
authorization remain `false`; the smoke manifest remains empty and
`accepted_for_panel` remains `false`.

The route's supported parameters, privacy acceptance, request-cap behavior,
reasoning-disabled behavior, and authoritative billing remain unresolved until
the separately authorized zero-completion preflight and later owner-approved
strict smoke.
