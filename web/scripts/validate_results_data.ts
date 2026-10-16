import leaderboardData from "../src/data/leaderboard.json";
import benchV2Lane from "../../config/bench_v2_lane.json";
import scoreV2Lane from "../../results/agentic_score_v2/lane.json";
import { AGENTIC_REFERENCE_AGENT, agenticLaneIssues, type AgenticLanePanel } from "../src/agenticLane";
import { buildBenchmarkView, scoreCi95, seedCount } from "../src/benchmarkData";
import type { AgenticLaneRow, Leaderboard, LeaderboardModel } from "../src/types";

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

// GM-Bench 2.0 rows live only in agentic_lane: panel grade, the lane's frozen
// 32-seed private panel (by digest), and a harness isolated from the driver by
// user or container. None may appear in, or share an id with, a 1.0 table.
// Each carries exactly one inference, the predeclared pick-trader reference on
// its own seeds; any other p-value or paired field is rejected.
if (benchV2Lane.panel_design.reference_agent !== AGENTIC_REFERENCE_AGENT) {
  throw new Error(
    `config/bench_v2_lane.json names ${benchV2Lane.panel_design.reference_agent} as the reference; ` +
      `the site checks ${AGENTIC_REFERENCE_AGENT}`,
  );
}
// Rows are published under score-v2 (results/agentic_score_v2/lane.json pins its
// pick-trader and random means); score-v1 survives only as each row's
// comparison block, pinned to config/bench_v2_lane.json as before.
if ((leaderboard.agentic_lane ?? []).length > 0 && leaderboard.agentic_scoring?.primary !== "score-v2") {
  throw new Error("The 2.0 section is not declared as scored with score-v2 (agentic_scoring.primary)");
}
const lanePanel: AgenticLanePanel = {
  artifact_panel_sha256: benchV2Lane.seed_panel.artifact_panel_sha256,
  count: benchV2Lane.seed_panel.count,
  reference_scores: { seasons: scoreV2Lane.seasons, mean_scores: scoreV2Lane.reference_scores },
  reference_scores_v1: benchV2Lane.reference_scores as AgenticLanePanel["reference_scores"],
};
const agenticIssues = agenticLaneIssues(leaderboard, lanePanel);
if (agenticIssues.length > 0) {
  throw new Error(`Agentic lane data is not publishable:\n  ${agenticIssues.join("\n  ")}`);
}

// Bots shown beside the 2.0 rows must be exactly the lane's recorded means
// (score-v2, with score-v1 beside each for comparison), and pick-trader and
// random must equal the pins every row's contrast uses under each score.
const botBlock = (benchV2Lane as { scripted_bot_scores?: { mean_scores: Record<string, number> } }).scripted_bot_scores;
const shownBots = leaderboard.agentic_bots ?? [];
if (botBlock) {
  const v2Means: Record<string, number> = scoreV2Lane.scripted_bot_scores;
  const expected = Object.entries(v2Means).sort(([, a], [, b]) => b - a);
  if (JSON.stringify(shownBots.map((bot) => [bot.agent, bot.mean_score])) !== JSON.stringify(expected)) {
    throw new Error("agentic_bots does not match results/agentic_score_v2/lane.json scripted_bot_scores");
  }
  for (const bot of shownBots) {
    if (bot.score_v1_mean_score !== botBlock.mean_scores[bot.agent]) {
      throw new Error(`agentic_bots ${bot.agent} score-v1 mean differs from config/bench_v2_lane.json`);
    }
  }
  for (const [agent, pinned] of Object.entries(benchV2Lane.reference_scores.mean_scores)) {
    if (pinned !== null && botBlock.mean_scores[agent] !== pinned) {
      throw new Error(`scripted_bot_scores.${agent} differs from the reference_scores pin ${pinned}`);
    }
  }
  for (const [agent, pinned] of Object.entries(scoreV2Lane.reference_scores as Record<string, number>)) {
    if (v2Means[agent] !== pinned) {
      throw new Error(`score-v2 scripted_bot_scores.${agent} differs from its reference_scores pin ${pinned}`);
    }
  }
} else if (shownBots.length > 0) {
  throw new Error("agentic_bots is published but the lane config records no scripted_bot_scores");
}

// The same rules must reject each way a 2.0 row could go wrong. The fixture is
// synthetic and lives only in memory.
const V2_PICK_TRADER = scoreV2Lane.reference_scores["pick-trader"];
const V2_RANDOM = scoreV2Lane.reference_scores.random;
const round3 = (value: number): number => Math.round(value * 1000) / 1000;
const agenticFixture = {
  id: "agentic:opencode-0.0.0:fixture/model",
  lane: "agentic",
  grade: "panel",
  agent: "opencode:fixture/model",
  model: "fixture/model",
  harness: { name: "opencode", version: "0.0.0", model: "fixture/model", variant: null },
  unpinned: true,
  pin: null,
  isolation: "container",
  panel: {
    distinct_seeds: lanePanel.count,
    episodes: lanePanel.count,
    sha256: lanePanel.artifact_panel_sha256,
  },
  seasons: 5,
  scoring_version: "score-v2",
  mean_score: 200,
  reference: {
    agent: "pick-trader",
    mean_score: V2_PICK_TRADER,
    floor: { agent: "random", mean_score: V2_RANDOM },
    seasons: 5,
    num_seeds: lanePanel.count,
    paired_lift_mean: round3(200 - V2_PICK_TRADER),
    paired_lift_stddev: 30,
    paired_lift_ci95: [round3(190 - V2_PICK_TRADER), round3(210 - V2_PICK_TRADER)],
    sign_flip_p_value: 0.0001,
    significant_at_95: true,
    candidate_seed_win_rate: 0.1,
  },
  score_v1: {
    scoring_version: "score-v1",
    mean_score: 200,
    score_stddev: 20,
    reference: {
      agent: "pick-trader",
      mean_score: 249.18,
      floor: { agent: "random", mean_score: 90.367 },
      seasons: 5,
      num_seeds: lanePanel.count,
      paired_lift_mean: -49.18,
      paired_lift_stddev: 30,
      paired_lift_ci95: [-59.18, -39.18],
      sign_flip_p_value: 0.0001,
      significant_at_95: true,
      candidate_seed_win_rate: 0.1,
    },
  },
  artifact_path: "results/agentic/fixture.json",
} as unknown as AgenticLaneRow;
function withAgentic(
  edit: (data: Leaderboard, row: AgenticLaneRow) => void,
  panel: AgenticLanePanel = lanePanel,
): string[] {
  const data = structuredClone(leaderboard) as Leaderboard;
  const row = structuredClone(agenticFixture);
  data.agentic_lane = [row];
  edit(data, row);
  return agenticLaneIssues(data, panel);
}
const pinnedPanel = (pickTrader: number, random: number): AgenticLanePanel => ({
  ...lanePanel,
  reference_scores: { seasons: 5, mean_scores: { "pick-trader": pickTrader, random } },
});
const pinnedMatchIssues = withAgentic(() => {}, pinnedPanel(V2_PICK_TRADER, V2_RANDOM));
if (pinnedMatchIssues.length !== 0) {
  throw new Error(`A row matching the pinned reference means was rejected: ${pinnedMatchIssues.join("; ")}`);
}
if (withAgentic(() => {}, pinnedPanel(40, V2_RANDOM)).length === 0) {
  throw new Error("The agentic-lane check accepted a pick-trader mean off the pinned value");
}
if (withAgentic(() => {}, pinnedPanel(V2_PICK_TRADER, 91)).length === 0) {
  throw new Error("The agentic-lane check accepted a random mean off the pinned value");
}
const emptyPerSeedIssues = withAgentic((_, row) => Object.assign(row.reference, { per_seed: [] }));
if (emptyPerSeedIssues.length !== 0) {
  throw new Error(`A reference with an empty per_seed list was rejected: ${emptyPerSeedIssues.join("; ")}`);
}
if (withAgentic(() => {}).length !== 0) {
  throw new Error(`A valid agentic fixture row was rejected: ${withAgentic(() => {}).join("; ")}`);
}
const pinnedFixtureIssues = withAgentic((_, row) => Object.assign(row, { unpinned: false, pin: "fixture/model@2026-01-01" }));
if (pinnedFixtureIssues.length !== 0) {
  throw new Error(`A valid pinned agentic fixture row was rejected: ${pinnedFixtureIssues.join("; ")}`);
}
const estimatedFixtureIssues = withAgentic((_, row) =>
  Object.assign(row, {
    telemetry: { cost_usd: null, api_equivalent_cost_usd: 1.23, api_equivalent_cost_per_episode_usd: 0.04 },
  }),
);
if (estimatedFixtureIssues.length !== 0) {
  throw new Error(`An agentic row with an API-equivalent estimate was rejected: ${estimatedFixtureIssues.join("; ")}`);
}
const agenticMustReject: Array<[string, (data: Leaderboard, row: AgenticLaneRow) => void]> = [
  ["a smoke row", (_, row) => ((row as { grade: string }).grade = "smoke")],
  ["31 seed groups", (_, row) => (row.panel.distinct_seeds = 31)],
  ["33 seed groups off the frozen panel", (_, row) => (row.panel.distinct_seeds = 33)],
  ["a same-user row", (_, row) => ((row as { isolation: string }).isolation = "same-user")],
  ["a row off the frozen panel", (_, row) => (row.panel.sha256 = "0".repeat(64))],
  ["a row sharing a headline id", (data, row) => (row.id = data.models[0].id)],
  [
    "an agentic row in the headline table",
    (data, row) => data.models.push({ ...data.models[0], id: row.id, lane: "agentic" as never }),
  ],
  [
    "an agentic row in the decision lane",
    (data, row) =>
      (data.decision_lane_models ?? []).push({
        ...(data.decision_lane_models ?? [])[0],
        id: row.id,
      }),
  ],
  ["a paired p-value", (_, row) => Object.assign(row, { paired_p_value: 0.01 })],
  ["a cross-model p-value", (_, row) => Object.assign(row, { vs_models: [{ id: "agentic:x", p_value: 0.2 }] })],
  ["a cross-harness p-value", (_, row) => Object.assign(row.harness, { holm_p_value: 0.04 })],
  ["a p-value inside the reference against another row", (_, row) => Object.assign(row.reference, { vs_row_p_value: 0.3 })],
  ["a row with no reference", (_, row) => delete (row as { reference?: unknown }).reference],
  ["a reference on the 29-seed 1.0 panel", (_, row) => (row.reference.num_seeds = 29)],
  ["a reference on other seasons", (_, row) => (row.reference.seasons = 1)],
  ["a reference against another agent", (_, row) => ((row.reference as { agent: string }).agent = "value")],
  ["a reference with per-seed lifts", (_, row) => Object.assign(row.reference, { per_seed: [{ lift: 3 }] })],
  ["per-seed lifts outside the reference", (_, row) => Object.assign(row, { per_seed: [] })],
  ["a reference with a cache path", (_, row) => Object.assign(row.reference, { baseline_cache: { hits: 1 } })],
  ["a reference with no random floor", (_, row) => ((row.reference.floor as { agent: string }).agent = "value")],
  ["a p-value inside the floor", (_, row) => Object.assign(row.reference.floor, { p_value: 0.01 })],
  ["a comparison inside the floor", (_, row) => Object.assign(row.reference.floor, { vs_model: "x" })],
  ["a lift that is not the row mean minus pick-trader's", (_, row) => (row.mean_score = 300)],
  ["a row not published under score-v2", (_, row) => Object.assign(row, { scoring_version: "score-v1" })],
  ["a row with no score-v1 comparison", (_, row) => delete (row as { score_v1?: unknown }).score_v1],
  ["a score-v1 comparison with a stray p-value", (_, row) => Object.assign(row.score_v1, { p_value: 0.01 })],
  ["a score-v1 comparison off the score-v1 pin", (_, row) => (row.score_v1.reference.mean_score = 260)],
  ["a score-v1 lift that is not its mean minus pick-trader's", (_, row) => (row.score_v1.mean_score = 300)],
  ["a score-v1 comparison with per-seed lifts", (_, row) => Object.assign(row.score_v1.reference, { per_seed: [{ lift: 1 }] })],
  [
    "an internally impossible reference",
    (_, row) => {
      row.reference.paired_lift_mean = 500;
      row.reference.paired_lift_ci95 = [-900, -800];
      row.reference.paired_lift_stddev = 0;
      row.reference.sign_flip_p_value = 1;
      row.reference.significant_at_95 = true;
      row.reference.candidate_seed_win_rate = 0;
    },
  ],
  ["an interval that excludes its own lift", (_, row) => (row.reference.paired_lift_ci95 = [-70, -55])],
  ["an interval far wider than its spread", (_, row) => (row.reference.paired_lift_stddev = 0)],
  ["a win rate of 1 with a negative lift", (_, row) => (row.reference.candidate_seed_win_rate = 1)],
  [
    "a win rate of 0 with a positive lift",
    (_, row) => {
      row.mean_score = round3(V2_PICK_TRADER + 40);
      row.reference.paired_lift_mean = 40;
      row.reference.paired_lift_ci95 = [30, 50];
      row.reference.candidate_seed_win_rate = 0;
    },
  ],
  [
    "two rows disagreeing on the pick-trader mean",
    (data, row) => {
      const other = structuredClone(row);
      other.id = `${row.id}:other`;
      other.mean_score = 210;
      other.reference.mean_score = 250;
      data.agentic_lane?.push(other);
    },
  ],
  [
    "two rows disagreeing on the random floor",
    (data, row) => {
      const other = structuredClone(row);
      other.id = `${row.id}:other`;
      other.reference.floor.mean_score = 91;
      data.agentic_lane?.push(other);
    },
  ],
  ["a reference with a reversed interval", (_, row) => (row.reference.paired_lift_ci95 = [-30, -50])],
  ["a reference whose p is not a probability", (_, row) => (row.reference.sign_flip_p_value = 1.5)],
  ["a reference flag that contradicts its interval", (_, row) => (row.reference.significant_at_95 = false)],
  ["a row with no unpinned flag", (_, row) => delete (row as { unpinned?: boolean }).unpinned],
  ["a pinned row with no pin", (_, row) => (row.unpinned = false)],
  ["a duplicate row", (data, row) => data.agentic_lane?.push(structuredClone(row))],
  [
    "an API-equivalent estimate equal to a billed cost",
    (_, row) => Object.assign(row, { telemetry: { cost_usd: 1.23, api_equivalent_cost_usd: 1.23 } }),
  ],
  [
    "mixed token shapes",
    (_, row) => Object.assign(row, { telemetry: { cost_usd: null, token_shape: "mixed" } }),
  ],
  [
    "an inclusive input total that does not add up",
    (_, row) =>
      Object.assign(row, {
        telemetry: {
          cost_usd: null,
          token_shape: "inclusive-v1",
          input_tokens: 100,
          uncached_input_tokens: 10,
          cached_input_tokens: 80,
          cache_write_input_tokens: 0,
        },
      }),
  ],
  [
    "a negative API-equivalent estimate",
    (_, row) => Object.assign(row, { telemetry: { cost_usd: null, api_equivalent_cost_usd: -1 } }),
  ],
];
for (const [label, edit] of agenticMustReject) {
  if (withAgentic(edit).length === 0) {
    throw new Error(`The agentic-lane check accepted ${label}`);
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
    `${(leaderboard.decision_lane_models ?? []).length} decision-lane row(s) kept apart; ` +
    `${(leaderboard.agentic_lane ?? []).length} GM-Bench 2.0 panel row(s); ` +
    `${agenticMustReject.length} agentic-lane rejection checks passed).`,
);
