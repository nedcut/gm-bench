import { buildBenchmarkView, shortModelName } from "../benchmarkData";
import type { Leaderboard } from "../types";
import { REPO_BLOB, routes } from "../site";
import { num, signed, vendorOf } from "../v2";

/* GM-Bench 1.0 (sota-v5), kept for the record: one prompt per decision. */
export default function V1Archive({ data }: { data: Leaderboard }) {
  const benchmark = buildBenchmarkView(data);
  const bar = benchmark.scriptedBar;
  const rows = [
    ...benchmark.models.map((m) => ({ id: m.id, label: shortModelName(m.model), score: m.mean_score, lift: m.primary_lift as number | null, cost: m.cost_per_episode_usd as number | null, vendor: vendorOf(m.model).key, bot: false })),
    ...data.baselines.map((b) => ({ id: `bot:${b.agent}`, label: b.agent, score: b.mean_score, lift: null, cost: null, vendor: "", bot: true })),
  ].sort((a, b) => b.score - a.score);
  const max = Math.ceil(Math.max(...rows.map((r) => r.score)) / 50) * 50;
  const at = (v: number) => `${(v / max) * 100}%`;
  return (
    <article className="page page-wide">
      <h1>GM-Bench 1.0 archive</h1>
      <p className="lede">
        Superseded by <a href={routes.standings}>GM-Bench 2.0</a>. In 1.0 a model answered one prompt per decision instead
        of playing inside an agent harness. {benchmark.modelCount} models, {data.preset.seed_count ?? "—"} private seeds,
        five seasons ({data.contract?.benchmark_version}).
      </p>
      <table className="standings v1-table">
        <thead>
          <tr>
            <th scope="col">Player</th>
            <th scope="col" className="col-bar"><span className="sr-only">Score bar</span></th>
            <th scope="col" className="r">Score</th>
            <th scope="col" className="r">vs pick-trader</th>
            <th scope="col" className="r hide-sm">$ / game</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id} className={row.bot ? (row.label === "pick-trader" ? "is-bar" : "is-bot") : undefined}>
              <th scope="row">
                <span className="row-name">
                  <span className={`dot ${row.bot ? "" : `vendor-${row.vendor}`}`} aria-hidden="true" />
                  <span className="name">{row.label}</span>
                </span>
              </th>
              <td className="col-bar">
                <span className="meter" aria-hidden="true">
                  <i className={row.bot ? undefined : `vendor-${row.vendor}`} style={{ width: at(row.score) }} />
                  <s style={{ left: at(bar) }} />
                </span>
              </td>
              <td className="r score">{num(row.score)}</td>
              <td className="r lift">{row.lift === null ? "" : <span className="neg">{signed(row.lift)}</span>}</td>
              <td className="r hide-sm">{row.cost === null ? "" : `$${num(row.cost, 2)}`}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="view-note">
        Holm-adjusted test against pick-trader rejects for {benchmark.holmRejectedCount} of {benchmark.modelCount} models at
        0.05. <a href={`${REPO_BLOB}docs/blog/sota-v5-findings.md`}>Findings</a> ·{" "}
        <a href={`${REPO_BLOB}docs/REPRODUCING_SOTA_V5_RELEASE.md`}>Reproduce</a> ·{" "}
        <a href="https://github.com/nedcut/gm-bench/releases/tag/sota-v5-publication-2026-09-03">Release</a>
      </p>
    </article>
  );
}
