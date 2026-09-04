import type {
  Leaderboard,
  LeaderboardModel,
  TieredLeaderboardModel,
} from "./types";

export type ResultModel = TieredLeaderboardModel & {
  primary_lift: number;
  primary_ci95: [number, number];
  full_panel_lift: number;
  cost_per_episode_usd: number;
};

/**
 * The primary lift is computed twice by independent code paths: once by the
 * runner (`paired.best_baseline.paired_lift_mean`, surfaced as
 * `lift_vs_best_baseline`) and once by scripts/analyze_publication_panel.py
 * (`mean_lift`, surfaced as `primary_lift`). Both round to 3dp, so any
 * disagreement past this tolerance means the two surfaces are describing
 * different contrasts -- the exact defect this module now guards.
 */
const PRIMARY_LIFT_AGREEMENT_TOLERANCE = 0.001;

/**
 * Two-sided 95% Student-t multipliers by degrees of freedom (index df-1).
 *
 * The runner publishes `score_stddev` as a *population* SD over per-seed means.
 * Treating that as a known population SD with z = 1.96 understates the interval
 * on a small panel; the honest interval applies the sample-SD correction and the
 * t multiplier for n-1. Beyond this table the two agree closely enough to fall
 * back to z.
 */
const T95_BY_DF = [
  12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228, 2.201, 2.179, 2.16,
  2.145, 2.131, 2.12, 2.11, 2.101, 2.093, 2.086, 2.08, 2.074, 2.069, 2.064, 2.06, 2.056, 2.052,
  2.048, 2.045, 2.042,
];
const Z95 = 1.96;

function t95(df: number): number {
  return df >= 1 && df <= T95_BY_DF.length ? T95_BY_DF[df - 1] : Z95;
}

export const MECHANICS = [
  ["cap_free_agency", "Cap & FA"],
  ["draft", "Draft"],
  ["information_memory", "Information"],
  ["lineup", "Lineup"],
  ["trades", "Trades"],
] as const;

export interface BenchmarkView {
  models: ResultModel[];
  modelCount: number;
  modelsAboveBar: number;
  /** Rows whose preregistered Holm-adjusted primary test rejects at 0.05. */
  holmRejectedCount: number;
  repeats: number;
  scriptedBar: number;
  /** Partial-oracle reference, or null for a study that ran no oracle. */
  oracle: number | null;
}

export type PrimaryClaim = "rejects" | "descriptive-only" | "inconclusive";

/**
 * Decide what claim a single published row has actually earned.
 *
 * The two available signals disagree, by design and by disclosure:
 *   - `primary_ci95` is a percentile bootstrap on the primary contrast. For
 *     every v2 row it excludes zero, which naively reads as "significant".
 *   - `holm_reject_at_0_05` is the preregistered family test. At 29 paired
 *     seeds the sign-flip floor is far below 0.05, so this test can and does
 *     reject; on the eight-seed v2 panel it could not reject for any row,
 *     because the floor (2/2**8) against a family of ten put the smallest
 *     achievable adjusted p at 0.078.
 *
 * The publication protocol is explicit that the interval is descriptive
 * and "must not be used as a headline claim". The preregistered Holm result
 * therefore controls the inferential claim; the interval only distinguishes a
 * descriptive directional gap from an interval that crosses zero.
 */
export function primaryClaim(model: ResultModel): PrimaryClaim {
  if (model.holm_reject_at_0_05 === true) return "rejects";
  const [lower, upper] = model.primary_ci95;
  if (upper < 0 || lower > 0) return "descriptive-only";
  return "inconclusive";
}

function finite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

/** Number of seeds this row's across-seed SD was computed over. */
export function seedCount(model: LeaderboardModel): number {
  return model.seeds?.length ?? model.seed_count ?? Object.keys(model.per_seed_scores ?? {}).length;
}

/**
 * Panel width for the study as a whole.
 *
 * `preset.seeds` is a list only for a public panel; a private panel publishes
 * the redaction sentinel string and its width in `seed_count`. Reading a length
 * off the sentinel would silently show the wrong number of seeds.
 */
export function presetSeedCount(data: Leaderboard): number | null {
  if (Array.isArray(data.preset.seeds)) return data.preset.seeds.length;
  return data.preset.seed_count ?? null;
}

/** Across-seed 95% interval on the mean score, or null when a row cannot support one. */
export function scoreCi95(model: LeaderboardModel): [number, number] | null {
  if (!finite(model.mean_score)) {
    return null;
  }
  const n = seedCount(model);
  if (n < 2 || !finite(model.score_stddev)) {
    return null;
  }
  const sampleStddev = model.score_stddev * Math.sqrt(n / (n - 1));
  const margin = (t95(n - 1) * sampleStddev) / Math.sqrt(n);
  return [model.mean_score - margin, model.mean_score + margin];
}

function assertResultModel(model: TieredLeaderboardModel): asserts model is ResultModel {
  if (!finite(model.mean_score)) {
    throw new Error(`Leaderboard row ${model.id} is missing a finite mean_score`);
  }
  if (!finite(model.primary_lift)) {
    throw new Error(`Leaderboard row ${model.id} is missing a finite primary_lift`);
  }
  // Fail loud rather than render a blank cell: a published row without the
  // secondary contrast is a malformed artifact, not a presentational edge case.
  if (!finite(model.full_panel_lift)) {
    throw new Error(`Leaderboard row ${model.id} is missing a finite full_panel_lift`);
  }
  if (
    !Array.isArray(model.primary_ci95) ||
    model.primary_ci95.length !== 2 ||
    !finite(model.primary_ci95[0]) ||
    !finite(model.primary_ci95[1]) ||
    model.primary_ci95[0] > model.primary_ci95[1]
  ) {
    throw new Error(`Leaderboard row ${model.id} has an invalid primary_ci95`);
  }
  if (model.primary_lift < model.primary_ci95[0] || model.primary_lift > model.primary_ci95[1]) {
    throw new Error(`Leaderboard row ${model.id} has a primary_lift outside its own primary_ci95`);
  }
  // Cross-surface check: the runner and the publication analyzer must agree on
  // the primary contrast. If they drift apart, the site would plot one and cite
  // the other's Holm verdict -- silently, which is how this shipped before.
  if (
    finite(model.lift_vs_best_baseline) &&
    Math.abs(model.primary_lift - model.lift_vs_best_baseline) > PRIMARY_LIFT_AGREEMENT_TOLERANCE
  ) {
    throw new Error(
      `Leaderboard row ${model.id} disagrees on the primary contrast: ` +
        `analysis primary_lift ${model.primary_lift} vs runner lift_vs_best_baseline ${model.lift_vs_best_baseline}`,
    );
  }
  if (!finite(model.cost_per_episode_usd) || model.cost_per_episode_usd < 0) {
    throw new Error(`Leaderboard row ${model.id} has an invalid cost_per_episode_usd`);
  }
  for (const [key] of MECHANICS) {
    const outcome = model.mechanic_breakdown[key];
    if (
      outcome === undefined ||
      !finite(outcome.accepted) ||
      !finite(outcome.rejected) ||
      outcome.accepted < 0 ||
      outcome.rejected < 0
    ) {
      throw new Error(`Leaderboard row ${model.id} has invalid ${key} outcomes`);
    }
  }
}

export function buildBenchmarkView(data: Leaderboard): BenchmarkView {
  const ids = new Set<string>();
  const completeModels: ResultModel[] = data.models.map((model) => {
    if (ids.has(model.id)) {
      throw new Error(`Leaderboard contains duplicate model id ${model.id}`);
    }
    ids.add(model.id);
    assertResultModel(model);
    return model;
  });

  if (data.models.length === 0 && data.publication.publishable_ranking) {
    throw new Error("Publishable leaderboard has no model rows");
  }

  const models = [...completeModels].sort((a, b) => b.mean_score - a.mean_score);
  const scriptedBar =
    data.baselines.find((baseline) => baseline.agent === "pick-trader")?.mean_score ??
    data.headroom.pick_trader;
  if (!finite(scriptedBar)) {
    throw new Error("Leaderboard is missing a finite scripted bar");
  }
  // The partial oracle is optional evidence, not a required field: sota-v5 ran
  // no oracle baseline, and every surface that draws it must hide it rather
  // than plot a zero. A present-but-malformed value is still a defect.
  if (data.headroom.oracle !== null && !finite(data.headroom.oracle)) {
    throw new Error("Leaderboard has a non-finite partial oracle reference");
  }

  // Repeats are derived per row from that row's own seed count, not from the
  // public preset's panel width: a redacted private-panel row publishes
  // seed_count (29) with seeds null, and dividing its decisions by the public
  // preset's 8 seeds would not yield a whole number.
  const repeatsFor = (model: ResultModel): number => {
    const denominator = seedCount(model) * data.preset.decision_points_per_episode;
    return denominator > 0 ? model.decision_points / denominator : 0;
  };
  const repeats = models.length > 0 ? repeatsFor(models[0]) : 0;
  if (models.length > 0 && (!Number.isInteger(repeats) || repeats < 1)) {
    throw new Error("Leaderboard decision counts do not yield a whole repeat count");
  }
  for (const model of models) {
    if (repeatsFor(model) !== repeats) {
      throw new Error("Leaderboard rows disagree on repeats per seed");
    }
  }

  return {
    models,
    modelCount: models.length,
    modelsAboveBar: models.filter((model) => model.mean_score > scriptedBar).length,
    // Derived, never hand-written: the previous copy asserted a Holm outcome in
    // prose, which is how a claim and its data drift apart in the first place.
    holmRejectedCount: models.filter((model) => primaryClaim(model) === "rejects").length,
    repeats,
    scriptedBar,
    oracle: finite(data.headroom.oracle) ? data.headroom.oracle : null,
  };
}

/**
 * v6 reliability, read defensively.
 *
 * The spec requires malformed and unrecoverable output rates to sit beside the
 * score rather than inside it, but rows published before v6 have neither field.
 * `null` here means "this row does not report it" and must render as an em
 * dash, never as a reassuring zero. Where a row carries counts but no rate, the
 * rate is derived from its own decision total instead of being invented.
 */
export interface Reliability {
  malformedRate: number | null;
  unrecoverableRate: number | null;
  malformedDecisions: number | null;
  unrecoverableDecisions: number | null;
  failedDecisions: number | null;
  /** Share of decisions whose call never returned a usable turn. */
  failedRate: number | null;
  reported: boolean;
}

function rate(
  explicit: number | null | undefined,
  count: number | null | undefined,
  total: number,
): number | null {
  if (finite(explicit)) return explicit;
  if (finite(count) && total > 0) return count / total;
  return null;
}

export function reliability(model: LeaderboardModel): Reliability {
  const total = model.decision_points;
  const malformedRate = rate(model.malformed_rate, model.malformed_decisions, total);
  const unrecoverableRate = rate(
    model.unrecoverable_rate,
    model.unrecoverable_decisions,
    total,
  );
  // `fallback_rate` is the old key for exactly this quantity, kept readable so
  // an older published dataset does not silently lose its failure rate.
  const failedRate = rate(
    finite(model.decision_failure_rate) ? model.decision_failure_rate : model.fallback_rate,
    model.failed_decisions,
    total,
  );
  return {
    malformedRate,
    unrecoverableRate,
    failedRate,
    malformedDecisions: finite(model.malformed_decisions) ? model.malformed_decisions : null,
    unrecoverableDecisions: finite(model.unrecoverable_decisions)
      ? model.unrecoverable_decisions
      : null,
    failedDecisions: finite(model.failed_decisions) ? model.failed_decisions : null,
    reported: malformedRate !== null || unrecoverableRate !== null,
  };
}

export function withinSeedStddev(model: LeaderboardModel): number | null {
  return finite(model.within_seed_score_stddev) ? model.within_seed_score_stddev : null;
}

export interface SeedScore {
  seed: number;
  score: number;
}

/** Per-seed scores in seed order, or an empty list when the row omits them. */
export function perSeedScores(model: LeaderboardModel): SeedScore[] {
  const rows: SeedScore[] = [];
  for (const [key, score] of Object.entries(model.per_seed_scores ?? {})) {
    const seed = Number(key);
    if (Number.isFinite(seed) && finite(score)) rows.push({ seed, score });
  }
  return rows.sort((a, b) => a.seed - b.seed);
}

export function shortModelName(model: string): string {
  return model.split("/").pop() ?? model;
}

export function issueLabel(issue: string): string {
  if (issue.includes("illegal actions")) return "Illegal actions";
  // The warning behind this text fires on failed_decisions, so label it that
  // way: under the strict no-op lane there is no adapter fallback path to name.
  if (issue.includes("fallback")) return "Failed decisions";
  if (issue.includes("failed queries")) return "Query errors";
  if (issue.includes("strongest scripted baseline")) return "Below bar";
  return "Protocol note";
}

export function issueLabels(model: LeaderboardModel): string[] {
  return (model.sota_v2_issues ?? []).map(issueLabel);
}

export function rejectionRate(
  model: LeaderboardModel,
  mechanic: (typeof MECHANICS)[number][0],
): number {
  const outcome = model.mechanic_breakdown[mechanic];
  if (!outcome) return 0;
  const total = outcome.accepted + outcome.rejected;
  return total === 0 ? 0 : outcome.rejected / total;
}
