import findingsData from "./data/v21-findings.json" with { type: "json" };

/* Built by scripts/build_v21_findings.py from the committed 2.1 behaviour
   diagnostic (results/diagnostics/v21_behavior/behavior.json). Aggregates only. */
export interface Term {
  key: string;
  label: string;
  detail: string;
  mean: number;
  ci95: [number, number];
  share: number;
}

export interface ModelFindings {
  model: string;
  artifact: string;
  harness: string;
  episodes: number;
  phases: number;
  empty_phases: number;
  empty_rate: number;
  empty_drafts_with_no_pick: number;
  share_empty_drafts_with_no_pick: number;
  drafts: number;
  drafts_closed_holding_unused_pick: number;
  rate_ended_without_status_read: number;
  roster_at_end: number;
  episodes_ending_with_5_or_fewer: number;
  season_5_extensions_per_episode: number;
  episodes_final_below_after_season_4: number;
}

export interface Findings {
  source: string;
  script: string;
  family_gap: {
    openai: string[];
    claude: string[];
    seeds: number;
    final_score: { mean: number; se: number; ci95: [number, number]; ahead: number };
    terms: Term[];
    extra_empty_vs_gap_correlation: [number, number];
  };
  drafts_closed_holding_unused_pick: number;
  drafts: number;
  models: ModelFindings[];
  not_covered: string[];
}

export const findings = findingsData as unknown as Findings;

/** A committed 2.1 row's findings, by its result file path. */
export const findingsByArtifact = new Map(findings.models.map((m) => [m.artifact, m]));
