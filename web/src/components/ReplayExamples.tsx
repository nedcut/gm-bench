import { useEffect, useState } from "react";
import summary from "../data/best-run-summary.json";
import { REPO } from "../site";
import TrajectoryExplorer from "./TrajectoryExplorer";
import "../replay-examples.css";

type Example = "public-replay" | "best-run";
const readExample = (): Example => new URLSearchParams(window.location.search).get("example") === "best-run" ? "best-run" : "public-replay";

function BestRunSummary() {
  return <section className="best-run shell" aria-labelledby="best-run-title">
    <div className="best-run-heading">
      <div><p className="best-run-kicker">Selected best-case · outcome summary</p><h2 id="best-run-title">{summary.model}</h2><p>Codex {summary.harness_version} · {summary.seasons} seasons · private panel</p></div>
      <div className="best-run-score"><strong>{summary.final_score.toFixed(3)}</strong><span>final score</span></div>
    </div>
    <p className="best-run-context">The highest-scoring individual episode among {summary.selection_episodes} episodes in the {summary.selection_rows} published GM-Bench 2.0 agentic panel rows. These rows share the same frozen contract, private panel and five-season horizon.</p>
    <dl className="best-run-outcomes">
      <div><dt>Championships</dt><dd>{summary.championships}</dd></div>
      <div><dt>Season wins, total</dt><dd>{summary.wins}</dd></div>
      <div><dt>Tool calls</dt><dd>{summary.tool_calls}</dd></div>
      <div><dt>Moves accepted / rejected</dt><dd>{summary.moves_accepted} / {summary.moves_rejected}</dd></div>
    </dl>
    <div className="best-run-evidence">
      <div><h3>One exceptional episode</h3><p>This is a selected best-case, not a representative mean or evidence that this model is superior overall. Astra’s published mean is {summary.panel_mean_score.toFixed(3)} across {summary.panel_episodes} episodes. The final score here is {summary.strategy_score.toFixed(3)} strategy points minus a {summary.protocol_penalty.toFixed(3)} protocol penalty.</p></div>
      <div><h3>Summary evidence, no timeline</h3><p>The private seed is redacted. The published compact artifact records outcomes and call counts, without the action ledger or season-by-season championship results. A full replay would require an approved, sanitized ledger and reproducible starting state.</p><p>The public Pick Trader replay also spans five seasons, but uses a different, public seed. It is not a matched comparison with this episode.</p></div>
    </div>
    <p className="best-run-source"><a href={`${REPO}/blob/main/${summary.source}`}>Inspect the published compact source ↗</a><span>Episode index {summary.episode_index} (zero-based artifact index; not a seed)</span></p>
  </section>;
}

export default function ReplayExamples() {
  const [example, setExample] = useState(readExample);
  useEffect(() => {
    const sync = () => setExample(readExample());
    window.addEventListener("popstate", sync);
    return () => window.removeEventListener("popstate", sync);
  }, []);
  function choose(next: Example) {
    const url = new URL(window.location.href);
    if (next === "best-run") url.searchParams.set("example", next);
    else url.searchParams.delete("example");
    window.history.pushState(null, "", url);
    setExample(next);
  }
  return <>
    <div className="replay-examples shell" role="group" aria-label="Example runs">
      <button aria-pressed={example === "public-replay"} onClick={() => choose("public-replay")}><strong>Public replay · Pick Trader & agents</strong><span>Every recorded move · public seed 1</span></button>
      <button aria-pressed={example === "best-run"} onClick={() => choose("best-run")}><strong>Best-case agent episode · Astra</strong><span>409.132 points · verified outcome summary</span></button>
    </div>
    {example === "public-replay" ? <TrajectoryExplorer /> : <BestRunSummary />}
  </>;
}
