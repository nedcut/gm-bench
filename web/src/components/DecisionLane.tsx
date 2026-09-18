import { fmt, numOrDash, pctOrDash } from "../lib";
import type { DecisionLaneModel, Leaderboard as LeaderboardData } from "../types";

/* The decision-model lane, kept apart from the headline on purpose.
 *
 * A chat model reads the observation and writes the action batch itself. A
 * decision model such as TypeSafe's Jev cannot write anything: the adapter
 * asks it a fixed list of typed questions (which free agent, whom to dress,
 * accept this offer or not) and composes the batch from the answers under
 * published rules. The score therefore measures the model plus that question
 * scaffold, the row sits outside the pre-registered Holm family, and the only
 * comparison it supports is against the same scripted baselines the headline
 * rows face. Nothing here feeds the shot chart, the "above the bar" count, or
 * the model profile. */

const LANE_DOC = "https://github.com/nedcut/gm-bench/blob/main/docs/typesafe_jev_lane.md";
const REPO_BLOB = "https://github.com/nedcut/gm-bench/blob/main/";

function ci(model: DecisionLaneModel): string {
  const interval = model.full_panel_ci95;
  if (!interval || interval.length !== 2) return "not reported";
  return `[${fmt(interval[0], 1)}, ${fmt(interval[1], 1)}]`;
}

function knobs(model: DecisionLaneModel): string {
  return Object.entries(model.provider_options)
    .map(([key, value]) => `${key}=${value}`)
    .join(" ");
}

export default function DecisionLane({ data }: { data: LeaderboardData }) {
  const rows = data.decision_lane_models ?? [];
  if (rows.length === 0) return null;
  const pickTrader = data.baselines.find((baseline) => baseline.agent === "pick-trader");
  const seedCount = rows[0].seed_count ?? data.preset.seed_count ?? null;

  return (
    <section className="analysis-section decision-lane" id="decision-lane">
      <div className="results-shell">
        <div className="analysis-heading">
          <div>
            <p className="kicker">Decision-model lane</p>
            <h2>A model that answers questions instead of writing the batch</h2>
          </div>
        </div>
        <p className="decision-lane-intro">
          These rows ran the same contract, the same {seedCount ?? "private"}-seed private panel,
          and the same eight scripted baselines as the headline above, but the model never wrote an
          action. The adapter asked it a fixed set of typed questions each decision and composed the
          batch from the answers under{" "}
          <a href={LANE_DOC}>published rules</a>. Read a score here as the model plus that question
          scaffold. The lane is not in the pre-registered Holm family and has no place in the shot
          chart or the headline count; its comparison is against the scripted baselines only.
        </p>
        <div
          className="results-table-wrap"
          role="region"
          aria-label="Decision-model lane results table"
          tabIndex={0}
        >
          <table className="results-table">
            <thead>
              <tr>
                <th>Model</th>
                <th>Score</th>
                <th title="Paired lift versus the mean of the whole baseline panel, with its 95% interval. Descriptive, not a headline claim.">
                  Lift vs panel mean
                </th>
                <th title="Share of seeds on which the row beat the baseline panel mean">
                  Seed win rate
                </th>
                <th title="Paired lift versus pick-trader, the strongest scripted baseline">
                  vs pick-trader
                </th>
                <th title="Actions the simulator refused; each one costs a protocol penalty inside the score">
                  Illegal
                </th>
                <th>Cost / episode</th>
                <th title="Input tokens per decision. The gateway also reports answer tokens, billed at zero.">
                  Input tokens / decision
                </th>
                <th>Latency / decision</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((model) => (
                <tr key={model.id}>
                  <td className="model-name">
                    <span>{model.model}</span>
                    <a className="row-profile-link" href={REPO_BLOB + model.artifact_path}>
                      artifact ↗
                    </a>
                  </td>
                  <td className="numeric strong">
                    {fmt(model.mean_score, 1)}
                    <span className="muted"> ± {fmt(model.score_stddev, 1)}</span>
                  </td>
                  <td className="numeric ci-cell">
                    {numOrDash(model.full_panel_lift, 1)} {ci(model)}
                  </td>
                  <td className="numeric">{pctOrDash(model.seed_win_rate, 0)}</td>
                  <td className="numeric">{numOrDash(model.lift_vs_best_baseline, 1)}</td>
                  <td className="numeric">{model.illegal_actions.toLocaleString("en-US")}</td>
                  <td className="numeric">${fmt(model.cost_per_episode_usd ?? 0, 3)}</td>
                  <td className="numeric">{numOrDash(model.input_tokens_per_decision, 0)}</td>
                  <td className="numeric">{numOrDash(model.api_latency_s_per_decision, 2)} s</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <ul className="decision-lane-notes">
          {rows.map((model) => (
            <li key={model.id}>
              <strong>{model.model}</strong> over {model.route}. Pinned knobs:{" "}
              <code>{knobs(model)}</code>. Scaffold fingerprint{" "}
              <code>{model.scaffold_fingerprint ?? "unrecorded"}</code>, {model.decision_points}{" "}
              decisions, total cost ${fmt(model.cost_usd ?? 0, 2)}.
              {pickTrader && model.lift_vs_best_baseline !== null
                ? ` It trails pick-trader (${fmt(pickTrader.mean_score, 1)}) by ${fmt(
                    Math.abs(model.lift_vs_best_baseline),
                    1,
                  )} points on the paired contrast.`
                : ""}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
