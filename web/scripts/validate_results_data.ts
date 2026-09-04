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
    `(${benchmark.repeats} repeats; ${benchmark.modelsAboveBar} above scripted bar).`,
);
