# sota-v2 final launch audit — 2026-07-18

An independent read-only Claude Fable 5 review of merged commit `0f12f21`
returned **GO WITH CONDITIONS** and found no P0 launch blocker. It verified the
ten-model registry, exact-route smoke manifest, GLM Novita amendment, serial
runner, endpoint preflight, resume behavior, status reporting, and publication
locks. Two pre-launch conditions were accepted:

1. reconcile the stale 1,024/768/2,048 policy text in
   `config/publication_protocol.json` with the machine-enforced and
   smoke-validated 4,096/3,072/8,192 native-minimum-reasoning lane; and
2. account for the configured bounded protocol repair in the per-cell spend
   reservation, not only the primary call.

Both conditions were resolved before any full-panel result. The protocol now
records the current lane as a pre-data amendment. The serial runner now reserves
every configured repair attempt as another full-price call and applies the
committed 1.2x cost contingency before a cell may start. Failed or interrupted
reservations remain active; successful cells settle to measured spend.

Using each accepted smoke's measured spend scaled by the panel's 120x decision
ratio, the expected full-panel spend is **$46.7742**. Simulating registry order
with the strengthened reservations produces a maximum expected commitment of
**$89.3659** immediately before Mistral. A **$95 operator ceiling** therefore
keeps authorization below the user's $100 limit while leaving approximately
$5.63 above that conservative expected commitment.

The ceiling is a cell-boundary guard, not a provider-side billing limit. The
reservation assumes 8,000 input tokens per decision, the frozen 4,096-token
output cap, every configured repair call, and 1.2x contingency. The operator
must monitor measured spend after every cell and stop on unexpected divergence.

Final operational conditions:

- use a fresh panel run directory and one serial runner process;
- confirm `GM_BENCH_PRIVATE_SEEDS` is unset;
- avoid unrelated OpenRouter usage during account-delta measurement;
- start promptly and complete the free Tencent HY3 cell before its July 21
  catalog expiration; and
- keep the status watcher open and review measured spend after each cell.
