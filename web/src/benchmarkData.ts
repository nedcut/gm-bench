import type {
  Leaderboard,
  LeaderboardModel,
  TieredLeaderboardModel,
} from "./types";

export type ResultModel = TieredLeaderboardModel & {
  paired_lift: number;
  ci95: [number, number];
  cost_per_episode_usd: number;
};

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
  repeats: number;
  scriptedBar: number;
  oracle: number;
}

function finite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function assertResultModel(model: TieredLeaderboardModel): asserts model is ResultModel {
  if (!finite(model.mean_score)) {
    throw new Error(`Leaderboard row ${model.id} is missing a finite mean_score`);
  }
  if (!finite(model.paired_lift)) {
    throw new Error(`Leaderboard row ${model.id} is missing a finite paired_lift`);
  }
  if (
    !Array.isArray(model.ci95) ||
    model.ci95.length !== 2 ||
    !finite(model.ci95[0]) ||
    !finite(model.ci95[1]) ||
    model.ci95[0] > model.ci95[1]
  ) {
    throw new Error(`Leaderboard row ${model.id} has an invalid ci95`);
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
    throw new Error("Leaderboard is missing a finite scripted bar or oracle ceiling");
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
