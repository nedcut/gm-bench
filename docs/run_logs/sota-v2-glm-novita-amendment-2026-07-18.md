# sota-v2 GLM 5.2 route amendment — 2026-07-18

Repeated launch preflights found the frozen first-party Z.AI FP8 endpoint for
`z-ai/glm-5.2` unhealthy in OpenRouter's live catalog (`status: -2`). No
full-panel GLM result existed, so the registry was amended before panel data to
the exact dated Novita FP8 endpoint:

- provider slug and endpoint tag: `novita/fp8`
- endpoint name: `Novita | z-ai/glm-5.2-20260616`
- reasoning: disabled, unchanged from the prior route
- output cap: 4,096 tokens, unchanged
- fallbacks: disabled

The replacement endpoint passed live catalog and authentication preflight. Its
serial benchmark smoke then completed all four decisions with zero failed
decisions, zero truncations, complete usage and finish-reason telemetry, and
exact Novita provenance. Peak output was 325 tokens, safely below the 3,072-token
cap-pressure threshold. Artifact-reported spend was **$0.009225** and API time
was 32.1795 seconds, or 8.045 seconds per decision.

The accepted artifact is retained outside Git at
`data/publication-runs/smoke-glm-novita-4096-2026-07-18/raw/openrouter-glm-5.2-novita--4096.json`
with SHA-256
`244ae595503e2288ac4051c5f8c10b9ebff46eb159924b14a668c43541e88c52`.
The superseded Z.AI artifact remains retained as historical evidence but no
longer unlocks the current registry.

Replacing the $0.047053 Z.AI smoke with this $0.009225 Novita smoke brings the
current ten-route accepted-smoke total to **$0.389785**. Scaling observed smoke
spend by the panel's 120x decision-count ratio gives an empirical panel estimate
of **$46.7742**; the operator ceiling remains authoritative and may stop the run
before completion if measured spend diverges upward.
