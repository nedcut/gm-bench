import type { BenchmarkView } from "../../benchmarkData";
import type { Leaderboard } from "../../types";
import { fmt } from "../../lib";
import { routes } from "../../site";
import ShotChart from "../ShotChart";

/* The finding, as an arena scoreboard. Every number is derived from the same
   leaderboard record the results page reads; nothing here is typed by hand. */
export default function Scoreboard({ data, benchmark }: { data: Leaderboard; benchmark: BenchmarkView }) {
  const best = benchmark.models[0]?.mean_score ?? null;
  // Signed: negative while every model is below pick-trader, positive once one clears it.
  const gap = best === null ? null : best - benchmark.scriptedBar;
  const panelMean = benchmark.models[0]?.baseline_panel_mean_score ?? null;

  return (
    <section className="board" aria-labelledby="board-title">
      <div className="shell">
        <div className="board-head">
          <p className="eyebrow">The {data.contract?.benchmark_version ?? "current"} result</p>
          <h2 id="board-title" className="display-2">
            {benchmark.modelCount === 0 ? (
              <>No model results are published yet.</>
            ) : benchmark.modelsAboveBar === 0 ? (
              <>
                The scripted policy is still <span className="accent-red">undefeated.</span>
              </>
            ) : (
              <>
                {benchmark.modelsAboveBar} of {benchmark.modelCount} models beat the{" "}
                <span className="accent-red">scripted policy.</span>
              </>
            )}
          </h2>
        </div>
        <dl className="board-stats">
          <div className="board-stat">
            <dt>models above the scripted bar</dt>
            <dd className="accent-red">
              {benchmark.modelsAboveBar}
              <small>/{benchmark.modelCount}</small>
            </dd>
          </div>
          <div className="board-stat">
            <dt>points between the closest model and pick-trader</dt>
            <dd>{gap === null ? "—" : `${gap < 0 ? "−" : "+"}${fmt(Math.abs(gap), 1)}`}</dd>
          </div>
          <div className="board-stat">
            <dt>significantly below it, Holm-adjusted at 0.05</dt>
            <dd>
              {benchmark.holmRejectedCount}
              <small>/{benchmark.modelCount}</small>
            </dd>
          </div>
        </dl>
        <div className="board-chart">
          {benchmark.models.length > 0 ? (
            <ShotChart models={benchmark.models} scriptedBar={benchmark.scriptedBar} panelMean={panelMean} />
          ) : (
            <p>No model rows are published yet, so there is nothing to plot.</p>
          )}
          <div className="board-aside">
            <p>
              <code>pick-trader</code> is one of the scripted baselines that ship with the
              benchmark. It scored {fmt(benchmark.scriptedBar, 1)} on the same private seeds. The
              study compares each model with that bar and never ranks models against each other.
            </p>
            <a className="link-arrow" href={routes.results}>
              Full scoreboard, model profiles and analysis
            </a>
          </div>
        </div>
      </div>
    </section>
  );
}
