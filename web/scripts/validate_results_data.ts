import leaderboardData from "../src/data/leaderboard.json";
import { buildBenchmarkView, scoreCi95, seedCount } from "../src/benchmarkData";
import type { Leaderboard, LeaderboardModel } from "../src/types";

const leaderboard = leaderboardData as Leaderboard;
const benchmark = buildBenchmarkView(leaderboard);

if (benchmark.modelCount !== leaderboard.publication.eligible_headline_models) {
  throw new Error(
    `Results UI has ${benchmark.modelCount} rows, but publication metadata declares ` +
      `${leaderboard.publication.eligible_headline_models} eligible headline models`,
  );
}

// The decision-model lane is published beside the headline, never inside it:
// no shared ids, every row on the same private panel, and none of them counted
// toward the eligible-headline figure the check above just tied down.
const headlineIds = new Set(leaderboard.models.map((model) => model.id));
const decisionLaneIds = new Set<string>();
for (const row of leaderboard.decision_lane_models ?? []) {
  if (row.lane !== "decision-api") {
    throw new Error(`Decision-lane row ${row.id} is not labelled decision-api`);
  }
  if (headlineIds.has(row.id)) {
    throw new Error(`Decision-lane row ${row.id} also appears among the headline rows`);
  }
  if (decisionLaneIds.has(row.id)) {
    throw new Error(`Duplicate decision-lane row ${row.id}`);
  }
  decisionLaneIds.add(row.id);
  if (row.seed_count !== leaderboard.preset.seed_count || row.seeds !== null) {
    throw new Error(`Decision-lane row ${row.id} is not a redacted run of the published private panel`);
  }
  if (!row.artifact_path || !row.route) {
    throw new Error(`Decision-lane row ${row.id} is missing its artifact path or route`);
  }
}

const redactedPrivateRow = {
  mean_score: 100,
  score_stddev: 10,
  seeds: null,
  seed_count: 29,
  per_seed_scores: null,
} as LeaderboardModel;
if (seedCount(redactedPrivateRow) !== 29 || scoreCi95(redactedPrivateRow) === null) {
  throw new Error("A redacted private-panel row lost its published seed count or score interval");
}

// A whole redacted private panel (seeds withheld, seed_count published) must
// still build a view: repeats come from each row's own seed count.
const privatePanel = structuredClone(leaderboard) as Leaderboard;
for (const model of privatePanel.models) {
  model.seeds = null;
  model.per_seed_scores = null;
  model.seed_count = 29;
  model.decision_points = 29 * privatePanel.preset.decision_points_per_episode;
}
if (buildBenchmarkView(privatePanel).repeats !== 1) {
  throw new Error("A redacted 29-seed private panel did not build as a one-repeat view");
}

console.log(
  `Validated ${benchmark.modelCount} result rows from one leaderboard source ` +
    `(${benchmark.repeats} repeats; ${benchmark.modelsAboveBar} above scripted bar; ` +
    `${(leaderboard.decision_lane_models ?? []).length} decision-lane row(s) kept apart).`,
);
