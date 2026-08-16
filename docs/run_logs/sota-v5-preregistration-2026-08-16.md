# SOTA-v5 successor preregistration — 2026-08-16

## Decision

SOTA-v4 is terminal. Its Qwen/Alibaba slot exhausted the permitted
infrastructure attempts after the endpoint returned HTTP 400 because reasoning
was mandatory, so v4 cannot produce a uniform reasoning-disabled eight-model
panel. SOTA-v5 is a new, outcome-independent contract. It does not reopen v4,
reuse v4 results, or treat the Qwen failure as a model ranking observation.

The v5 family retains the seven non-Qwen v4 identities and replaces Qwen with
`google/gemini-3.7-flash` on the provisional `google-vertex/global` route. The
replacement was selected from public OpenRouter catalog metadata before any v5
route, smoke, panel, or result evidence.

The frozen replacement rule first requires a stable exact, general-purpose
text model with optional reasoning, an advertised disabled path,
`response_format`, `max_tokens`, and at least 4,096 completion tokens. It then
prefers the missing Google frontier family: the seven retained identities
already cover OpenAI, Anthropic, Upstage, MiniMax, Mistral, DeepSeek, and
Tencent, while the published phase-one panel treated Google as a distinct
frontier anchor. Within that identity, the route rule selects the eligible
endpoint with the highest public 24-hour uptime, followed by newest stable
snapshot and lexicographic model-id tie-breaks. Price, latency, throughput,
OpenRouter popularity, GM-Bench scores, and candidate completions are excluded
selection inputs.

## Frozen pre-data design

- Provider and lane: OpenRouter gateway API, compact fresh-spawn API lane.
- Cohort: eight exact model identities/routes in
  `config/sota_v5_models.json`.
- Reasoning policy: disabled for every model; `OPENROUTER_REASONING_ENABLED=false`
  and no reasoning-effort option. Mandatory reasoning, cap pressure, unknown
  cost, or route incompatibility terminates v5 and requires a new
  preregistration.
- Output ceiling: 4,096 tokens per response; cap-pressure threshold 3,072;
  no in-place cap amendment.
- Repair policy: one protocol repair, serialized provider execution, maximum
  two infrastructure attempts per cell. Model behavior never authorizes a
  rerun; unknown charges are reconciled before any retry.
- Panel: hidden 16-seed × 1-repeat commitment, 16 episodes per model, with
  exact two-sided sign-flip tests and Holm-Bonferroni adjustment over eight
  registered contrasts at alpha 0.05.
- Primary contrast: paired model lift versus deterministic `pick-trader`;
  no ordinal ranking or model tiers are preregistered.
- Cost planning: the protocol-maximum smoke estimate is `$5.47964672`, or
  `$6.575576064` with the 1.2x contingency, below the owner-set `$10` smoke
  ceiling. The panel remains separately unauthorized and is estimated above
  that ceiling.

## Seed lineage and attestation

The exact hidden 16-seed commitment is carried forward unchanged from v3
through v4 into v5:

- seed-list SHA-256:
  `291fa61cc3dfd8b23fdd79cce3c80a0a98f918f6c8757d35c21b4d8131cc6099`;
- hiding commitment SHA-256:
  `7f8da7ca4db4a698ea2b0506af8568c89744e18508d8dedbfeb1c87e90a2b5f8`;
- escrow: `macos-keychain:gm-bench-sota-v3-private-panel`.

This lineage is not evidence that the panel was run. The v5 lane requires an
owner attestation before seed access confirming that the commitment and seed
values remain unused, that no v3 or v4 panel read them, and that v5 will use
the exact committed values without substitution. The preregistration contains
no seed values and reads no secret material.

## Spend and evidence boundary

All v5 spend, smoke, panel, and publication authorizations are false. Route
preflight is the only enabled phase, and it is limited to authenticated route,
privacy, and pricing metadata with zero completion calls. The registry's exact
route acceptance is intentionally `pending-authenticated-zero-call-preflight`;
public catalog data is not treated as authenticated evidence.

Paid smokes require a later, explicit owner decision after fresh route
preflight, a seed-free smoke-command dry run, exact-head CI, and cost
reconciliation. The v5 smoke path does not read Keychain; commitment
verification and seed access are deferred until the owner attests before the
private panel. Each
model's smoke must be accepted independently before a separate panel decision.
No paid smoke was run while preparing this package.

## Source artifacts

- `config/sota_v5_lane.json`
- `config/sota_v5_models.json`
- `config/sota_v5_publication_protocol.json`
- `config/sota_v5_pricing_snapshot.json`
- `config/sota_v5_smoke_manifest.json`
- `results/analysis/sota-v5-pre-smoke-cost-estimate.json`
- `tests/test_sota_v5_preregistration.py`

The public catalog snapshot was collected with unauthenticated GET requests to
`https://openrouter.ai/api/v1/models` and the public Gemini endpoint metadata
route. No authentication, Keychain, completion endpoint, or provider secret
was used. Future route/privacy acceptance is a point-in-time, URL-based
operator attestation over authenticated metadata; it records policy locations
and retrieval time, not a versioned copy of provider policy text.
