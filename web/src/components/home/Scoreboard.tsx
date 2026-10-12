import type { BenchmarkView } from "../../benchmarkData";
import { scoreCi95, shortModelName } from "../../benchmarkData";
import type { Leaderboard } from "../../types";
import { routes } from "../../site";
import { agenticLadderRows, agenticReference } from "../../agenticRows";
import ScoreLadder from "../ScoreLadder";

/* The finding as two ladders: 1.0 (one prompt per decision) and 2.0 (a model
   in its own agent harness). Each lane has its own seeds and its own
   pick-trader mean, so they share no axis. */
export default function Scoreboard({ data, benchmark }: { data: Leaderboard; benchmark: BenchmarkView }) {
  const agentic = agenticLadderRows(data);
  const agenticBar = agenticReference(data);
  const domain: [number, number] = [60, 300];

  return (
    <section className="board" aria-labelledby="board-title">
      <div className="shell">
        <h2 id="board-title" className="display-2">
          {benchmark.modelsAboveBar === 0
            ? `No model beats pick-trader yet.`
            : `${benchmark.modelsAboveBar} of ${benchmark.modelCount} models beat pick-trader.`}
        </h2>
        <p className="board-lede">
          <code>pick-trader</code> is a short scripted policy that ships with the benchmark. Every
          model is compared with it on the same private seeds; dots are mean five-season scores,
          bars are 95% intervals.
        </p>
        <div className="board-lanes">
          <div>
            <h3>1.0: one prompt per decision</h3>
            <ScoreLadder
              rows={benchmark.models.map((m) => ({
                id: m.id,
                label: shortModelName(m.model),
                score: m.mean_score,
                ci: scoreCi95(m),
              }))}
              reference={benchmark.scriptedBar}
              domain={domain}
              caption={`${benchmark.modelCount} models, ${data.preset.seed_count ?? "—"} private seeds. Listed by score for reading; each model is compared only with pick-trader.`}
            />
          </div>
          {agentic.length > 0 && agenticBar !== null && (
            <div>
              <h3>2.0: the model plays inside its own agent harness</h3>
              <ScoreLadder
                rows={agentic}
                reference={agenticBar}
                domain={domain}
                caption={`${agentic.length} harness and model pairs, 32 private seeds. Not ranked against each other.`}
              />
            </div>
          )}
        </div>
        <a className="link-arrow" href={routes.results}>
          Full results
        </a>
      </div>
    </section>
  );
}
