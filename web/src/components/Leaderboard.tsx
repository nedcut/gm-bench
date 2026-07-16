import type { Leaderboard as LeaderboardData, LeaderboardModel } from "../types";
import { agentColor, COLOR, fmt, pct } from "../lib";

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
          <span className="tag tag-warn" title={issues}>
            {allIssues.length} warning{allIssues.length === 1 ? "" : "s"}
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
  data,
  models,
  title,
  subtitle,
  withTiers,
}: {
  data: LeaderboardData;
  models: LeaderboardModel[];
  title: string;
  subtitle: string;
  withTiers: boolean;
}) {
  const maxScore = Math.max(data.headroom.oracle, ...models.map((model) => model.mean_score));
  let previousTier: number | undefined;
  return (
    <div className="panel">
      <div className="panel-title">
        <h3>{title}</h3>
        <span>{subtitle}</span>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {withTiers && <th>Tier</th>}
              <th>Model</th>
              <th>Status</th>
              <th className="num">Score</th>
              <th></th>
              <th className="num">Lift vs panel [95% CI]</th>
              <th className="num">Fallback</th>
              <th className="num">Failed queries</th>
              <th className="num">Input/dec</th>
              <th className="num">Output/dec</th>
              <th className="num">Cost/episode</th>
              <th className="num">Latency</th>
            </tr>
          </thead>
          <tbody>
            {models.map((model) => {
              const tierStarts = withTiers && model.tier !== previousTier;
              previousTier = model.tier;
              return (
                <tr key={model.id} className={tierStarts && model.tier !== 1 ? "tier-start" : ""}>
                  {withTiers && (
                    <td>{tierStarts ? <span className="tier-chip">Tier {model.tier}</span> : <span className="mono-dim">·</span>}</td>
                  )}
                  <td>
                    <span className="agent-cell">
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
                        style={{ width: `${Math.max(0, (model.mean_score / maxScore) * 100)}%`, background: COLOR.blue }}
                      />
                    </div>
                  </td>
                  <td className="num mono-dim">{liftCell(model)}</td>
                  <td className="num mono-dim">{pct(model.fallback_rate)}</td>
                  <td className="num mono-dim">{model.failed_queries === undefined ? "—" : model.failed_queries}</td>
                  <td className="num mono-dim">
                    {model.input_tokens_per_decision === null ? "—" : fmt(model.input_tokens_per_decision, 0)}
                  </td>
                  <td className="num mono-dim">
                    {model.output_tokens_per_decision === null ? "—" : fmt(model.output_tokens_per_decision, 0)}
                  </td>
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
        {withTiers ? (
          <>
            <span>tiers group models whose paired-lift 95% intervals overlap — order inside a tier is display order, not a claim</span>
            <span>per-model intervals are descriptive; family-wise claims follow the frozen Holm-corrected analysis plan</span>
          </>
        ) : (
          <span>observational lane — uncontrolled tool loops, context, and retries; no tiers, not comparable to the API lane</span>
        )}
        <span>lift vs panel = paired per-seed difference against the full scripted-baseline mean</span>
        <span>fallback = decisions answered by the adapter's fallback policy, not the model</span>
        <span>cost from measured tokens × published prices; read score next to input/output tokens and cost, never alone</span>
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
        <h3>The bar, measured</h3>
        <span>
          scripted panel · preset {data.preset.name} · {data.preset.seeds.length} seeds × {data.preset.seasons} seasons
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
                  {row.kind === "bar" && <span className="tag tag-bar">the red line</span>}
                  {row.kind === "ceiling" && <span className="tag tag-baseline">hidden-information ceiling</span>}
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
        <span>every model row is paired against these exact seeds — the panel is the control group</span>
        <span>the oracle sees hidden information no legal agent can; it bounds what the score can express</span>
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
  const checks = [
    { done: laneFrozen, label: `compute policy frozen (${publication.frozen_output_token_cap ?? "—"}-token ceiling)` },
    { done: registryFrozen, label: "model registry frozen" },
    { done: smokesDone, label: "every registered route smoke-verified" },
    {
      done: rowsMet,
      label: `≥${publication.minimum_headline_models} strictly eligible rows (${publication.eligible_headline_models} today)`,
    },
  ];
  return (
    <div className="gate">
      <div>
        <h3>No ranking yet — that is the protocol working</h3>
        <p>
          The previous version of this table was withdrawn when a contract defect was found to
          penalize some models and not others. The v2 board therefore publishes nothing until every
          gate below is machine-verified: {publication.reason}.
        </p>
        <p>
          Scores cannot influence the protocol — the contract, compute policy, model registry, and
          statistical analysis plan freeze <em>before</em> official runs, and a valid poor result is
          never re-run.
        </p>
        <div className="gate-checks">
          {checks.map((check) => (
            <span key={check.label} className={check.done ? "done" : "todo"}>
              {check.label}
            </span>
          ))}
        </div>
      </div>
      <span className="stamp">Withheld by design</span>
    </div>
  );
}

function ArchiveNotice() {
  return (
    <div className="panel">
      <div className="panel-title">
        <h3>Withdrawn: the sota-v1 results</h3>
        <span>retained as evidence · not a ranking</span>
      </div>
      <p>
        Every score published under the previous <code>sota-v1</code> contract has been withdrawn.
        The scaffold prompt documented <code>{`{"type":"scout","prospect_id":N}`}</code> as a valid
        action, but the simulator only ever read <code>player_id</code> and silently rejected the
        documented form — with no protocol penalty, so the rejections never appeared in any summary.
      </p>
      <p>
        The defect did not fall evenly. It cost some candidates over a thousand silently-rejected
        lookups and others none at all, while the scripted baselines were untouched. The v1 table was
        therefore not a valid ranking of the models in it, and no caveat makes it one. The raw
        artifacts remain in <code>results/leaderboard/archive-v1/</code> as evidence of the defect.
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
        <h3>Protocol outcomes by mechanic</h3>
        <span>accepted / rejected actions</span>
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

export default function Leaderboard({ data }: { data: LeaderboardData }) {
  const publishable = data.publication.publishable_ranking;
  return (
    <section className="section" id="leaderboard">
      <div className="shell">
        <div className="section-head">
          <p className="kicker">The board</p>
          <h2>Tiers, not ranks. Evidence, not vibes.</h2>
          <p>
            Models manage the same franchises over the same {data.preset.seeds.length} seeds for{" "}
            {data.preset.seasons} seasons ({data.preset.decision_points_per_episode} decisions per
            franchise), paired per-seed against the scripted panel. The frozen analysis plan
            publishes overlapping-uncertainty <strong>tiers</strong> — never an ordinal #1.
          </p>
        </div>
        {!publishable && <Gate data={data} />}
        {publishable && (
          <ModelTable
            data={data}
            models={data.models}
            title="Official API leaderboard"
            subtitle={`frozen ${data.publication.frozen_output_token_cap?.toLocaleString("en-US")}-token ceiling · reasoning off · ${data.updated ? `updated ${data.updated}` : "sota-v2"}`}
            withTiers
          />
        )}
        {publishable && data.models.length > 0 && <MechanicBreakdown models={data.models} />}
        <div style={{ marginTop: 20 }}>
          <BarTable data={data} />
        </div>
        {data.cli_harness_models.length > 0 && (
          <>
            <p className="lane-note" style={{ marginTop: 20 }}>
              Coding-harness rows run the same episodes through a CLI agent's own tool loop, context,
              and retries. That harness is part of what gets measured, so these rows live in their own
              observational table and never mix with the API lane.
            </p>
            <ModelTable
              data={data}
              models={data.cli_harness_models}
              title="Coding-harness lane"
              subtitle="observational · separate table by design"
              withTiers={false}
            />
          </>
        )}
        <div style={{ marginTop: 20 }}>
          <ArchiveNotice />
        </div>
      </div>
    </section>
  );
}
