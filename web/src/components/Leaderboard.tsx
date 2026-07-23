import { useState } from "react";
import type { Leaderboard as LeaderboardData, LeaderboardModel, TieredLeaderboardModel } from "../types";
import { agentColor, fmt, pct } from "../lib";

const PROVIDER_LABELS: Record<string, string> = {
  openai: "OpenAI API",
  openrouter: "OpenRouter",
  claude: "Claude Code",
  codex: "Codex CLI",
  cursor: "Cursor CLI",
  ollama: "Ollama (local)",
  opencode: "opencode",
};

function cost(model: LeaderboardModel): string {
  if (model.cost_per_episode_usd === null) {
    return model.provider === "ollama" ? "$0" : "—";
  }
  return `$${fmt(model.cost_per_episode_usd, 2)}`;
}

function statusTag(model: LeaderboardModel) {
  const allIssues = model.sota_v2_issues ?? [];
  const issues = allIssues.join("\n");
  if (model.sota_v2_eligible) {
    return (
      <span className="status-stack">
        <span className="tag tag-official" title={issues || "validated as sota-v2"}>
          sota-v2
        </span>
        {allIssues.length > 0 && (
          <span
            className="tag tag-warn"
            title={issues}
            aria-label={`${allIssues.length} protocol flags: ${issues}`}
          >
            {allIssues.length} flag{allIssues.length === 1 ? "" : "s"}
          </span>
        )}
      </span>
    );
  }
  return (
    <span className="tag tag-warn" title={issues || "not validated as sota-v2"}>
      diagnostic
    </span>
  );
}

function liftCell(model: LeaderboardModel): string {
  if (model.paired_lift === null) {
    return "—";
  }
  const lift = `${model.paired_lift >= 0 ? "+" : ""}${fmt(model.paired_lift, 1)}`;
  const ci = model.ci95;
  if (!ci || ci.length !== 2) {
    return lift;
  }
  return `${lift} [${fmt(ci[0], 1)}, ${fmt(ci[1], 1)}]`;
}

function ModelTable({
  models,
  title,
  subtitle,
  withTiers,
}: {
  models: Array<LeaderboardModel | TieredLeaderboardModel>;
  title: string;
  subtitle: string;
  withTiers: boolean;
}) {
  const [showTelemetry, setShowTelemetry] = useState(false);
  let previousTier: number | undefined;
  return (
    <div className="panel">
      <div className="panel-title">
        <h3>{title}</h3>
        <div className="panel-title-actions">
          <span>{subtitle}</span>
          <button
            className="telemetry-toggle"
            type="button"
            aria-expanded={showTelemetry}
            onClick={() => setShowTelemetry((visible) => !visible)}
          >
            {showTelemetry ? "Hide telemetry" : "Show telemetry"}
          </button>
        </div>
      </div>
      <div className="table-wrap" tabIndex={0} role="region" aria-label={`${title} table`}>
        <table>
          <thead>
            <tr>
              {withTiers && <th>Tier</th>}
              <th>Model</th>
              <th className="num">Score</th>
              <th className="num">Lift vs panel [95% CI]</th>
              <th className="num">Cost/episode</th>
              <th>Status</th>
              {showTelemetry && (
                <>
                  <th className="num">Fallback</th>
                  <th className="num">Failed queries</th>
                  <th className="num">Input/dec</th>
                  <th className="num">Output/dec</th>
                  <th className="num">Latency</th>
                </>
              )}
            </tr>
          </thead>
          <tbody>
            {models.map((model) => {
              const tier = "tier" in model ? model.tier : undefined;
              const tierStarts = withTiers && tier !== previousTier;
              previousTier = tier;
              const latency =
                model.lane === "cli-harness"
                  ? model.harness_latency_s_per_decision
                  : model.api_latency_s_per_decision;
              return (
                <tr key={model.id} className={tierStarts && tier !== 1 ? "tier-start" : ""}>
                  {withTiers && (
                    <td>{tierStarts ? <span className="tier-chip">Tier {tier}</span> : <span className="mono-dim">·</span>}</td>
                  )}
                  <td>
                    <span className="agent-cell">
                      {model.model}
                      <span className="tag tag-candidate">{PROVIDER_LABELS[model.provider] ?? model.provider}</span>
                    </span>
                  </td>
                  <td className="num score-strong">{fmt(model.mean_score, 1)}</td>
                  <td className="num mono-dim">{liftCell(model)}</td>
                  <td className="num mono-dim">{cost(model)}</td>
                  <td>{statusTag(model)}</td>
                  {showTelemetry && (
                    <>
                      <td className="num mono-dim">{pct(model.fallback_rate)}</td>
                      <td className="num mono-dim">
                        {model.failed_queries === undefined ? "—" : model.failed_queries}
                      </td>
                      <td className="num mono-dim">
                        {model.input_tokens_per_decision === null ? "—" : fmt(model.input_tokens_per_decision, 0)}
                      </td>
                      <td className="num mono-dim">
                        {model.output_tokens_per_decision === null ? "—" : fmt(model.output_tokens_per_decision, 0)}
                      </td>
                      <td className="num mono-dim">
                        {latency === null ? "—" : `${fmt(latency, 1)}s`}
                      </td>
                    </>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="legend">
        {withTiers ? (
          <>
            <span>tiers group models whose paired-lift 95% intervals overlap</span>
            <span>per-model intervals are descriptive; family-wise claims follow the frozen Holm plan</span>
          </>
        ) : (
          <span>observational lane — uncontrolled tool loops; not comparable to the API lane</span>
        )}
        <span>lift vs panel = paired per-seed difference against the scripted-baseline mean</span>
        <span>fallback = decisions answered by the adapter policy, not the model</span>
      </div>
    </div>
  );
}

function BarTable({ data }: { data: LeaderboardData }) {
  const rows = [
    { agent: "oracle", mean_score: data.headroom.oracle, score_stddev: null as number | null, kind: "ceiling" },
    ...data.baselines.map((baseline) => ({
      agent: baseline.agent,
      mean_score: baseline.mean_score,
      score_stddev: baseline.score_stddev as number | null,
      kind: baseline.agent === "pick-trader" ? "bar" : "baseline",
    })),
  ];
  const maxScore = data.headroom.oracle;
  return (
    <div className="panel">
      <div className="panel-title">
        <h3>Scripted panel</h3>
        <span>
          preset {data.preset.name} · {data.preset.seeds.length} seeds × {data.preset.seasons} seasons
          {data.updated ? ` · updated ${data.updated}` : ""}
        </span>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Agent</th>
              <th></th>
              <th className="num">Mean score</th>
              <th className="num">σ</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.agent} className={row.kind === "bar" ? "is-bar" : row.kind === "ceiling" ? "is-ceiling" : ""}>
                <td>
                  <span className="agent-cell">
                    <i className="agent-chip" style={{ background: agentColor(row.agent) }} />
                    {row.agent}
                  </span>
                </td>
                <td>
                  {row.kind === "bar" && <span className="tag tag-bar">red line</span>}
                  {row.kind === "ceiling" && <span className="tag tag-baseline">oracle ceiling</span>}
                  {row.kind === "baseline" && <span className="tag tag-baseline">scripted</span>}
                </td>
                <td className="num score-strong">{fmt(row.mean_score, 1)}</td>
                <td className="num mono-dim">{row.score_stddev === null ? "—" : fmt(row.score_stddev, 1)}</td>
                <td>
                  <div className="bar-track">
                    <div
                      className="bar-fill"
                      style={{ width: `${(row.mean_score / maxScore) * 100}%`, background: agentColor(row.agent), opacity: row.kind === "baseline" ? 0.55 : 0.9 }}
                    />
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="legend">
        <span>every model row is paired against these seeds</span>
        <span>oracle sees hidden information no legal agent can</span>
      </div>
    </div>
  );
}

function Gate({ data }: { data: LeaderboardData }) {
  const { publication } = data;
  const laneFrozen = publication.frozen_output_token_cap !== null;
  const registryFrozen = publication.model_registry_frozen === true;
  const smokesDone = publication.smoke_gate_issues != null && publication.smoke_gate_issues.length === 0;
  const rowsMet = publication.eligible_headline_models >= publication.minimum_headline_models;
  const analysisDone = publication.panel_analysis_ready === true;
  const checks = [
    { done: laneFrozen, label: `compute policy frozen (${publication.frozen_output_token_cap ?? "—"}-token ceiling)` },
    { done: registryFrozen, label: "model registry frozen" },
    { done: smokesDone, label: "every registered route smoke-verified" },
    {
      done: rowsMet,
      label: `≥${publication.minimum_headline_models} eligible rows (${publication.eligible_headline_models} today)`,
    },
    { done: analysisDone, label: "Holm-adjusted panel analysis bound to artifacts" },
  ];
  return (
    <div className="gate">
      <div>
        <h3>Ranking withheld until every gate clears</h3>
        <p>
          v1 was withdrawn after a contract defect penalized some models unevenly. v2 publishes
          nothing until these checks pass: {publication.reason}.
        </p>
        <div className="gate-checks">
          {checks.map((check) => (
            <span key={check.label} className={check.done ? "done" : "todo"}>
              {check.label}
            </span>
          ))}
        </div>
      </div>
      <span className="stamp">Withheld</span>
    </div>
  );
}

function ArchiveNotice() {
  return (
    <div className="panel">
      <div className="panel-title">
        <h3>Archive: sota-v1 withdrawn</h3>
        <span>retained as evidence · not a ranking</span>
      </div>
      <p>
        Scores under the previous <code>sota-v1</code> contract were withdrawn. The scaffold prompt
        documented <code>{`{"type":"scout","prospect_id":N}`}</code> as valid, but the simulator
        only read <code>player_id</code> and silently rejected the documented form.
      </p>
      <p>
        The defect did not fall evenly across candidates. Raw artifacts remain in{" "}
        <code>results/leaderboard/archive-v1/</code>.
      </p>
    </div>
  );
}

function MechanicBreakdown({ models }: { models: LeaderboardModel[] }) {
  const mechanics = [
    ["draft", "Draft/scouting"],
    ["trades", "Trades"],
    ["cap_free_agency", "Cap/free agency"],
    ["lineup", "Lineup"],
    ["information_memory", "Information/memory"],
  ] as const;
  return (
    <div className="panel">
      <div className="panel-title">
        <h3>Accepted / rejected by mechanic</h3>
        <span>protocol outcomes</span>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Model</th>
              {mechanics.map(([key, label]) => (
                <th className="num" key={key}>
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {models.map((model) => (
              <tr key={model.id}>
                <td>{model.model}</td>
                {mechanics.map(([key]) => {
                  const outcome = model.mechanic_breakdown?.[key] ?? { accepted: 0, rejected: 0 };
                  return (
                    <td className="num mono-dim" key={key}>
                      {outcome.accepted} / {outcome.rejected}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Footnotes({ data }: { data: LeaderboardData }) {
  const contract = data.contract;
  const cap = data.publication.frozen_output_token_cap;
  const registryFrozen = data.publication.model_registry_frozen === true;
  return (
    <div className="footnotes" id="integrity">
      <div className="footnote">
        <h4>Contract</h4>
        <p>
          Simulator, scoring, presets, and schemas hash to{" "}
          <code>{contract?.contract_fingerprint ?? "—"}</code>.
        </p>
      </div>
      <div className="footnote">
        <h4>Compute</h4>
        {cap ? (
          <p>
            Shared {cap.toLocaleString("en-US")}-token output ceiling, reasoning off, JSON mode on;
            routes {registryFrozen ? "pinned" : "pending smoke verification"}.
          </p>
        ) : (
          <p>Compute policy still pending — no fixed-ceiling claim published.</p>
        )}
      </div>
      <div className="footnote">
        <h4>Tiers</h4>
        <p>
          Holm-corrected paired contrasts froze before data. Overlapping uncertainty publishes as
          one tier — not an ordinal #1.
        </p>
      </div>
      <div className="footnote">
        <h4>Evidence</h4>
        <p>
          Runs are serial, checkpointed, spend-capped; artifacts hash-linked. Valid poor results are
          not re-run.
        </p>
      </div>
    </div>
  );
}

export default function Leaderboard({ data }: { data: LeaderboardData }) {
  const publishable = data.publication.publishable_ranking;
  return (
    <section className="section" id="leaderboard">
      <div className="shell">
        <div className="section-head">
          <p className="kicker">Standings</p>
          <h2>Tiers from paired lifts, not a #1 ranking.</h2>
          <p>
            Same franchises, same {data.preset.seeds.length} seeds, {data.preset.seasons} seasons (
            {data.preset.decision_points_per_episode} decisions per franchise), paired per-seed
            against the scripted panel.
          </p>
        </div>
        {!publishable && <Gate data={data} />}
        {publishable && (
          <ModelTable
            models={data.models}
            title="API lane"
            subtitle={`frozen ${data.publication.frozen_output_token_cap?.toLocaleString("en-US")}-token ceiling · reasoning off · ${data.updated ? `updated ${data.updated}` : "sota-v2"}`}
            withTiers
          />
        )}
        {publishable && data.models.length > 0 && <MechanicBreakdown models={data.models} />}
        <div style={{ marginTop: 14 }}>
          <BarTable data={data} />
        </div>
        {data.cli_harness_models.length > 0 && (
          <>
            <p className="lane-note" style={{ marginTop: 14 }}>
              Coding-harness rows use each CLI agent’s own tool loop, context, and retries. Separate
              table by design — not mixed with the API lane.
            </p>
            <ModelTable
              models={data.cli_harness_models}
              title="Coding-harness lane"
              subtitle="observational · separate table"
              withTiers={false}
            />
          </>
        )}
        <Footnotes data={data} />
        <div style={{ marginTop: 14 }}>
          <ArchiveNotice />
        </div>
      </div>
    </section>
  );
}
