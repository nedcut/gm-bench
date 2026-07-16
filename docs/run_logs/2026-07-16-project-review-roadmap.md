# Project review & sprint roadmap — 2026-07-16

Multi-agent review (repo audit, GitHub history analysis, independent GPT-5.6
strategic pass) of the sota-v2 publication sprint (issue #63, window
2026-07-14 → 2026-07-21). Day 3 of 7 at time of review.

## State

The publication machine is finished; the evidence is at zero. Frozen on
`main`: sota-v2 contract `558e8f35ea1d66b9` (scaffold `d7321ad9d0a739b4`),
serial checkpointed paid runner, spend ceilings, machine-locked smoke gate
(#70/#71), pre-registered stats plan in `config/publication_protocol.json`,
empty gated leaderboard. The four-cap sweep was retired (#66) for a frozen
1,024-token fixed safety ceiling after the invalidated Luna cell showed the
cap non-binding (p99 264 out-tokens). No valid paid evidence exists; the
smoke manifest (`config/sota_v2_smoke_manifest.json`) does not exist yet and
gates everything downstream. `OPENROUTER_API_KEY` is present in `.env.local`.

## Verified findings

1. **Site contradicts the frozen analysis plan.** Protocol freezes
   "publish tiers, not ordinal ranks" and forbids headlining
   `significant_at_95`, but `Leaderboard.tsx` renders `#1/#2` ordinals and a
   "✓ lift significant at 95%" badge; `build_leaderboard.py` sorts by mean
   score only. Fix pre-data.
2. **Headline-contrast vulnerability.** Primary contrast is paired lift vs
   the full baseline-panel mean (dragged down by `random` 96.7) while the
   story is "no LLM beats pick-trader (411.6)". A model can pass the primary
   test while losing to every good heuristic. Decide pre-data whether
   pick-trader lift should headline, with a dated protocol note.
3. **Power is thin (protocol admits it).** 8 seeds → min sign-flip p
   0.0078 vs Holm first threshold 0.005: family-wise significance is
   unreachable; MDD ~62 pts exceeds pick-trader→oracle headroom (19.5).
   Blog must lead with effect sizes and per-seed results.
4. **13 open Semgrep alerts on main** despite #67 claiming zero — CI scan
   isn't honoring the local `# nosemgrep` suppressions. Fix or dismiss with
   justification before promoting Semgrep to blocking.
5. **Housekeeping drift:** PUBLISH_READINESS.md header still says #66 is
   "staged in draft"; issue #63 §2 describes the retired sweep; panel cost
   artifact describes the retired 12-cell plan; site `"updated"` field
   empty; PR #62 (sota-v3, `75818ce1be557ef3`) closed unmerged — confirm
   intentional; PR #46 correctly parked until v2 rows exist.

## Roadmap (remaining 5 sprint days)

- **Jul 16** — Reconcile site with frozen stats plan (tiers, no ordinal
  ranks, no uncorrected significance badge). Decide the headline-contrast
  question pre-data. Smoke dry-run, then start the ten paid smokes serially
  (`scripts/run_publication_matrix.py smoke`, one model at a time, spend
  ceiling). Verify OpenRouter balance (~$39.61 on 07-15) covers smokes +
  panel or top up.
- **Jul 17** — Finish/record all ten smokes; freeze registry; replace stale
  cost artifact with a real fixed-cap panel estimate; refresh
  PUBLISH_READINESS.md header and issue #63 §2.
- **Jul 18–19** — Run the ten-model panel serially (~9–13 API hours). No
  substitutions; no reruns of valid poor cells.
- **Jul 20–21** — Validate, compact, hash; write blog results/limitations;
  package CITATION.cff, checksums, tagged release; independent final read.
  If <8 eligible rows, publish a transparent progress update rather than
  weaken the gate.
- **Anytime** — Semgrep suppression mismatch; confirm #62 closure; populate
  site `"updated"` field.

Biggest schedule risk: a second scaffold-level defect discovered mid-panel
with zero slack. The smokes are the instrument designed to catch that early
— start them first.
