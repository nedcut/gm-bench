# SOTA-v4 initial preregistration — 2026-08-12

## Scope and evidence boundary

This is an initial, fail-closed preregistration package created after the
terminal SOTA-v3 strict-smoke outcome and before any SOTA-v4 model result. It
made no authenticated request, read no provider credential or private seed,
and called no completion endpoint. Public OpenRouter endpoint metadata was
read at `2026-08-12T20:03:16Z`; those records are candidate metadata, not route
or privacy acceptance.

The initial package unlocked nothing. After local cross-file validation and
generation of `results/analysis/sota-v4-pre-smoke-cost-estimate.json`, the
preregistration is now frozen for an authenticated zero-completion-call route
preflight only. The registry remains `route-preflight-ready`, rather than
frozen, until new v4 exact-route and privacy acceptance exists. Spend, strict
smoke, panel execution, and publication remain false. The smoke manifest is
empty, final preflight evidence is unresolved, and no SOTA-v3 route, privacy,
smoke, final-preflight, panel, or leaderboard artifact is reused as SOTA-v4
evidence.

## Eight-model family

The family remains eight models so the proposed Holm family and unused 16-seed
commitment retain their declared dimensions:

1. `openai/gpt-5.6-luna`
2. `anthropic/claude-sonnet-5`
3. `upstage/solar-pro4`
4. `minimax/minimax-m3`
5. `qwen/qwen3.8-max`
6. `mistralai/mistral-medium-3-5`
7. `deepseek/deepseek-v4-flash-0731`
8. `tencent/hy3`

The owner-directed external-selection rule replaces the terminal GLM 5.2 slot
with the new `upstage/solar-pro4` identity before any v4 result exists. The
public catalog exposed one candidate route,
`Upstage | upstage/solar-pro4-20260810` at tag `upstage`: status 0, unknown
quantization, 131,072 maximum completion tokens, 100% 30-minute and 24-hour
uptime, and the required `reasoning`, `max_tokens`, and `response_format`
parameters. Its live rates were 90% discounted (`$0.03/M` prompt and
`$0.12/M` completion), so the provisional pricing snapshot records the
policy-required undiscounted list rates of `$0.30/M` and `$1.20/M`.
Authentication, privacy, reasoning-disabled behavior, and request behavior
remain unresolved.

## Route decisions

MiniMax keeps the same `minimax/minimax-m3` model and FP8 precision but returns
to `Minimax | minimax/minimax-m3-20260531` at tag `minimax/fp8`. Under
[`docs/ROUTE_SUBSTITUTION_POLICY.md`](../ROUTE_SUBSTITUTION_POLICY.md), that
publicly eligible route had the highest 24-hour uptime among same-model FP8
candidates: status 0, 512,000-token maximum, 96.5401% 30-minute uptime, and
99.6508% 24-hour uptime. This is a proposed route only; prior first-party or
DeepInfra evidence does not carry forward.

Qwen remains on its only public same-model endpoint,
`Alibaba | qwen/qwen3.8-max-20260803` at tag `alibaba`. The endpoint was
publicly healthy (status 0, 131,072-token maximum, 99.9797% 30-minute and
99.9994% 24-hour uptime) and advertised the common parameters, but that does
not explain or resolve the two terminal SOTA-v3 HTTP 400 attempts. Request
compatibility is an explicit blocker before any v4 paid authorization.

The other five identities retain their proposed v3 route names only as public
catalog candidates. Every route must receive new authenticated exact-route and
privacy evidence under v4.

## Seed commitment lineage

No SOTA-v3 panel was run, so its exact 16-seed private commitment remains
unused. SOTA-v4 carries forward, without reading the secret or salt:

- ordered seed hash:
  `291fa61cc3dfd8b23fdd79cce3c80a0a98f918f6c8757d35c21b4d8131cc6099`
- salted hiding commitment:
  `7f8da7ca4db4a698ea2b0506af8568c89744e18508d8dedbfeb1c87e90a2b5f8`
- escrow identity: `macos-keychain:gm-bench-sota-v3-private-panel`

The v4 lane records that exact v3 lineage, `seed_values_included: false`, and
`secret_values_read_for_v4_preregistration: false`. Because the Holm family
remains eight, the frozen pre-data 16x1 selection remains coherent: sensitivity
power 0.8727 with Wilson 95% interval `[0.866024, 0.87909]`, above the 0.80
target. This freezes the statistical design, not panel execution.

## Cost boundary

The generated cost artifact binds the frozen public list-rate snapshot to this
eight-model family. Its one-response-per-window smoke forecast is `$0.667548672`;
the protocol maximum, including all five interaction rounds and one permitted
repair, is `$6.67548672`. The owner-set `$100` smoke operator ceiling easily
covers that maximum. It is a future hard limit, not permission to spend, and it
does not cover or authorize the `$534.0389376` protocol-maximum panel estimate.

## Required next gates

1. Run the authorized authenticated zero-completion route and privacy preflight
   for all eight proposed routes.
2. Resolve Qwen request compatibility without consuming a paid strict-smoke
   attempt.
3. Produce a digested zero-call final preflight before any separate smoke
   authorization.

Until those gates pass, SOTA-v4 authorizes no paid execution.
