import { describe, expect, test } from "bun:test";
import data from "../src/data/leaderboard.json";
import { modelRows } from "../src/v2";
import type { Leaderboard } from "../src/types";
import { CHART_AXES, chartRows, logTicks } from "../src/app/chartAxes";

const rows = modelRows(data as Leaderboard);
const axis = (id: string) => CHART_AXES.find(item => item.id === id)!;

describe("chart measurements from published telemetry", () => {
  test("tokens are full panel totals, per-game means divide by telemetry episodes", () => {
    for (const row of rows) {
      expect(axis("output-total").value(row)).toBe(row.source.telemetry.output_tokens);
      expect(axis("input-total").value(row)).toBe(row.source.telemetry.input_tokens);
      expect(axis("output-game").value(row)).toBe(row.source.telemetry.output_tokens! / 32);
      expect(axis("time").value(row)).toBe(row.source.telemetry.wall_seconds_per_episode / 60);
      expect(axis("calls").value(row)).toBe(row.source.telemetry.tool_calls_per_episode);
    }
  });
  test("null, partial and incompatible token telemetry never become zero", () => {
    for (const changes of [{ output_tokens: null }, { telemetry_episodes: 31 }, { telemetry_episodes: 0 }, { token_shape: "mixed" as const }, { token_shape: "legacy" as const }, { output_tokens: NaN }, { output_tokens: -1 }]) {
      const row = structuredClone(rows[0]);
      Object.assign(row.source.telemetry, changes);
      expect(chartRows([row], axis("output-total"))).toEqual([]);
      expect(chartRows([row], axis("output-game"))).toEqual([]);
    }
    const row = structuredClone(rows[0]);
    row.source.telemetry.output_tokens = 0;
    expect(chartRows([row], axis("output-total"))[0].xValue).toBe(0);
  });
  test("missing wall time and incomplete call coverage are excluded", () => {
    const row = structuredClone(rows[0]);
    Object.assign(row.source.telemetry, { wall_seconds_per_episode: null });
    expect(chartRows([row], axis("time"))).toEqual([]);
    row.source.telemetry.episodes = 0;
    expect(chartRows([row], axis("calls"))).toEqual([]);
  });
  test("cost excludes the unmeasured row and log ticks match wide token magnitudes", () => {
    expect(chartRows(rows, axis("cost"))).toHaveLength(rows.length - 1);
    expect(logTicks(100_000, 5_000_000)).toEqual([100_000, 300_000, 1_000_000, 3_000_000]);
    expect(logTicks(0.01, 0.3)).toEqual([0.01, 0.03, 0.1, 0.3]);
  });
});
