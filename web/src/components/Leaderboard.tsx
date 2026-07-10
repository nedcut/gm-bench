import type { Leaderboard as LeaderboardData, LeaderboardBaseline, LeaderboardModel } from "../types";
import { agentColor, fmt, pct } from "../lib";

const PROVIDER_LABELS: Record<string, string> = {
  openai: "OpenAI API",
  claude: "Claude Code",
  codex: "Codex CLI",
  ollama: "Ollama (local)",
  opencode: "opencode",
  cursor: "Cursor",
};

const REPO_DOCS = "https://github.com/nedcut/gm-bench/blob/main/docs/production_benchmark.md";

type Row =
  | { kind: "model"; model: LeaderboardModel }
  | { kind: "baseline"; baseline: LeaderboardBaseline };

function buildRows(data: LeaderboardData): Row[] {
  const rows: Row[] = [
    ...data.models.map((model) => ({ kind: "model" as const, model })),
    ...data.baselines.map((baseline) => ({ kind: "baseline" as const, baseline })),
  ];
  return rows.sort((a, b) => {
    const scoreA = a.kind === "model" ? a.model.mean_score : a.baseline.mean_score;
    const scoreB = b.kind === "model" ? b.model.mean_score : b.baseline.mean_score;
    return scoreB - scoreA;
  });
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

function BoardCallout({ data }: { data: LeaderboardData }) {
  const pickTrader = data.baselines.find((row) => row.agent === "pick-trader");
  const bestModel = [...data.models].sort((a, b) => b.mean_score - a.mean_score)[0];
  const cleared = bestModel && pickTrader ? bestModel.mean_score >= pickTrader.mean_score : false;

  return (
    <div className="board-callout">
      <div>
        <p className="board-callout-kicker">Current read</p>
        <p className="board-callout-body">
          {cleared
            ? "At least one model clears the pick-trader bar on this panel."
            : "No submitted model clears pick-trader yet. Treat current rows as diagnostics — the scripted bar is still ahead."}
        </p>
      </div>
      <div className="board-callout-stats">
        <div>
          <strong>{pickTrader ? fmt(pickTrader.mean_score, 1) : "—"}</strong>
          <span>pick-trader bar</span>
        </div>
        <div>
          <strong>{bestModel ? fmt(bestModel.mean_score, 1) : "—"}</strong>
          <span>best model</span>
        </div>
        <div>
          <strong>{data.preset.seeds.length}×{data.preset.seasons}</strong>
          <span>seeds × seasons</span>
        </div>
      </div>
    </div>
  );
}

function LeaderboardTable({ data }: { data: LeaderboardData }) {
  const rows = buildRows(data);
  const scores = rows.map((row) => (row.kind === "model" ? row.model.mean_score : row.baseline.mean_score));
  const maxScore = Math.max(...scores, 1);
  const minScore = Math.min(...scores, 0);
  const span = Math.max(maxScore - Math.min(minScore, 0), 1);

  return (
    <div className="panel">
      <div className="panel-title">
        <h3>Official panel</h3>
        <span>
          preset {data.preset.name} · seeds {data.preset.seeds.join("–")} · updated {data.updated}
        </span>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Entry</th>
              <th>Status</th>
              <th className="num">Score</th>
              <th></th>
              <th className="num">vs pick-trader</th>
              <th className="num">Lift vs panel</th>
              <th className="num">Illegal</th>
              <th className="num">Fallback</th>
              <th className="num">Latency</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => {
              if (row.kind === "baseline") {
                const vsBest =
                  data.baselines.find((b) => b.agent === "pick-trader")?.mean_score ?? row.baseline.mean_score;
                const delta = row.baseline.mean_score - vsBest;
                const width = `${((row.baseline.mean_score - Math.min(minScore, 0)) / span) * 100}%`;
                return (
                  <tr
                    key={`baseline-${row.baseline.agent}`}
                    className={row.baseline.agent === "pick-trader" ? "is-bar" : "is-reference"}
                  >
                    <td className="mono-dim">{index + 1}</td>
                    <td>
                      <span className="agent-cell">
                        <i className="agent-chip" style={{ background: agentColor(row.baseline.agent) }} />
                        {row.baseline.agent}
                        <span className="tag tag-baseline">
                          {row.baseline.agent === "pick-trader" ? "bar to beat" : "scripted"}
                        </span>
                      </span>
                    </td>
                    <td>
                      <span className="tag tag-baseline">baseline</span>
                    </td>
                    <td className="num score-strong">{fmt(row.baseline.mean_score, 1)}</td>
                    <td>
                      <div className="bar-track">
                        <div
                          className="bar-fill"
                          style={{
                            width,
                            background: agentColor(row.baseline.agent),
                            opacity: row.baseline.agent === "pick-trader" ? 0.9 : 0.35,
                          }}
                        />
                      </div>
                    </td>
                    <td className="num mono-dim">
                      {row.baseline.agent === "pick-trader"
                        ? "—"
                        : `${delta >= 0 ? "+" : ""}${fmt(delta, 1)}`}
                    </td>
                    <td className="num mono-dim">—</td>
                    <td className="num mono-dim">0</td>
                    <td className="num mono-dim">—</td>
                    <td className="num mono-dim">—</td>
                  </tr>
                );
              }
              const { model } = row;
              const vsBest = model.lift_vs_best_baseline;
              const width = `${((model.mean_score - Math.min(minScore, 0)) / span) * 100}%`;
              return (
                <tr key={model.id}>
                  <td className="mono-dim">{index + 1}</td>
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
                          width,
                          background: agentColor(model.provider),
                          opacity: 0.85,
                        }}
                      />
                    </div>
                  </td>
                  <td className="num mono-dim">
                    {vsBest === null ? "—" : `${vsBest >= 0 ? "+" : ""}${fmt(vsBest, 1)}`}
                  </td>
                  <td className="num mono-dim">
                    {model.paired_lift === null ? "—" : `${model.paired_lift >= 0 ? "+" : ""}${fmt(model.paired_lift, 1)}`}
                    {model.significant ? " ✓" : ""}
                  </td>
                  <td className="num mono-dim">{model.illegal_actions}</td>
                  <td className="num mono-dim">{pct(model.fallback_rate)}</td>
                  <td className="num mono-dim">
                    {model.api_latency_s_per_decision === null ? "—" : `${fmt(model.api_latency_s_per_decision, 1)}s`}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="legend legend-tight">
        <span>
          <strong>pick-trader</strong> is the serious scripted bar. Clearing it on this panel is the claim that matters.
        </span>
        <span>
          <strong>sota-v1</strong> means the run is structurally eligible (3 repeats, official seeds, usage coverage, low fallback) — not that the model is good.
        </span>
        <span>
          Strategy score and protocol penalties are reported separately in artifacts; illegal actions still hit the headline score.
        </span>
        <span>
          Read the{" "}
          <a href={REPO_DOCS} target="_blank" rel="noreferrer">
            production standard
          </a>{" "}
          before quoting a row.
        </span>
      </div>
    </div>
  );
}

function SubmitBlock() {
  return (
    <div className="panel submit-panel">
      <div className="panel-title">
        <h3>Submit a row</h3>
        <span>official preset · validate · rebuild</span>
      </div>
      <p>
        Run the leaderboard preset, validate against <code>sota-v1</code>, then refresh the site data.
        Full policy:{" "}
        <a href="https://github.com/nedcut/gm-bench/blob/main/docs/submitting_results.md" target="_blank" rel="noreferrer">
          submitting results
        </a>
        .
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
          <h2>One official panel. Beat pick-trader — or show why you didn’t.</h2>
          <p>
            Every model manages the same franchises over {data.preset.seeds.length} seeds ×{" "}
            {data.preset.seasons} seasons ({data.preset.decision_points_per_episode} decisions per
            episode). Scripted baselines stay on the board as reference rows. Cost and latency are
            measured when the adapter reports usage.
          </p>
        </div>
        <BoardCallout data={data} />
        <LeaderboardTable data={data} />
        <div className="leaderboard-foot">
          <SubmitBlock />
        </div>
      </div>
    </section>
  );
}
