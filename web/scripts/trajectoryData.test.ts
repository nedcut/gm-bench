import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { comparisonIssue, parseTrajectories, rosterChange } from "../src/trajectoryData";
const source = JSON.parse(readFileSync(new URL("../public/replay/trajectory-demo.json", import.meta.url), "utf8"));
const fresh = () => structuredClone(source);

describe("public trajectory evidence", () => {
  test("real pair has a matched start, reconciled scores and complete windows", () => {
    const data = parseTrajectories(fresh());
    expect(comparisonIssue(data.episodes[0], data.episodes[1])).toBeNull();
    expect(data.episodes.map(e => e.fixture.decisions.length)).toEqual([20, 20]);
    expect(data.episodes[0].score.final_score).toBeCloseTo(107.5535877262878, 8);
    expect(data.episodes[1].score.final_score).toBeCloseTo(198.14748468577113, 8);
  });
  test("same policy, empty and missing starting observations cannot form a pair", () => {
    const [a, b] = parseTrajectories(fresh()).episodes;
    expect(comparisonIssue(a, a)).toMatch(/different policies/);
    b.fixture.decisions[0].interaction_rounds[0].observation = undefined;
    expect(comparisonIssue(a, b)).toMatch(/unavailable/);
    b.fixture.decisions = [];
    expect(comparisonIssue(a, b)).toMatch(/no recorded/);
    expect(parseTrajectories({ ...fresh(), episodes: [] }).episodes).toEqual([]);
  });
  test.each(["seed", "user_team_id", "config", "contract", "observation", "windows"])("refuses incompatible %s", field => {
    const [a, b] = parseTrajectories(fresh()).episodes;
    if (field === "seed") b.fixture.seed = 2;
    if (field === "user_team_id") b.fixture.user_team_id = 3;
    if (field === "config") b.fixture.config.include_midseason = false;
    if (field === "contract") b.fixture.provenance!.contract_fingerprint = "other";
    if (field === "observation") b.fixture.decisions[0].interaction_rounds[0].observation!.team!.cap_room = 99;
    if (field === "windows") b.fixture.decisions.reverse();
    expect(comparisonIssue(a, b)).not.toBeNull();
  });
  test("missing later observations remain unavailable, not a zero roster", () => {
    const data = fresh();
    delete data.episodes[0].fixture.decisions[2].interaction_rounds[0].observation;
    expect(parseTrajectories(data).episodes).toHaveLength(2);
    expect(rosterChange(undefined, {})).toBeNull();
    expect(rosterChange({ team: { roster: [{ id: 1, name: "One" }] } }, { team: { roster: [{ id: 2, name: "Two" }] } })).toEqual({ added: [{ id: 2, name: "Two" }], removed: [{ id: 1, name: "One" }] });
  });
  test.each(["schema", "score", "results", "roster", "duplicates", "provenance", "null-player-number", "null-team-number"])("rejects malformed %s", field => {
    const data = fresh();
    if (field === "schema") data.schema = "private-trace";
    if (field === "score") data.episodes[1].score.final_score = 999;
    if (field === "results") data.episodes[1].fixture.decisions[0].results = [{ accepted: "yes" }];
    if (field === "roster") data.episodes[1].fixture.decisions[0].interaction_rounds[0].observation.team.roster = [null];
    if (field === "duplicates") data.episodes[1].fixture.agent = "conservative";
    if (field === "null-player-number") data.episodes[1].fixture.decisions[0].interaction_rounds[0].observation.team.roster[0].overall = null;
    if (field === "null-team-number") data.episodes[1].fixture.decisions[0].interaction_rounds[0].observation.team.cap_room = null;
    if (field === "provenance") data.starting_state_digest = "unknown";
    expect(() => parseTrajectories(data)).toThrow();
  });
});
