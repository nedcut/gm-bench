import { useMemo } from "react";
import type { BenchmarkView } from "../benchmarkData";
import {
  perSeedScores,
  reliability,
  scoreCi95,
  shortModelName,
  withinSeedStddev,
} from "../benchmarkData";
import { fmt, formatTokensPerDecision, numOrDash, pctOrDash } from "../lib";
import type { Leaderboard as LeaderboardData } from "../types";

/* One published row, opened up.
 *
 * The site's navigation idiom is a hash section driven by the shared model
 * selection, so the profile is a section rather than a route: picking a model
 * in the chart, the table, or the heatmap opens it here. Every v6 field is
 * optional, so each block states plainly when a row does not report something
 * instead of printing a zero that reads like a measurement. */

/* `run_info.seed_panel.name` for a row run on a private seed panel; such a row
 * publishes its panel width and commitment hash but never its seed values. */
const PRIVATE_SEED_PANEL = "private-env";

function Figure({
  label,
  value,
  note,
}: {
  label: string;
  value: string;
  note?: string;
}) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
      {note && <span>{note}</span>}
    </div>
  );
}

/* Notes follow whichever source produced the value on screen: a row that
 * publishes a rate but no count still gets a note describing that rate, and
 * only a row reporting neither reads as "not reported". */
function reliabilityNote(
  value: number | null,
  count: number | null,
  fromCount: (count: string) => string,
  fromRate: string,
): string {
  if (count !== null) return fromCount(count.toLocaleString("en-US"));
  if (value !== null) return fromRate;
  return "not reported by this row";
}

function SeedScores({ scores }: { scores: Array<{ seed: number; score: number }> }) {
  const bounds = useMemo(() => {
    const values = scores.map((row) => row.score);
    const low = Math.min(...values);
    const high = Math.max(...values);
    return { low, span: high - low || 1 };
  }, [scores]);

  return (
    <ol className="seed-scores">
      {scores.map((row) => (
        <li key={row.seed}>
          <span className="seed-label">seed {row.seed}</span>
          <span className="seed-track" aria-hidden="true">
            <i style={{ width: `${((row.score - bounds.low) / bounds.span) * 92 + 8}%` }} />
          </span>
          <span className="seed-value">{fmt(row.score, 1)}</span>
        </li>
      ))}
    </ol>
  );
}

export default function ModelProfile({
  data,
  benchmark,
  selectedModelId,
}: {
  data: LeaderboardData;
  benchmark: BenchmarkView;
  selectedModelId: string;
}) {
  const model =
    benchmark.models.find((row) => row.id === selectedModelId) ?? benchmark.models[0];
  if (!model) return null;

  const interval = scoreCi95(model);
  const withinSeed = withinSeedStddev(model);
  const stats = reliability(model);
  const seedScores = perSeedScores(model);
  // A private-panel row publishes its seed count but not its seed values.
  // Falling back to `data.preset.seeds` would label the *public* preset's
  // panel as this row's, so there is no fallback: the count comes from the
  // row itself, and an absent count reads as an em dash.
  const seeds = model.seeds;
  const seedCount = seeds?.length ?? model.seed_count;
  const seedCountLabel = seedCount === null ? "an unreported number of" : seedCount;

  return (
    <section className="section profile-section" id="profile" tabIndex={-1}>
      <div className="shell">
        <div className="section-head">
          <p className="kicker">Model profile</p>
          <h2>{shortModelName(model.model)}</h2>
          <p>
            <code>{model.model}</code> on {model.provider}, {model.lane ?? "api"} lane. Run
            under {model.benchmark_version ?? "unversioned"} over {seedCountLabel} seeds and{" "}
            {model.seasons ?? data.preset.seasons} seasons.
          </p>
        </div>

        <div className="panel">
          <div className="panel-title">
            <h3>Score and uncertainty</h3>
            <span>higher is better</span>
          </div>
          <dl className="profile-figures">
            <Figure
              label="Mean score"
              value={fmt(model.mean_score, 1)}
              note={
                interval
                  ? `95% across-seed [${fmt(interval[0], 1)}, ${fmt(interval[1], 1)}]`
                  : "interval needs two or more seeds"
              }
            />
            <Figure
              label="Across-seed SD"
              value={numOrDash(model.score_stddev)}
              note="scenario-to-scenario spread"
            />
            <Figure
              label="Within-seed SD"
              value={numOrDash(withinSeed)}
              note={
                withinSeed === null
                  ? "not reported by this row"
                  : "this model's own run-to-run noise"
              }
            />
            <Figure
              label="Paired lift vs pick-trader"
              value={fmt(model.primary_lift, 1)}
              note={`95% [${fmt(model.primary_ci95[0], 1)}, ${fmt(model.primary_ci95[1], 1)}]`}
            />
          </dl>
        </div>

        <div className="panel">
          <div className="panel-title">
            <h3>Per-seed scores</h3>
            <span>
              {model.seed_panel === PRIVATE_SEED_PANEL ? "private panel, " : ""}
              {seedCount === null ? "—" : `${seedCount} seeds`}
            </span>
          </div>
          {seedScores.length > 0 ? (
            <SeedScores scores={seedScores} />
          ) : seeds ? (
            <p>
              This row publishes the seed panel but not its per-seed scores. Seeds run:{" "}
              <code>{seeds.join(", ")}</code>.
            </p>
          ) : (
            <p>
              This row ran a private seed panel, so neither its seed values nor its per-seed
              scores are published.{" "}
              {seedCount === null
                ? "It does not report how wide the panel was."
                : `Only the panel width, ${seedCount} seeds, and the commitment hash below are public.`}
            </p>
          )}
        </div>

        <div className="panel">
          <div className="panel-title">
            <h3>Reliability</h3>
            <span>reported beside the score, never inside it</span>
          </div>
          <dl className="profile-figures">
            <Figure
              label="Malformed"
              value={pctOrDash(stats.malformedRate)}
              note={reliabilityNote(
                stats.malformedRate,
                stats.malformedDecisions,
                (count) =>
                  `${count} of ${model.decision_points.toLocaleString("en-US")} decisions`,
                "share of decisions whose raw output was unusable",
              )}
            />
            <Figure
              label="Unrecoverable"
              value={pctOrDash(stats.unrecoverableRate)}
              note={reliabilityNote(
                stats.unrecoverableRate,
                stats.unrecoverableDecisions,
                (count) => `${count} became structured no-ops`,
                "share of decisions that became structured no-ops",
              )}
            />
            <Figure
              label="Failed decisions"
              value={pctOrDash(stats.failedRate)}
              note={reliabilityNote(
                stats.failedRate,
                stats.failedDecisions,
                (count) =>
                  `${count} of ${model.decision_points.toLocaleString("en-US")} calls never returned a usable turn`,
                "share of calls that never returned a usable turn",
              )}
            />
            <Figure
              label="Illegal actions"
              value={model.illegal_actions.toLocaleString("en-US")}
              note="penalised inside the score"
            />
            <Figure
              label="Failed queries"
              value={numOrDash(model.failed_queries, 0)}
              note="misfired scout and inspect lookups"
            />
          </dl>
        </div>

        <div className="panel">
          <div className="panel-title">
            <h3>Cost</h3>
            <span>as billed on the run</span>
          </div>
          <dl className="profile-figures">
            <Figure
              label="Per episode"
              value={`$${fmt(model.cost_per_episode_usd, 2)}`}
            />
            <Figure
              label="Run total"
              value={model.cost_usd === null ? "—" : `$${fmt(model.cost_usd, 2)}`}
            />
            <Figure label="Tokens / decision" value={formatTokensPerDecision(model)} />
            <Figure
              label="Output cap"
              value={
                model.output_token_cap === null
                  ? "—"
                  : model.output_token_cap.toLocaleString("en-US")
              }
              note="tokens, reasoning included"
            />
          </dl>
        </div>

        <div className="panel">
          <div className="panel-title">
            <h3>Provenance</h3>
            <span>enough to rebuild this row</span>
          </div>
          <dl className="profile-provenance">
            <div>
              <dt>Contract fingerprint</dt>
              <dd className="mono">{model.contract_fingerprint ?? "—"}</dd>
            </div>
            <div>
              <dt>Route</dt>
              <dd className="mono">{model.route ?? `${model.provider}/${model.model}`}</dd>
            </div>
            <div>
              <dt>Seed panel</dt>
              <dd className="mono">
                {model.seed_panel ?? "—"}
                {model.seed_panel_hash ? ` · ${model.seed_panel_hash.slice(0, 12)}…` : ""}
              </dd>
            </div>
            <div>
              <dt>Artifact</dt>
              <dd className="mono">
                {model.artifact_sha256 ? `${model.artifact_sha256.slice(0, 16)}…` : "—"}
              </dd>
            </div>
          </dl>
          {(model.sota_v2_issues ?? []).length > 0 && (
            <ul className="profile-issues">
              {(model.sota_v2_issues ?? []).map((issue) => (
                <li key={issue}>{issue}</li>
              ))}
            </ul>
          )}
          <p className="profile-replay-link">
            <a href="#replay">Open the replay browser</a>. It plays the one committed
            episode for this benchmark. The per-model episode files are named by the hashes
            above and are not published here.
          </p>
        </div>
      </div>
    </section>
  );
}
