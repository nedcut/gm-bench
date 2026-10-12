# Experimental decision journal report

Evidence: **offline fixture**. Separate from frozen 1.0/2.0 panels.

Manifest SHA-256: `6759eefd4be7cbbbc6b419fbcf5539286f197bfc0d4b530778d2e85b7cffaeb8`.

Model: `scripted-rules-v1`; pin status: **pinned**; sampling seed: unsupported.
Source unchanged during run: True.

Cells: 8/8; complete panel: True; all episodes completed: True; all identity pins verified: True.

Differences are journal minus no persistent journal, averaged within seed over repeats first. Standard errors are descriptive; no hypothesis test or memory-benefit claim.

| Metric | Mean paired difference | Seed SE | Seeds | Pairs |
|---|---:|---:|---:|---:|
| final_score | 0 | 0.0 | 2 | 4 |
| completed | 0 | 0.0 | 2 | 4 |
| illegal_actions | 0 | 0.0 | 2 | 4 |
| tool_calls | -3 | 0.0 | 2 | 4 |
| rejected_tool_calls | 0 | 0.0 | 2 | 4 |
| model_calls | -3 | 0.0 | 2 | 4 |

| Seed/repeat | Condition | Completion | Illegal | Score | Tools | Input/output tokens | Provider seconds | USD |
|---|---|---|---:|---:|---:|---|---|---|
| 701/0 | no_persistent_journal | completed | 0 | 118.573 | 12 | 0 (measured) / 0 (measured) | 0.00209108 (measured) | 0 (measured) |
| 701/0 | structured_decision_journal | completed | 0 | 118.573 | 9 | 0 (measured) / 0 (measured) | 0.00150546 (measured) | 0 (measured) |
| 701/1 | structured_decision_journal | completed | 0 | 118.573 | 9 | 0 (measured) / 0 (measured) | 0.00165292 (measured) | 0 (measured) |
| 701/1 | no_persistent_journal | completed | 0 | 118.573 | 12 | 0 (measured) / 0 (measured) | 0.00303341 (measured) | 0 (measured) |
| 702/0 | structured_decision_journal | completed | 0 | 88.365 | 9 | 0 (measured) / 0 (measured) | 0.00149012 (measured) | 0 (measured) |
| 702/0 | no_persistent_journal | completed | 0 | 88.365 | 12 | 0 (measured) / 0 (measured) | 0.00219462 (measured) | 0 (measured) |
| 702/1 | no_persistent_journal | completed | 0 | 88.365 | 12 | 0 (measured) / 0 (measured) | 0.0021635 (measured) | 0 (measured) |
| 702/1 | structured_decision_journal | completed | 0 | 88.365 | 9 | 0 (measured) / 0 (measured) | 0.00156687 (measured) | 0 (measured) |

Billed cost is unavailable. Provider time is measured locally; token counts are provider-reported (zero for fixtures). Missing usage is unavailable, never zero-filled. See each cell.json for bases, rejections, termination, model identity and tool counts.

- Offline scripted fixtures test machinery, not whether memory improves LLM performance.
- Historical facts remain retrievable through tools: this may measure retrieval efficiency, not memory dependence.
- Both arms plan and write journals; only cross-phase retention differs. This does not isolate planning benefit.
- Journal input tokens and resulting actions can differ; equal resource ceilings do not mean equal realized compute.
- Public seeds, fixed order counterbalancing, one model/harness and small panels limit generalization.
- A model snapshot ID is not deterministic inference; backend fingerprints and sampling support are recorded.
- Claude model IDs carry no date; a pin is checked only against the returned model field, not proven a snapshot.
- Existing four 2.0 rows are unpinned exploratory evidence; no causal 1.0 versus 2.0 comparison is supported.
