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

console.log(
  `Validated ${benchmark.modelCount} result rows from one leaderboard source ` +
    `(${benchmark.repeats} repeats; ${benchmark.modelsAboveBar} above scripted bar).`,
);
