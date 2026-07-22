import type { Leaderboard as LeaderboardData } from "../types";
import { fmt } from "../lib";

const COUNT_WORDS: Record<number, string> = {
  1: "One",
  2: "Two",
  3: "Three",
  4: "Four",
  5: "Five",
  6: "Six",
  7: "Seven",
  8: "Eight",
  9: "Nine",
  10: "Ten",
};

function shortName(model: string): string {
  return model.split("/").pop() ?? model;
}

interface Bar {
  name: string;
  score: number;
  kind: "ceiling" | "bar" | "model" | "rest";
}

export default function Hero({ data }: { data: LeaderboardData }) {
  const cap = data.publication.frozen_output_token_cap;
  const fingerprint = data.contract?.contract_fingerprint;
  const modelCount = data.models.length;
  const baselineCount = data.baselines.length;
  const countWord = COUNT_WORDS[modelCount] ?? String(modelCount);

  const oracle = data.headroom.oracle;
  const bar = data.baselines.find((b) => b.agent === "pick-trader")?.mean_score ?? oracle;
  const ranked = [...data.models].sort((a, b) => b.mean_score - a.mean_score);
  const best = ranked[0] ?? null;
  const topModels = ranked.slice(0, 3);
  const rest = ranked.slice(3);
  const restMin = rest.length > 0 ? Math.min(...rest.map((m) => m.mean_score)) : null;

  // Oracle anchors the scale; the red line sits where the scripted bar falls, so
  // every model bar visibly stops short of it — the gap is the whole message.
  const scaleMax = oracle;
  const width = (score: number) => `${(score / scaleMax) * 100}%`;
  const redLineLeft = `${(bar / scaleMax) * 100}%`;

  const underBar = best ? Math.round(bar - best.mean_score) : 0;
  const underOracle = best ? Math.round(oracle - best.mean_score) : 0;

  const bars: Bar[] = [
    { name: "oracle", score: oracle, kind: "ceiling" },
    { name: "pick-trader", score: bar, kind: "bar" },
    ...topModels.map<Bar>((m) => ({ name: shortName(m.model), score: m.mean_score, kind: "model" })),
  ];

  return (
    <section className="hero" id="top">
      <div className="shell hero-grid">
        <div className="hero-copy">
          <p className="hero-brand">
            GM-Bench<span>.</span>
          </p>
          <h1 className="hero-verdict">
            {countWord} model-plus-scaffold systems. <em>None</em> exceeded the scripted bar’s observed mean.
          </h1>
          <p className="hero-sub">
            Under the frozen compact, fresh-spawn/memo-only, native-minimum-reasoning protocol, agents run a
            multi-season franchise against {baselineCount} scripted reference policies. The best model lands {underBar}
            points under the bar and {underOracle} under a partial oracle that sees hidden information.
          </p>
          <p className="hero-caveat">
            Observed means, not an ordinal ranking: all eight rows overlap in one tier and the full-family Holm test
            does not reject at 0.05. Public seeds and committed baselines also permit benchmark-specific adaptation.
          </p>
          <p className="hero-facts">
            <b>{data.preset.seeds.length} seeds</b> × <b>{data.preset.seasons} seasons</b> × 3 repeats
            {cap && (
              <>
                {" "}
                · <b>{cap.toLocaleString("en-US")}-token</b> ceiling
              </>
            )}
            {fingerprint && (
              <>
                {" "}
                · contract <b>{fingerprint.slice(0, 8)}</b>
              </>
            )}
          </p>
        </div>

        <div className="gapchart">
          <div className="gapchart-head">
            <span>mean score — model vs bar vs ceiling</span>
            <span className="gapchart-scale">0 → {Math.round(scaleMax)}</span>
          </div>
          {bars.map((b) => (
            <div className={`gaprow gap-${b.kind}`} key={b.name}>
              <span className="gap-label">{b.name}</span>
              <div className="gap-track">
                <i className="gap-fill" style={{ width: width(b.score) }} />
                {b.kind !== "ceiling" && (
                  <span className="gap-redline" style={{ left: redLineLeft }} />
                )}
              </div>
              <span className="gap-value">{fmt(b.score, 1)}</span>
            </div>
          ))}
          {rest.length > 0 && (
            <div className="gaprow gap-rest">
              <span className="gap-label">+ {rest.length} more models</span>
              <div className="gap-track">
                <i className="gap-fill" style={{ width: restMin === null ? "0%" : width(restMin) }} />
                <span className="gap-redline" style={{ left: redLineLeft }} />
              </div>
              <span className="gap-value">{restMin === null ? "—" : `↓${Math.round(restMin)}`}</span>
            </div>
          )}
          <p className="gapchart-legend">
            <i /> red line = pick-trader {fmt(bar, 1)}, the scripted bar to beat · oracle sees hidden
            information
          </p>
        </div>
      </div>
    </section>
  );
}
