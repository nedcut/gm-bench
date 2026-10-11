# Experimental counterfactual draft lab

This offline diagnostic is a separate experimental track. It does not change or
populate GM-Bench 1.0/2.0 contracts, scores, leaderboard artifacts or evaluation
panels. A value means **this action among these candidates, under this continuation
policy**, conditional on this simulator checkpoint. It is not an optimal-policy
oracle or a benchmark score claim.

## Run an end-to-end comparison

From an installed checkout (no provider, credential, network or paid model needed):

```sh
python3 -m gm_bench.counterfactual checkpoint --seed 1 --season 1 --out /tmp/draft.json
python3 -m gm_bench.counterfactual compare /tmp/draft.json \
  --limit 6 --rollouts 8 --horizons 1 2 3 --out /tmp/draft-comparison.json
```

Open the JSON's `candidates`, `summaries` and `rows`. Candidate 0 is the explicit
reference; each summary includes score, downstream wins, and paired score delta
against that reference. Larger scores are better. A horizon is the number of
season completions after the checkpoint, so horizon 1 covers only the remaining
part of the current season. Downstream wins exclude games already won at capture.
`score` is the frozen simulator's total state score at that horizon, including
shared history. It is not a separately calibrated decision-quality scale.

To supply choices, write a JSON array containing 2–12 actions of the form
`{"type":"draft","prospect_id":123}` using IDs from the checkpoint's public
`observation.draft_class`, then pass `--candidates /tmp/actions.json`. All actions
must be distinct legal draft picks. The default takes the top published prospects
by the existing public asset heuristic, with ID tie-breaking; it is intentionally
not an exhaustive search. Results depend on this truncation. Drafting was chosen
because the simulator exposes discrete prospects and directly checks availability
and pick ownership. No other decision family is currently supported.

## Checkpoints and continuation

`make_checkpoint(seed, season)` supports only public development seeds 1–32 and
seasons 1–3, at the first user draft window after opponent picks ahead of the user.
The prefix uses the existing ValueAgent, one action batch per decision window.
The checkpoint contains the public observation, prefix action/results transcript,
a full-state SHA-256 digest, source/contract/Python provenance and content ID.
It contains no serialized hidden player attributes, pickle or executable payload.
A public seed necessarily makes the simulated world reconstructible: these files
are for public/dev research, never private-panel seed storage or publication.

Loading regenerates the deterministic prefix and compares the *entire* checkpoint,
including observation, full-state digest, transcript and provenance. The capture
recipe deliberately supports this prefix policy, not arbitrary live game saves.
Replay requires the same Python patch version and source fingerprint. Hashes detect
accidental edits and compatibility mismatch; they are not authenticity signatures.

Each initial candidate replaces the entire first draft-window action batch: only
that one draft action is applied, with no extra user signing or lineup action.
Opponent drafting/autopilot and season completion then proceed normally. From
the next season onward every branch uses `value-one-batch-per-window-v1`, which
re-observes each branch and invokes a fresh stateless ValueAgent at every phase.
Matching means the same policy function, not identical actions in different states.
Deep copies isolate every branch and legality probe. Candidate application must
consume zero simulator RNG streams. No frozen engine code is modified.

## Randomness and uncertainty

Independent pseudorandom rollout seeds 1001–1032 salt only downstream `League._rng`
streams. Candidate branches within a rollout share stream seeds, namespaces and
starting offsets. The original league seed is unchanged: existing hidden player
attributes, future generated draft classes, direct seed-keyed incoming offers,
contract reservations, partner valuations and scout noise remain fixed. Thus this
samples downstream simulation randomness conditional on a fixed world, **not** a
posterior over hidden ability or a population of independent league episodes.

The audit records every instrumented namespace/offset and primitive `random()` and
`getrandbits()` consumption, including bit totals. Instrumentation preserves the
underlying `Random` sequence. Direct seed-keyed streams are outside this audit.
Different injury thresholds, lineup ordering, roster changes or opponent behavior
can assign the same draws to different events or consume different numbers of
draws. **Event-level common random numbers are not guaranteed**, even when primitive
counts agree. `primitive_consumption_equal` is a diagnostic, not a validity proof.
These are paired stream seeds; no variance reduction claim is made.

Uncertainty is computed across complete independent downstream rollout streams,
with paired differences within each seed. Correlated seasons/horizons are not
additional samples. The reported standard error and normal 95% interval are
approximate Monte Carlo summaries, especially weak with few rollouts; one rollout
has a null SE/interval. They do not include checkpoint-selection uncertainty,
candidate-selection uncertainty, simulator misspecification or policy uncertainty.
Selecting the best estimated candidate can introduce selection optimism.

## Bounds and schemas

Maximum work per comparison: 12 candidates × 32 rollouts × 3 season completions;
prefix length is at most 3 seasons. Default work is 6 × 8 × 3. Input JSON is capped
at 32 MB. Output is deterministic (no wall-clock timing). Runtime depends on the
machine; CLI calls in tests have a 30-second timeout for their small smoke fixture.
The hard simulation-count limits, not that smoke timeout, bound library work.

- `schemas/counterfactual_checkpoint.schema.json`: capture recipe and provenance.
- `schemas/counterfactual_comparison.schema.json`: embedded checkpoint, actions,
  horizons, seed panel, per-rollout rows, uncertainty summaries and RNG audits.
- `checkpoint_id` / `comparison_id`: SHA-256 of canonical JSON excluding that ID.
- `state_sha256`: exact internal state digest for replay checks, not a public state.

Python API: `make_checkpoint`, `replay_checkpoint`, `enumerate_candidates`,
`compare`, `read_json`, `save_json`. JSON Schema checks structure; replay performs
semantic checkpoint validation. Public experiment/viewer consumers should use the
versioned exports and leave the frozen benchmark result schema unchanged.
