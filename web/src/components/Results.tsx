import type { Snapshot } from "../types";
import { agentColor, fmt, pct } from "../lib";
import { LiftChart, SeasonTraceChart } from "./Charts";

function StandingsTable({ snapshot }: { snapshot: Snapshot }) {
  const { standings, config } = snapshot;
  const maxScore = Math.max(...standings.map((row) => row.mean_score));
  return (
    <div className="panel">
      <div className="panel-title">
        <h3>Agent standings</h3>
        <span>
          seeds {config.seeds.join(" ")} · {config.seasons} seasons
        </span>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Agent</th>
              <th className="num">Mean score</th>
              <th></th>
              <th className="num">σ</th>
              <th className="num">Wins/ep</th>
              <th className="num">Titles</th>
              <th className="num">Illegal</th>
            </tr>
          </thead>
          <tbody>
            {standings.map((row, index) => (
              <tr key={row.agent} className={row.agent === config.candidate ? "is-candidate" : ""}>
                <td className="mono-dim">{index + 1}</td>
                <td>
                  <span className="agent-cell">
                    <i className="agent-chip" style={{ background: agentColor(row.agent) }} />
                    {row.agent}
                    <span className={`tag ${row.agent === config.candidate ? "tag-candidate" : "tag-baseline"}`}>
                      {row.agent === config.candidate ? "candidate" : "baseline"}
                    </span>
                  </span>
                </td>
                <td className="num score-strong">{fmt(row.mean_score, 1)}</td>
                <td>
                  <div className="bar-track">
                    <div
                      className="bar-fill"
                      style={{
                        width: `${(row.mean_score / maxScore) * 100}%`,
                        background: agentColor(row.agent),
                        opacity: 0.85,
                      }}
                    />
                  </div>
                </td>
                <td className="num mono-dim">{fmt(row.score_stddev, 1)}</td>
                <td className="num mono-dim">{fmt(row.mean_wins, 1)}</td>
                <td className="num mono-dim">{row.titles}</td>
                <td className="num mono-dim">{row.illegal_actions}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Verdict({ snapshot }: { snapshot: Snapshot }) {
  const { normalized, paired } = snapshot;
  return (
    <div className="panel verdict">
      <div className="panel-title">
        <h3>Paired evaluation verdict</h3>
        <span>value vs panel</span>
      </div>
      <div>
        <div className="verdict-big">
          +{fmt(paired.paired_lift_mean, 1)}
          <small>paired lift</small>
        </div>
        {paired.significant_at_95 && (
          <p style={{ marginTop: 10 }}>
            <span className="sig-pill">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                <path d="M20 6 9 17l-5-5" />
              </svg>
              significant at 95%
            </span>
          </p>
        )}
      </div>
      <div>
        <div className="verdict-row">
          <span>Candidate mean score</span>
          <strong>{fmt(normalized.candidate_mean_score, 1)}</strong>
        </div>
        <div className="verdict-row">
          <span>Baseline panel mean</span>
          <strong>{fmt(normalized.baseline_panel_mean_score, 1)}</strong>
        </div>
        <div className="verdict-row">
          <span>Bootstrap 95% CI on lift</span>
          <strong>
            [{fmt(paired.paired_lift_ci95[0], 1)}, {fmt(paired.paired_lift_ci95[1], 1)}]
          </strong>
        </div>
        <div className="verdict-row">
          <span>Seed win rate vs panel</span>
          <strong>{pct(paired.candidate_seed_win_rate)}</strong>
        </div>
        {paired.best_baseline && (
          <div className="verdict-row">
            <span>vs best baseline ({paired.best_baseline.agent})</span>
            <strong>
              +{fmt(paired.best_baseline.paired_lift_mean, 1)} · {pct(paired.best_baseline.seed_win_rate)} seeds
            </strong>
          </div>
        )}
        <div className="verdict-row">
          <span>Illegal actions (candidate)</span>
          <strong>{normalized.candidate_illegal_actions}</strong>
        </div>
      </div>
    </div>
  );
}

export default function Results({ snapshot }: { snapshot: Snapshot }) {
  return (
    <section className="section" id="results">
      <div className="shell">
        <div className="section-head">
          <p className="section-kicker">Reference results</p>
          <h2>Scripted baselines set the bar. Beat them on identical seeds.</h2>
          <p>
            Every agent plays the exact same league generations. Per-seed differencing cancels
            league luck, and a deterministic bootstrap puts a confidence interval on the lift —
            so a handful of seeds still gives an honest read on skill.
          </p>
        </div>
        <div className="results-grid">
          <StandingsTable snapshot={snapshot} />
          <Verdict snapshot={snapshot} />
        </div>
        <div className="charts-grid">
          <LiftChart snapshot={snapshot} />
          <SeasonTraceChart snapshot={snapshot} />
        </div>
      </div>
    </section>
  );
}
