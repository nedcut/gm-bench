import { fmt, numOrDash, pctOrDash } from "../lib";
import type { AgenticLaneRow, Leaderboard as LeaderboardData } from "../types";

/* GM-Bench 2.0, the agentic lane, kept apart from every 1.0 table.
 *
 * A 2.0 row is a model running inside its own harness (OpenCode, Claude
 * Code, ...) and driving the simulator through MCP tools for one continuous
 * session per episode. It is a different contract from 1.0, so nothing here
 * feeds the shot chart, the headline count, the model profile, or the
 * decision lane, and nothing is paired against a 1.0 row. The one inference
 * shown is the spec's predeclared contrast: each row against pick-trader on
 * the row's own seeds. Rows are never compared with each other. Only
 * panel-grade rows reach this component (the builder and the data validator
 * both enforce it); with none, it renders nothing at all. */

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

function tokensTitle(row: AgenticLaneRow): string {
  const t = row.telemetry;
  if (t.token_shape === "legacy") {
    return "Recorded before the shared token shape: input and output follow the harness's own convention.";
  }
  const parts = ["Input includes cached and cache-write tokens; output includes reasoning."];
  if (t.input_tokens && t.cached_input_tokens !== null) {
    parts.push(`${fmt((100 * t.cached_input_tokens) / t.input_tokens, 0)}% of input was read from cache.`);
  }
  if (t.output_tokens && t.reasoning_tokens) {
    parts.push(`${fmt((100 * t.reasoning_tokens) / t.output_tokens, 0)}% of output was reasoning.`);
  }
  return parts.join(" ");
}

function tokensPerEpisode(row: AgenticLaneRow): string | null {
  const t = row.telemetry;
  if (t.telemetry_episodes === 0 || t.input_tokens === null) return null;
  const perEpisode = (value: number | null) =>
    value === null ? null : value / t.telemetry_episodes;
  return `${compactCount(perEpisode(t.input_tokens))} in / ${compactCount(perEpisode(t.output_tokens))} out`;
}

const ESTIMATE_TITLE =
  "API-equivalent estimate: the tokens this harness reported, priced at the model's API list price " +
  "(cached input at the cached rate, short-context rates). Not billed: the harness reports no cost, " +
  "and a subscription is not charged per token.";

function costPerEpisode(row: AgenticLaneRow): string | null {
  const cost = row.telemetry.cost_per_episode_usd;
  return cost === null ? null : `$${fmt(cost, 3)}`;
}

/* A billed or harness-reported cost wins; without one, the list-price
 * estimate shows, marked "est.", with its basis in the title; with neither,
 * the cost is unmeasured. */
function CostCell({ row }: { row: AgenticLaneRow }) {
  const billed = costPerEpisode(row);
  if (billed !== null) return <Measured row={row} text={billed} />;
  const t = row.telemetry;
  const estimate = t.api_equivalent_cost_per_episode_usd ?? null;
  if (estimate === null) return <>unmeasured</>;
  const covered = t.api_equivalent_cost_episodes ?? t.telemetry_episodes;
  const longContext = t.api_equivalent_long_context_possible
    ? " Some turns exceeded the long-context threshold, so the estimate may be low."
    : "";
  return (
    <>
      <span className="agentic-estimate" title={ESTIMATE_TITLE + longContext}>
        ${fmt(estimate, 3)} est.
      </span>
      {covered < t.episodes && (
        <span className="agentic-coverage muted">
          {covered} of {t.episodes} episodes
        </span>
      )}
    </>
  );
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

/* A subscription harness (Codex) reports its plan's usage windows; the
 * panel pauses when one is nearly used up. Shown as a short note, never as
 * a cost. */
function quotaNote(row: AgenticLaneRow): string {
  const quota = row.telemetry.quota;
  if (!quota) return "";
  const plan = quota.plan_types.length > 0 ? `${quota.plan_types.join(", ")} plan` : "subscription";
  const peak = quota.max_used_percent === null ? "" : `, peak ${fmt(quota.max_used_percent, 0)}% of a usage window`;
  const pauses =
    quota.pauses > 0
      ? `, ${quota.pauses} quota pause${quota.pauses === 1 ? "" : "s"} (${fmt(quota.pause_seconds / 60, 0)} min)`
      : "";
  return ` Quota: ${plan}${peak}${pauses}.`;
}

function signed(value: number, digits = 1): string {
  const text = fmt(Math.abs(value), digits);
  if (text === fmt(0, digits)) return text;
  return value > 0 ? `+${text}` : `−${text}`;
}

function pValue(p: number): string {
  return p < 0.001 ? "p < 0.001" : `p = ${fmt(p, 3)}`;
}

/* The row's per-seed score minus pick-trader's on the same seeds, with the
 * bootstrap 95% interval and the sign-flip p-value. */
function referenceLift(row: AgenticLaneRow): string {
  const r = row.reference;
  const [low, high] = r.paired_lift_ci95;
  return `${signed(r.paired_lift_mean)} [${signed(low)}, ${signed(high)}]`;
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
          Rows are listed by model and harness, not by score; 2.0 ranks nothing. The one comparison
          the specification supports is each row against the scripted pick-trader policy on the same
          seeds and seasons: the <em>vs pick-trader</em> column is the row's per-seed score minus
          pick-trader's, averaged over the panel, with its 95% interval and sign-flip p-value.
          Pick-trader is played by the 1.0 simulator's own baseline runner at redaction time, so its
          score is the one a 1.0 run on these seeds gets. There is no p-value between two rows, two
          harnesses, or two models, and no 1.0 row's score is placed beside a 2.0 row. A row
          marked <span className="agentic-unpinned">unpinned</span> runs a model whose version or
          provider is not pinned, so it may not be reproducible.
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
                <th title="Row score minus pick-trader's on the same seeds and seasons: mean of per-seed differences, bootstrap 95% interval, and two-sided sign-flip p-value. The only inference the 2.0 specification supports.">
                  vs pick-trader (same seeds)
                </th>
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
                <th title="Harness-reported cost, averaged over the episodes that reported it. Marked est.: an API-equivalent list-price estimate for a harness that reports no cost; not billed.">
                  Cost / episode
                </th>
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
                  <td className="numeric">
                    {referenceLift(row)}
                    <span className="muted"> · {pValue(row.reference.sign_flip_p_value)}</span>
                  </td>
                  <td>
                    {row.panel.distinct_seeds} seeds · {row.isolation}
                  </td>
                  <td className="numeric">{numOrDash(row.telemetry.tool_calls_per_episode, 1)}</td>
                  <td className="numeric">{phasesByAgent(row)}</td>
                  <td className="numeric">{fmt(row.telemetry.nudges_per_episode, 2)}</td>
                  <td className="numeric">
                    <span title={tokensTitle(row)}>
                      <Measured row={row} text={tokensPerEpisode(row)} />
                    </span>
                  </td>
                  <td className="numeric">
                    <CostCell row={row} />
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
              pick-trader {fmt(row.reference.mean_score, 1)} and random{" "}
              {fmt(row.reference.floor.mean_score, 1)} on the same {row.reference.num_seeds} seeds,
              ahead of pick-trader on {pctOrDash(row.reference.candidate_seed_win_rate, 0)} of them,{" "}
              {fmt(row.telemetry.tool_calls, 0)} tool calls, {row.telemetry.guard_kills} guard stop
              {row.telemetry.guard_kills === 1 ? "" : "s"},{" "}
              {row.telemetry.provider_stalls > 0
                ? `${row.telemetry.provider_stalls} provider stall${row.telemetry.provider_stalls === 1 ? "" : "s"} (${fmt(row.telemetry.provider_stall_wait_seconds / 60, 0)} min of backoff), `
                : ""}
              {row.illegal_actions ?? 0} illegal action
              {row.illegal_actions === 1 ? "" : "s"}.
              {quotaNote(row)}
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
