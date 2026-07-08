import type { Leaderboard as LeaderboardData, LeaderboardBaseline, LeaderboardModel } from "../types";
import { agentColor, fmt, pct } from "../lib";

const PROVIDER_LABELS: Record<string, string> = {
  openai: "OpenAI API",
  claude: "Claude Code",
  codex: "Codex CLI",
  ollama: "Ollama (local)",
  opencode: "opencode",
};

type Row =
  | { kind: "model"; rank: number; model: LeaderboardModel }
  | { kind: "baseline"; baseline: LeaderboardBaseline };

function buildRows(data: LeaderboardData): Row[] {
  const rows: Row[] = data.models.map((model, index) => ({ kind: "model", rank: index + 1, model }));
  for (const baseline of data.baselines) {
    rows.push({ kind: "baseline", baseline });
  }
  return rows.sort((a, b) => {
    const scoreA = a.kind === "model" ? a.model.mean_score : a.baseline.mean_score;
    const scoreB = b.kind === "model" ? b.model.mean_score : b.baseline.mean_score;
    return scoreB - scoreA;
  });
}

function cost(model: LeaderboardModel): string {
  if (model.cost_per_episode_usd === null) {
    return model.provider === "ollama" ? "$0" : "—";
  }
  return `$${fmt(model.cost_per_episode_usd, 2)}`;
}

function statusTag(model: LeaderboardModel) {
  const issues = model.sota_v1_issues.join("\n");
  if (model.sota_v1_eligible) {
    return (
      <span className="status-stack">
        <span className="tag tag-official" title={issues || "validated as sota-v1"}>
          sota-v1
        </span>
        {model.sota_v1_issues.length > 0 && (
          <span className="tag tag-warn" title={issues}>
            {model.sota_v1_issues.length} warning{model.sota_v1_issues.length === 1 ? "" : "s"}
          </span>
        )}
      </span>
    );
  }
  return (
    <span className="tag tag-dev" title={issues || "not validated as sota-v1"}>
      diagnostic
    </span>
  );
}

function LeaderboardTable({ data }: { data: LeaderboardData }) {
  const rows = buildRows(data);
  const maxScore = Math.max(...rows.map((row) => (row.kind === "model" ? row.model.mean_score : row.baseline.mean_score)));
  return (
    <div className="panel">
      <div className="panel-title">
        <h3>Official leaderboard</h3>
        <span>
          preset {data.preset.name} · {data.preset.seeds.length} seeds × {data.preset.seasons} seasons · updated {data.updated}
        </span>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Model</th>
              <th>Status</th>
              <th className="num">Score</th>
              <th></th>
              <th className="num">Lift vs panel</th>
              <th className="num">Fallback</th>
              <th className="num">Tok/decision</th>
              <th className="num">Cost/episode</th>
              <th className="num">Latency</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              if (row.kind === "baseline") {
                return (
                  <tr key={`baseline-${row.baseline.agent}`} className="is-reference">
                    <td className="mono-dim">·</td>
                    <td>
                      <span className="agent-cell">
                        <i className="agent-chip" style={{ background: agentColor(row.baseline.agent) }} />
                        {row.baseline.agent}
                        <span className="tag tag-baseline">scripted baseline</span>
                      </span>
                    </td>
                    <td>
                      <span className="tag tag-baseline">baseline</span>
                    </td>
                    <td className="num mono-dim">{fmt(row.baseline.mean_score, 1)}</td>
                    <td>
                      <div className="bar-track">
                        <div
                          className="bar-fill"
                          style={{
                            width: `${(row.baseline.mean_score / maxScore) * 100}%`,
                            background: agentColor(row.baseline.agent),
                            opacity: 0.35,
                          }}
                        />
                      </div>
                    </td>
                    <td className="num mono-dim">—</td>
                    <td className="num mono-dim">—</td>
                    <td className="num mono-dim">0</td>
                    <td className="num mono-dim">$0</td>
                    <td className="num mono-dim">—</td>
                  </tr>
                );
              }
              const { model, rank } = row;
              return (
                <tr key={model.id}>
                  <td className="mono-dim">{rank}</td>
                  <td>
                    <span className="agent-cell">
                      <i className="agent-chip" style={{ background: agentColor(model.provider) }} />
                      {model.model}
                      <span className="tag tag-candidate">{PROVIDER_LABELS[model.provider] ?? model.provider}</span>
                    </span>
                  </td>
                  <td>{statusTag(model)}</td>
                  <td className="num score-strong">{fmt(model.mean_score, 1)}</td>
                  <td>
                    <div className="bar-track">
                      <div
                        className="bar-fill"
                        style={{
                          width: `${(model.mean_score / maxScore) * 100}%`,
                          background: agentColor(model.provider),
                          opacity: 0.85,
                        }}
                      />
                    </div>
                  </td>
                  <td className="num mono-dim">
                    {model.paired_lift === null ? "—" : `${model.paired_lift >= 0 ? "+" : ""}${fmt(model.paired_lift, 1)}`}
                    {model.significant ? " ✓" : ""}
                  </td>
                  <td className="num mono-dim">{pct(model.fallback_rate)}</td>
                  <td className="num mono-dim">{model.tokens_per_decision === null ? "—" : fmt(model.tokens_per_decision, 0)}</td>
                  <td className="num mono-dim">{cost(model)}</td>
                  <td className="num mono-dim">
                    {model.api_latency_s_per_decision === null ? "—" : `${fmt(model.api_latency_s_per_decision, 1)}s`}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="legend">
        <span>sota-v1 = 3 repeats, official seed panel, full usage, low fallback, full baseline panel</span>
        <span>seed-panel hash is an integrity check for a known panel, not a secrecy mechanism</span>
        <span>contract fingerprint pins simulator, scoring, preset, and action schemas</span>
        <span>eligible rows may still show warnings (illegal actions, fallback, insignificant lift)</span>
        <span>diagnostic rows are useful evidence, but not frontier-model claims</span>
        <span>✓ lift significant at 95% (paired bootstrap)</span>
        <span>fallback = decisions answered by the adapter's fallback policy, not the model</span>
        <span>cost from measured tokens × published prices; CLI lanes report their own cost</span>
      </div>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="panel">
      <div className="panel-title">
        <h3>Model runs land here</h3>
        <span>telemetry is wired — the board fills as official runs complete</span>
      </div>
      <p style={{ maxWidth: 640 }}>
        Every leaderboard run records objective score with paired-lift confidence intervals,
        plus tokens, dollar cost, and latency for every decision the model makes. Run one lane
        and rebuild:
      </p>
      <pre>
        <code>
          {`LLM_API_KEY=... python -m gm_bench model --provider openai --model gpt-5.4 \\
  --preset leaderboard --repeats 3 --json > results/leaderboard/openai-gpt-5.4.json
python -m gm_bench validate-result results/leaderboard/openai-gpt-5.4.json --policy sota-v1
python web/scripts/build_leaderboard.py`}
        </code>
      </pre>
    </div>
  );
}

export default function Leaderboard({ data }: { data: LeaderboardData }) {
  return (
    <section className="section" id="leaderboard">
      <div className="shell">
        <div className="section-head">
          <p className="section-kicker">Leaderboard</p>
          <h2>Scores, cost, and speed — measured, not estimated.</h2>
          <p>
            Models manage the same franchises over the same {data.preset.seeds.length} seeds for {data.preset.seasons} seasons
            ({data.preset.decision_points_per_episode} decisions per franchise). Scripted baselines are shown as
            reference rows: <strong>pick-trader</strong> is the serious scripted bar to beat, <strong>random</strong> the floor.
          </p>
        </div>
        <LeaderboardTable data={data} />
        {data.models.length === 0 && <EmptyState />}
      </div>
    </section>
  );
}
