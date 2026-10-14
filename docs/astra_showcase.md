# Astra selected best-case showcase

This derived account selects episode index 28 of the published Astra artifact
because it is the highest final score among the site's 320 comparable episodes
in ten published 2.0 panel rows. It describes a selected best case, not typical
performance. The existing best-run validator checks this selection against all
published rows on every web build.

The operator-held original run was checked using `canonical_sha256` and
`validate_agentic_artifact(artifact, raw_run=...)`. Its canonical digest is
`091fff8d623165c0fe98538cf10a9c243e03bcd5f89a32dc506455aad2c25154`.
The full raw validation passed; the recorded driver differs from the checkout's
driver, an expected warning. No new model evaluation was run.

To reproduce, supply the operator-held original run directory:

```sh
python3 scripts/build_astra_showcase.py --raw <operator-held-run-directory> --check
python3 web/scripts/validate_best_run.py
```

Omit `--check` to regenerate `web/src/data/astra-showcase.json`. Extraction
rejects another canonical run, replays episode 28 with the frozen engine,
checks every executed tool reply, reproduces the complete retained transaction
list and season summaries, and checks the final score and move totals against
the compact artifact. It writes no replay ledger. Public validation checks an
exact schema, financial and outcome arithmetic, and accepted/rejected counts.
CI can validate the derived data; only an operator with the original run can
reproduce it. The extraction script is outside the frozen contract and driver.

The frozen engine's partial-season path retains cumulative win/loss counters.
Its season summaries record 17–16, 37–29, 63–36, 85–47 and 109–56; the episode's
published wins field sums the five win snapshots to 311. The derived season
records subtract consecutive snapshots: 17–16, 20–13, 26–7, 22–11 and 24–9.
The final score remains 409.132 (411.632 strategy points minus 2.500 penalty).
Standings reconstructed from the engine's cumulative ordering are 7th, 4th,
1st, 1st and 1st. The first two seasons qualify for the eight-team playoffs but
win zero rounds; seasons 3–5 win all three rounds and the championship.
No benchmark score, contract source or published panel artifact was edited.

Highlights emphasize accepted acquisitions, the only drafted prospect, major
renewals and a repeated rejected target eventually acquired. Expandable detail
contains all 54 roster calls (49 accepted, five rejected), with 20 accepted
lineup calls summarized separately: 69 accepted moves total. No causal claim
or unretained model reasoning is inferred from subsequent titles.

Publication follows the raw-evidence boundary in `docs/bench_v2_spec.md`:
only typed, derived outcomes, simulated names and transaction terms appear.
The exporter never copies raw arguments, messages (except two reviewed refusal
categories), tool replies, commands, harness events or local paths. No seed,
entity ID, seed-bearing URL, starting-state export, full lineup or hidden
rating/potential is published. The original raw evidence remains with the
operator and is not included in Git or browser assets. The showcase query
parameter chooses an editorial view and cannot instantiate this private run.

Missing detail: the simulator has no league-points or game-score records and
does not retain playoff opponents. Rollover departures are reconstructed roster
differences, not agent-initiated waivers; the page does not assign an unverified
expiry or retirement reason. Score snapshots are computed before appending the
current summary to scoring history and advancing the calendar. Full replay,
initial state, exact lineup ordering and hidden traits remain withheld; expanding
that disclosure would require an owner decision.
