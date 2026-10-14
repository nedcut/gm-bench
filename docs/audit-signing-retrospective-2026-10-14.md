# Blind-signing audit amendment and retrospective — 2026-10-14

The signing amendment is model-independent: an accepted `sign_free_agent`
whose sole unseen entity ID is its `player_id` is a `guessed_signing` warning.
Normal simulator legality still applies. Every season and pool is covered,
including players kept after signing, expired contracts and former rostered
players. Typo, salary and release are not eligibility conditions. Other
accepted unseen-ID moves remain violations. A valid guessed ID alone is not
proof of cheating; a warning is not proof of absence of leakage. IDs encode
position slots, and small initial-pool potential correlation cannot establish
absence of exploitable information, especially in later pools.

This disclosed audit/publication amendment is allowed by the spec without a
benchmark version bump. Scores, seeds, simulator and tools are unchanged.
The September blind-draft amendment is held fixed in both compared rules.
“Old” below means immediately before the October signing amendment, not the
original pre-September draft policy.

## Reproduction and coverage

```sh
python -m gm_bench.agentic.audit_compare "$RAW_ROOT" --validate > comparison.json
```

Run against the existing local retained archive, with no provider calls or
paid reruns. The [machine-readable report](../results/analysis/agentic-signing-audit-2026-10-14.json)
contains SHA-256 bindings to manifests and ledgers, indexed episodes, both-rule
status and finding counts, and full-validation problem/warning counts. Paths,
private seeds, entity IDs, arguments, raw ledgers and credentials are omitted.
Run indices use sorted manifest paths; names below describe the local mapping.
“Validation” includes replay and harness recounts, not just ID auditing, and
passing validation does not establish headline eligibility or trace authenticity.

| Run | Retained run | Episodes | Validation old → new | Warnings old → new | ID findings (both rules) |
| --- | --- | ---: | --- | --- | --- |
| 0 | Space Bunny gate smoke | 8 | pass → pass | 5 → 5 | none |
| 1 | Haiku 4.5 panel | 32 | pass → pass | 14 → 14 | 10 suspicious; 6 guessed drafts |
| 2 | Haiku 4.5 smoke | 1 | pass → pass | 0 → 0 | none |
| 3 | Sonnet 5 panel | 32 | pass → pass | 5 → 5 | 4 suspicious |
| 4 | Sonnet 5.5 locally retained panel (does **not** bind to #198) | 32 | pass → pass | 8 → 8 | 8 suspicious |
| 5 | GPT-6 Luna panel | 32 | pass → pass | 0 → 0 | none |
| 6 | Composer 2.5 panel | 32 | pass → pass | 0 → 0 | none |
| 7 | Grok 4.7 excluded panel | 32 | fail → fail (11 problems) | 36 → 36 | none |
| 8 | DeepSeek v4.1 Flash / OpenCode Go 1.18.31 panel | 32 | pass → pass | 0 → 0 | none |
| 9 | Sonnet 5 probe A | 4 | pass → pass | 0 → 0 | none |
| 10 | Sonnet 5 probe B | 4 | pass → pass | 1 → 1 | 1 suspicious |
| 11 | GPT-6 Luna probe A | 4 | pass → pass | 0 → 0 | none |
| 12 | GPT-6 Luna probe B | 4 | pass → pass | 0 → 0 | none |
| 13 | Sonnet 5 smoke | 1 | pass → pass | 0 → 0 | none |
| 14 | GPT-6 Luna smoke | 1 | pass → pass | 0 → 0 | none |

All 251 manifest episodes have auditable retained ledgers. All have zero ID
violations and zero guessed signings under both policies. None changes status,
warning count or violation count. Full validation passes 14 of 15 runs under
both rules; Grok's 11 missing prompt-audit problems persist independently of
this amendment.

The interrupted Muse Spark 1.3 directory has no completed `run.json`: all 18
retained ledgers (including the unfinished episode) were audited as orphans.
All pass both ID audits. There is one unchanged suspicious finding (orphan
index 12), with no violations, guessed reads, guessed drafts or guessed
signings under either rule. No statuses or counts change. This is **not**
full run validation or publication eligibility for Muse. There are 269 total
retained raw ledgers covered. No excluded/incomplete run was filtered out.

## Published Sonnet 5.5 provenance and missing evidence

The #198 compact artifact reports mean **217.060**, 37 illegal actions and
one guessed signing in episode 19: this signing failed the pre-signing rule
and became a warning under the revised rule. That original failure and revised
pass remain disclosed. The artifact itself validates successfully, but compact
validation is **not** a raw-ledger re-audit.

The local directory labelled Sonnet 5.5 instead has mean **209.510**, 56 illegal
actions, no guessed signings, and raw-byte manifest SHA-256
`23397ed6d24af58422ce329e7bf35dec7af2aae7b09713f1bfba06f11aefc49e`.
The publication validator hashes canonical JSON rather than file bytes. The
local canonical manifest SHA-256 is
`dc7184108d0c556af8f500a7b54b53435c95a404c704fc64882c86051d141aed`;
the published artifact binds to canonical SHA-256
`a1f927753b765272e4a3ba70d95d4013baa4b60fde6d30ea5b06dd7673d73cee`.
`agentic-validate --raw` explicitly rejects that binding. The retained local
run is counted as separate evidence, not substituted for the published run.
The matching published raw manifest and episode-19 ledger were not found in
the local raw archive, Documents/code, Documents/Codex, Downloads or /tmp.
Why the two runs differ is not established; no chronology or selection motive
is inferred. Owner review should locate the matching raw evidence and explain
the distinct run before relying on independent provenance confirmation.

Canonical manifest hashes match 12 committed artifacts: Space Bunny smoke,
Haiku 4.5 panel, Sonnet 5 panel, Luna panel, Composer panel, OpenCode Go 1.18.31
DeepSeek panel, the four Sonnet/Luna probes and the two Sonnet/Luna smokes.
This manifest binding check supplements the raw re-audit; it is not a claim of
complete trace authenticity. Haiku 4.5 smoke and excluded Grok have no committed
artifact binding in this checkout.

Other published panel raw evidence absent from the local archive: GPT-6.1 Sol,
GPT-6 Astra, Haiku 5.5, and OpenCode 2.0.27 DeepSeek v4.1 Flash (including the
discarded first 2.x panel). Sonnet 5.5's matching smoke is also absent. Earlier
smokes/public rows without retained raw evidence are not claimed as re-audited.
The two public trajectory demo ledgers are separate public-seed examples, not
private-panel evidence. Existence elsewhere was not ruled out; no downloads,
paid reruns or private raw publication were performed.

## User-provided WSL verification — 2026-10-14

Ned supplied the following verification from WSL after the Mac retrospective.
These results are attributed to his report; this author did not access WSL,
its computer or its raw files. They are separate from the reproducible Mac
269-ledger report above and are not added to its machine-readable coverage.
The different Mac run is not evidence that the published result is bad.

Ned reports that `gmb-runs/claude-sonnet-5-5-panel/` contains the matching
`run.json` and 32 ledgers. Its canonical manifest SHA-256 is
`a1f927753b765272e4a3ba70d95d4013baa4b60fde6d30ea5b06dd7673d73cee`,
exactly matching the published artifact's `publication.raw_artifact_sha256`.
He reports that the separate 209.510 Mac run is absent from that WSL location.
The reported reproduction is mean **217.060**, SD **50.272**, 32 seeds,
37 illegal actions, zero failed decisions out of 640, container isolation,
driver digest `0c20d2de9ce62901` and run Git revision `0f3042d`.

The reported dual-policy audit confirms the published provenance: episode 19
has one violation under the old signing rule and one `guessed_signing` warning
under the revised rule. ID audits pass 31/32 episodes under the old rule and
32/32 under the revised rule. Reported full validation is old `ok: false`
with one problem, versus revised `ok: true` with zero problems.

There is a remaining artifact-maintenance caveat. Ned reports that
`agentic-validate --raw` accepts the canonical SHA-256 binding but flags a
fresh-redaction mismatch solely in episode 19's warning wording, which
`d2e60ac` changed. The compact artifact has not been regenerated. His WSL
checkout was still at `e69147a`, while the branch was at `1d7a9d0` when this
verification was supplied. Regeneration from the matching raw run at the
current branch head, followed by a clean `agentic-validate --raw` check, has
been recommended but is **not reported completed**. No compact artifact was
hand-edited or regenerated by this addendum, and no paid rerun is needed for
that maintenance. Ned reports no file changes, merge, paid runs or credential
access during his verification.

## Statistical interpretation

Re-reading the committed Sonnet artifact confirms mean 217.060 versus
`pick-trader` 249.180, paired lift −32.120, 95% interval [−56.331, −9.664],
and unadjusted sign-flip p = 0.0121. Sorting the ten committed panel-row
p-values places Sonnet fourth. Holm gives
`max((10 - j) * p[j] for j <= 3) = 0.0847`, so it is **not significant**
at 0.05 after correction. These values describe the published compact sample;
the mismatched local sample cannot independently reproduce its statistics.
No scores, samples or simulator behavior were altered by this amendment.

## Verification and owner review

Local validation: full Python suite 1,584 passed / 3 skipped; the subsequent
91-test focused pass includes the added simulator-backed retained-player test.
Ruff checks and formatting pass. The contract check passes without touching
fingerprinted simulator/tool sources. All 18 committed compact artifacts
validate; a tampered score is rejected. Web lint, data/replay/trajectory checks,
TypeScript and production build pass. Retained raw hashes and both-rule counts
reproduce exactly on a second archive scan.

The patch was separately inspected for policy propagation, preservation of
non-signing violations, privacy of the report fields, provenance classification,
and claim scope. Existing GitHub review state was read; it supplies no fresh
independent review of this amendment. Owner review should focus on the broad
model-independent policy and the unmatched published Sonnet evidence. No merge
or paid model run is authorized by this work.
