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

const Z95 = 1.96;

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
  oracle: number;
}

export type PrimaryClaim = "rejects" | "descriptive-only" | "inconclusive";

/**
 * Decide what claim a single published row has actually earned.
 *
 * The two available signals disagree, by design and by disclosure:
 *   - `primary_ci95` is a percentile bootstrap on the primary contrast. For
 *     every v2 row it excludes zero, which naively reads as "significant".
 *   - `holm_reject_at_0_05` is the preregistered family test. It rejects for
 *     no v2 row, because at eight seeds the sign-flip floor (2/2**8) against a
 *     family of ten puts the smallest achievable adjusted p at 0.078.
 *
 * config/publication_protocol.json is explicit that the interval is descriptive
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

export function scoreCi95(model: LeaderboardModel): [number, number] | null {
  if (!finite(model.mean_score)) {
    return null;
  }
  const n = model.seeds?.length ?? 0;
  if (n < 2 || !finite(model.score_stddev)) {
    return null;
  }
  const margin = (Z95 * model.score_stddev) / Math.sqrt(n);
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
  if (!finite(scriptedBar) || !finite(data.headroom.oracle)) {
    throw new Error("Leaderboard is missing a finite scripted bar or partial oracle reference");
  }

  const decisionPoints = models[0]?.decision_points ?? 0;
  const denominator = data.preset.seeds.length * data.preset.decision_points_per_episode;
  const repeats = denominator > 0 ? decisionPoints / denominator : 0;
  if (!Number.isInteger(repeats) || repeats < 1) {
    throw new Error("Leaderboard decision counts do not yield a whole repeat count");
  }
  for (const model of models) {
    if (model.decision_points !== decisionPoints) {
      throw new Error("Leaderboard rows disagree on decision_points");
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
    oracle: data.headroom.oracle,
  };
}

export function shortModelName(model: string): string {
  return model.split("/").pop() ?? model;
}

export function issueLabel(issue: string): string {
  if (issue.includes("illegal actions")) return "Illegal actions";
  if (issue.includes("fallback")) return "Adapter fallback";
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
