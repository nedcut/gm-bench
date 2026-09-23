import { fmt, numOrDash } from "../lib";
import type { AgenticLaneRow, Leaderboard as LeaderboardData } from "../types";

/* GM-Bench 2.0, the agentic lane, kept apart from every 1.0 table.
 *
 * A 2.0 row is a model running inside its own harness (OpenCode, Claude
 * Code, ...) and driving the simulator through MCP tools for one continuous
 * session per episode. It is a different contract from 1.0, so nothing here
 * feeds the shot chart, the headline count, the model profile, or the
 * decision lane, and nothing is paired against a 1.0 row. Only panel-grade
 * rows reach this component (the builder and the data validator both enforce
 * it); with none, it renders nothing at all. */

const REPO_BLOB = "https://github.com/nedcut/gm-bench/blob/main/";
const SPEC_DOC = `${REPO_BLOB}docs/bench_v2_spec.md`;
const LANE_DOC = `${REPO_BLOB}docs/agentic_lane.md`;

function harnessLabel(row: AgenticLaneRow): string {
  const { name, version, variant } = row.harness;
  return `${name} ${version}${variant ? ` · ${variant}` : ""}`;
}

function compactCount(value: number | null): string {
  if (value === null) return "—";
  if (value >= 1_000_000) return `${fmt(value / 1_000_000, 1)}M`;
  if (value >= 1_000) return `${fmt(value / 1_000, 1)}k`;
  return fmt(value, 0);
}

/* Tokens and cost are the harness's own accounting, averaged over the
 * episodes whose harness reported it. Absent telemetry is unmeasured, never
 * zero; partial telemetry says how many episodes it covers, on its own line. */
function Coverage({ row }: { row: AgenticLaneRow }) {
  const t = row.telemetry;
  if (t.telemetry_episodes >= t.episodes) return null;
  return (
    <span className="agentic-coverage muted">
      {t.telemetry_episodes} of {t.episodes} episodes
    </span>
  );
}

function tokensPerEpisode(row: AgenticLaneRow): string | null {
  const t = row.telemetry;
  if (t.telemetry_episodes === 0 || t.input_tokens === null) return null;
  const perEpisode = (value: number | null) =>
    value === null ? null : value / t.telemetry_episodes;
  return `${compactCount(perEpisode(t.input_tokens))} in / ${compactCount(perEpisode(t.output_tokens))} out`;
}

function costPerEpisode(row: AgenticLaneRow): string | null {
  const cost = row.telemetry.cost_per_episode_usd;
  return cost === null ? null : `$${fmt(cost, 3)}`;
}

function Measured({ row, text }: { row: AgenticLaneRow; text: string | null }) {
  if (text === null) return <>unmeasured</>;
  return (
    <>
      {text}
      <Coverage row={row} />
    </>
  );
}

function phasesByAgent(row: AgenticLaneRow): string {
  const ended = row.telemetry.phases_ended_by;
  const total = Object.values(ended).reduce((sum, count) => sum + count, 0);
  return `${fmt(ended.agent ?? 0, 0)} / ${fmt(total, 0)}`;
}

function wallMinutes(row: AgenticLaneRow): string {
  return `${fmt(row.telemetry.wall_seconds_per_episode / 60, 1)} min`;
}

/* Spec, Row identity and eligibility: an unpinned row carries the flag and a
 * plain sentence that it may not be reproducible. */
const UNPINNED_SENTENCE =
  "The model version or provider behind this row is not pinned, so the row may not be reproducible. It is an extra data point, not a headline.";

export default function AgenticLane({ data }: { data: LeaderboardData }) {
  const rows = data.agentic_lane ?? [];
  if (rows.length === 0) return null;

  return (
    <section className="analysis-section agentic-lane" id="agentic-lane">
      <div className="results-shell">
        <div className="analysis-heading">
          <div>
            <p className="kicker">GM-Bench 2.0 · agentic lane</p>
            <h2>A model in its own harness, driving the simulator through tools</h2>
          </div>
        </div>
        <p className="agentic-lane-intro">
          In 1.0 a model answered one bounded prompt per decision. In 2.0 the model runs inside its
          own agent harness and plays each five-season episode as one continuous session, calling
          MCP tools to read the league, act, end each phase, and keep its own notes. Budgets are
          reported, not capped: tool calls, tokens, cost, and wall time sit beside the score and
          never inside it. A row is one model in one harness at one version, so two harnesses on the
          same model are two rows, shown side by side with no p-value between them. Every row here
          ran the frozen private panel with the harness separated from the driver by a different
          user or a container, because a harness running as the driver's user can find the private
          seeds through the operating system. See the <a href={SPEC_DOC}>2.0 specification</a> and the{" "}
          <a href={LANE_DOC}>operator guide</a>.
        </p>
        <p className="agentic-lane-intro">
          Rows are listed by model and harness, not by score; 2.0 ranks nothing. No 1.0 score sits
          beside them: the 1.0 scripted references ran on a different panel, and the one comparison
          the specification supports is a pick-trader reference on the same 32 seeds, which is not
          yet published. A row marked <span className="agentic-unpinned">unpinned</span> runs a
          model whose version or provider is not pinned, so it may not be reproducible.
        </p>
        <div
          className="results-table-wrap"
          role="region"
          aria-label="GM-Bench 2.0 agentic lane results table"
          tabIndex={0}
        >
          <table className="results-table">
            <thead>
              <tr>
                <th>Model</th>
                <th>Harness</th>
                <th title="Mean of per-seed scores, ± their standard deviation across seeds">Score</th>
                <th title="Lowest and highest per-seed score">Seed range</th>
                <th title="Distinct private seeds, and how the harness was isolated from the driver">
                  Panel
                </th>
                <th>Tool calls / episode</th>
                <th title="Phases the agent closed itself, out of all phases; the rest were closed by the phase guard">
                  Closed by agent
                </th>
                <th title="Prompts sent when the harness stopped before the season was over, averaged over all episodes">
                  Nudges / episode
                </th>
                <th title="Harness-reported tokens, averaged over the episodes that reported them">
                  Tokens / episode
                </th>
                <th title="Harness-reported cost, averaged over the episodes that reported it">Cost / episode</th>
                <th>Wall / episode</th>
                <th title="Episodes where the harness's own tool-call count equals the server ledger, which is authoritative">
                  Ledger = harness
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td className="model-name">
                    <span>{row.model}</span>
                    {row.unpinned ? (
                      <span className="agentic-unpinned" title={UNPINNED_SENTENCE}>
                        unpinned
                      </span>
                    ) : null}
                    <a className="row-profile-link" href={REPO_BLOB + row.artifact_path}>
                      artifact ↗
                    </a>
                  </td>
                  <td>{harnessLabel(row)}</td>
                  <td className="numeric">
                    {fmt(row.mean_score, 1)}
                    <span className="muted"> ± {fmt(row.score_stddev, 1)}</span>
                  </td>
                  <td className="numeric">
                    {fmt(row.seed_mean_min, 1)} – {fmt(row.seed_mean_max, 1)}
                  </td>
                  <td>
                    {row.panel.distinct_seeds} seeds · {row.isolation}
                  </td>
                  <td className="numeric">{numOrDash(row.telemetry.tool_calls_per_episode, 1)}</td>
                  <td className="numeric">{phasesByAgent(row)}</td>
                  <td className="numeric">{fmt(row.telemetry.nudges_per_episode, 2)}</td>
                  <td className="numeric">
                    <Measured row={row} text={tokensPerEpisode(row)} />
                  </td>
                  <td className="numeric">
                    <Measured row={row} text={costPerEpisode(row)} />
                  </td>
                  <td className="numeric">{wallMinutes(row)}</td>
                  <td className="numeric">
                    {row.agreement.episodes_agreeing} / {row.agreement.episodes}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <ul className="agentic-lane-notes">
          {rows.map((row) => (
            <li key={row.id}>
              <strong>{row.model}</strong> in {harnessLabel(row)}:{" "}
              {row.unpinned ? `${UNPINNED_SENTENCE} ` : `Pinned to ${row.pin}. `}Agentic fingerprint{" "}
              <code>{row.contract.agentic_fingerprint}</code> on 1.0 contract{" "}
              <code>{row.contract.base_contract_fingerprint}</code>, tool surface{" "}
              <code>{row.contract.tool_surface}</code>, brief <code>{row.contract.brief}</code>. Panel{" "}
              <code title={row.panel.sha256}>{row.panel.sha256.slice(0, 16)}…</code>,{" "}
              {row.panel.episodes} episodes of {row.seasons} seasons,{" "}
              {fmt(row.telemetry.tool_calls, 0)} tool calls, {row.telemetry.guard_kills} guard stop
              {row.telemetry.guard_kills === 1 ? "" : "s"}, {row.illegal_actions ?? 0} illegal action
              {row.illegal_actions === 1 ? "" : "s"}.
              {row.v1_row_id
                ? ` The same model has a 1.0 row (${row.v1_row_id}); the two are different benchmarks and are not paired here.`
                : ""}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
