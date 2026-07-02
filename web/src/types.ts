export interface SnapshotConfig {
  candidate: string;
  baselines: string[];
  seeds: number[];
  seasons: number;
}

export interface Normalized {
  candidate_mean_score: number;
  baseline_panel_mean_score: number;
  score_lift: number;
  score_lift_pct: number;
  candidate_illegal_actions: number;
  baseline_illegal_actions: number;
}

export interface PerSeed {
  seed: number;
  candidate_score: number;
  baseline_panel_score: number;
  lift: number;
}

export interface Paired {
  num_seeds: number;
  per_seed: PerSeed[];
  paired_lift_mean: number;
  paired_lift_stddev: number;
  paired_lift_ci95: number[];
  significant_at_95: boolean;
  candidate_seed_win_rate: number;
  best_baseline: {
    agent: string;
    mean_score: number;
    paired_lift_mean: number;
    seed_win_rate: number;
  } | null;
}

export interface StandingRow {
  agent: string;
  mean_score: number;
  score_stddev: number;
  mean_wins: number;
  titles: number;
  illegal_actions: number;
  episodes: number;
  best_score: number;
  worst_score: number;
}

export interface SeasonRow {
  season: number;
  wins: number;
  losses: number;
  playoff_rounds: number;
  champion: boolean;
  cap_room: number;
  score_after_season: number;
}

export interface SampleTransaction {
  season: number;
  phase: string;
  accepted: boolean;
  message: string;
  action: Record<string, unknown>;
}

export interface Snapshot {
  config: SnapshotConfig;
  normalized: Normalized;
  paired: Paired;
  standings: StandingRow[];
  season_trace: {
    agent: string;
    seed: number;
    seasons: SeasonRow[];
  };
  sample_transactions: SampleTransaction[];
}
