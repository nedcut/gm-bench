import type { BenchmarkView } from "../../benchmarkData";
import type { Leaderboard } from "../../types";
import { routes } from "../../site";
import PromoVideo from "./PromoVideo";

/* Center-ice markings drawn behind the hero: red line, blue lines, faceoff
   circle and dots. Proportions follow a 200 x 85 ft rink, cropped to the
   neutral zone. */
function RinkLines() {
  return (
    <svg className="lead-rink" viewBox="0 0 1600 900" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
      <rect x="793" y="0" width="14" height="900" className="rink-red" />
      <rect x="573" y="0" width="14" height="900" className="rink-blue" />
      <rect x="1013" y="0" width="14" height="900" className="rink-blue" />
      <circle cx="800" cy="450" r="126" className="rink-circle-blue" />
      <circle cx="800" cy="450" r="6" className="rink-dot-blue" />
      {[
        [632, 265],
        [632, 635],
        [968, 265],
        [968, 635],
      ].map(([cx, cy]) => (
        <circle key={`${cx}-${cy}`} cx={cx} cy={cy} r="8" className="rink-dot-red" />
      ))}
    </svg>
  );
}

export default function Hero({ data, benchmark }: { data: Leaderboard; benchmark: BenchmarkView }) {
  return (
    <section className="lead" aria-labelledby="page-title">
      <RinkLines />
      <div className="shell lead-inner">
        <div className="lead-copy">
          <h1 id="page-title" className="lead-title">
            Can an LLM run a hockey team?
          </h1>
          <p className="lead-lede">
            {data.preset.seasons} seasons of free agency, trades and drafts under a hard salary cap.{" "}
            {benchmark.modelCount + (data.agentic_lane?.length ?? 0)} model runs so far;{" "}
            <strong>{benchmark.modelsAboveBar === 0 ? "none" : benchmark.modelsAboveBar}</strong> beat a short scripted policy.
          </p>
          <div className="lead-actions">
            <a className="cta" href={routes.results}>
              See the results
            </a>
            <a className="cta cta-ghost" href="#play">
              Make a call yourself
            </a>
          </div>
        </div>
        <PromoVideo />
      </div>
    </section>
  );
}
