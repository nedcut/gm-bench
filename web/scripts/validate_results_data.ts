import leaderboardData from "../src/data/leaderboard.json";
import benchV2Lane from "../../config/bench_v2_lane.json";
import { agenticLaneIssues, type AgenticLanePanel } from "../src/agenticLane";
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
const lanePanel: AgenticLanePanel = {
  artifact_panel_sha256: benchV2Lane.seed_panel.artifact_panel_sha256,
  count: benchV2Lane.seed_panel.count,
};
const agenticIssues = agenticLaneIssues(leaderboard, lanePanel);
if (agenticIssues.length > 0) {
  throw new Error(`Agentic lane data is not publishable:\n  ${agenticIssues.join("\n  ")}`);
}

// The same rules must reject each way a 2.0 row could go wrong. The fixture is
// synthetic and lives only in memory.
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
  artifact_path: "results/agentic/fixture.json",
} as unknown as AgenticLaneRow;
function withAgentic(edit: (data: Leaderboard, row: AgenticLaneRow) => void): string[] {
  const data = structuredClone(leaderboard) as Leaderboard;
  const row = structuredClone(agenticFixture);
  data.agentic_lane = [row];
  edit(data, row);
  return agenticLaneIssues(data, lanePanel);
}
if (withAgentic(() => {}).length !== 0) {
  throw new Error(`A valid agentic fixture row was rejected: ${withAgentic(() => {}).join("; ")}`);
}
const pinnedFixtureIssues = withAgentic((_, row) => Object.assign(row, { unpinned: false, pin: "fixture/model@2026-01-01" }));
if (pinnedFixtureIssues.length !== 0) {
  throw new Error(`A valid pinned agentic fixture row was rejected: ${pinnedFixtureIssues.join("; ")}`);
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
  ["an off-panel reference score", (_, row) => Object.assign(row, { reference: { pick_trader: 247.1 } })],
  ["a row with no unpinned flag", (_, row) => delete (row as { unpinned?: boolean }).unpinned],
  ["a pinned row with no pin", (_, row) => (row.unpinned = false)],
  ["a duplicate row", (data, row) => data.agentic_lane?.push(structuredClone(row))],
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
