import { useEffect, useState } from "react";
import summary from "../data/best-run-summary.json";
import showcase from "../data/astra-showcase.json";
import { REPO } from "../site";
import TrajectoryExplorer from "./TrajectoryExplorer";
import "../replay-examples.css";

type Example = "public-replay" | "best-run";
const readExample = (): Example => new URLSearchParams(window.location.search).get("example") === "best-run" ? "best-run" : "public-replay";

const highlights = [
  { title: "Rebuild before the first puck drops", story: "Two accepted preseason trades brought in Rafi Grant, Rafi Ivers and Hugo Anders for seven players and the season 2, 3 and 4 picks. Astra made five free-agent signings across preseason and midseason, scouted three prospects and drafted Finn Quill. The team finished seventh and exited in round one." },
  { title: "Consolidate the roster", story: "Astra traded Eli Ivers, Alex Hayes and Cal Lund for Ivan Vale, then Alex Stone, Cal Berg and the season 5 pick for Jules Diaz. Alex Chen returned as a free agent; Jules Price arrived via waivers but left at rollover. The recorded standings improved to fourth, followed by another first-round exit." },
  { title: "Retain the draft pick; win the first title", story: "Finn Quill received a five-year extension at $7.95M per year. Five other players were extended and Nico Mason signed. Two offers for Quin Olsen were rejected as too light; neither changed the roster. The season ended with 26 wins, first place in the recorded standings and the first championship." },
  { title: "Revisit an unsuccessful target", story: "The Quin Olsen trade finally succeeded: Alex Chen plus season 6 and 7 picks went to Austin. Astra also extended Hugo Anders, Jules Diaz and Nico Mason, and claimed Kai Anders from waivers. Kai left at rollover. A second title followed; the evidence does not establish that the trade caused it." },
  { title: "Renew rather than acquire", story: "All fourteen roster transactions were accepted extensions, each for two years. They included Rafi Grant at $8.50M, Milo Olsen at $7.81M and Rafi Ivers at $7.08M per year. There were no trades, signings, draft selections or waiver claims this season. The third consecutive title arrived with $1.84M of cap room at the season-summary snapshot." },
];
const phaseName = (phase: string) => phase.replaceAll("_", " ");

function BestRunSummary() {
  return <section className="best-run shell" aria-labelledby="best-run-title">
    <div className="best-run-heading">
      <div><p className="best-run-kicker">Selected best-case · verified season story</p><h2 id="best-run-title">{summary.model}</h2><p>Codex {summary.harness_version} · {summary.seasons} seasons · private panel</p></div>
      <div className="best-run-score"><strong>{summary.final_score.toFixed(3)}</strong><span>final score (score-v1)</span></div>
    </div>
    <p className="best-run-context">The highest-scoring individual episode among {summary.selection_episodes} episodes in the {summary.selection_rows} published GM-Bench 2.0 agentic panel rows. These rows share the same frozen contract, private panel and five-season horizon.</p>
    <dl className="best-run-outcomes">
      <div><dt>Championships</dt><dd>{summary.championships}</dd></div>
      <div><dt>Published wins counter*</dt><dd>{summary.wins}</dd></div>
      <div><dt>Tool calls</dt><dd>{summary.tool_calls}</dd></div>
      <div><dt>Moves accepted / rejected</dt><dd>{summary.moves_accepted} / {summary.moves_rejected}</dd></div>
    </dl>
    <p className="best-run-counter-note">*The frozen engine retains cumulative win counters at season boundaries and sums those snapshots: 17 + 37 + 63 + 85 + 109 = 311. The season records below are differences between snapshots: 109 actual wins and 56 losses over 165 regular-season games. This explains the published counter; no benchmark score has been changed.</p>
    <div className="best-run-timeline" aria-label="Season-by-season timeline">
      {showcase.seasons.map((season, index) => <article className="best-run-season" key={season.season} aria-labelledby={`astra-season-${season.season}`}>
        <div className="best-run-season-number"><span>Season</span><strong>{season.season}</strong>{season.champion && <span className="best-run-title-badge">Champion</span>}</div>
        <div className="best-run-season-content">
          <h3 id={`astra-season-${season.season}`}>{highlights[index].title}</h3>
          <dl className="best-run-season-stats">
            <div><dt>Season record</dt><dd>{season.wins}–{season.losses}</dd></div>
            <div><dt>Recorded standings</dt><dd>#{season.standing} of 12</dd></div>
            <div><dt>Payroll / cap room</dt><dd>${season.payroll.toFixed(2)}M / ${season.cap_room.toFixed(2)}M</dd></div>
          </dl>
          <p className="best-run-finish">{season.finish}</p>
          <p>{highlights[index].story}</p>
          <details>
            <summary>Season {season.season} supporting detail · {season.moves.filter(move => move.accepted).length} accepted roster moves{season.moves.some(move => !move.accepted) && ` · ${season.moves.filter(move => !move.accepted).length} rejected attempts`}</summary>
            <div className="best-run-season-detail">
              <p><strong>Snapshot evidence.</strong> Recorded cumulative record: {season.recorded_wins}–{season.recorded_losses}. Benchmark score at the season-summary snapshot: {season.score_after_season.toFixed(3)} points. League points and game scores are unavailable. Standings use the engine’s cumulative counters, reconstructed by replay; they are not a separate ranking of this season’s wins.</p>
              <p><strong>Roster and cap.</strong> {season.roster_start} players at season start → {season.roster_end} after rollover. Payroll and cap room above are the retained post-aging/contract-rollover summary, against a ${season.cap.toFixed(2)}M cap. {season.rollover_departures.length ? `Left the roster during rollover: ${season.rollover_departures.join(", ")}.` : "No roster departures at rollover."} These are automatic changes, not agent waiver calls. No agent-initiated waivers were recorded in this episode.</p>
              <p><strong>Lineups.</strong> {season.lineup_calls} accepted lineup calls; complete player ordering is withheld. Lineup calls are included in the published accepted-move count.</p>
              <ol className="best-run-moves">{season.moves.map((move, moveIndex) => <li key={moveIndex}>
                <span className={move.accepted ? "best-run-move-status" : "best-run-move-status rejected"}>{move.accepted ? "Accepted" : "Rejected attempt"} · {phaseName(move.phase)}</span>
                <p>{move.detail}</p>
              </li>)}</ol>
            </div>
          </details>
        </div>
      </article>)}
    </div>
    <div className="best-run-evidence">
      <div><h3>One exceptional episode</h3><p>This is a selected best-case, not a representative mean or evidence that this model is superior overall. Astra’s mean under score-v1, the score this showcase was recorded with, is {summary.panel_mean_score.toFixed(3)} across {summary.panel_episodes} episodes; the standings now use score-v2. The final score here is {summary.strategy_score.toFixed(3)} strategy points minus a {summary.protocol_penalty.toFixed(3)} protocol penalty.</p></div>
      <div><h3>How these highlights were selected</h3><p>We selected the accepted acquisitions, draft selection, largest renewals and a rejected trade target that was later acquired. Supporting detail includes every roster move and rejected attempt, plus lineup counts and rollover departures. Chronology and outcomes come from the retained run and a verified ledger replay; the narrative does not infer Astra’s reasoning or attribute titles to individual moves.</p></div>
      <div><h3>Evidence and disclosure limits</h3><p>The private seed is redacted. This is a sanitized, derived account, not an executable replay: no raw ledger, entity IDs, initial state, full lineups, hidden player attributes, harness text or seed-bearing download is published. Player names and contract terms here are simulated.</p><p>First-round exits are reconstructed from playoff qualification and zero rounds won; opponents, game scores and league points are not retained. Season-summary benchmark points are computed before that summary is appended to scoring history and the calendar advances; they are not the final episode score.</p></div>
      <div><h3>A separate public replay</h3><p>The public Pick Trader replay also spans five seasons, but uses a different, public seed. It is not a matched comparison with this episode. The private episode cannot be loaded into that replay.</p></div>
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
      <button aria-pressed={example === "best-run"} onClick={() => choose("best-run")}><strong>Best-case agent episode · Astra</strong><span>409.132 points · five-season story</span></button>
    </div>
    {example === "public-replay" ? <TrajectoryExplorer /> : <BestRunSummary />}
  </>;
}
