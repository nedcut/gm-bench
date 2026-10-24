import { useEffect, useState } from "react";
import { describeAction, phaseLabel, seasonRecord } from "../replayData";
import { COMPONENTS, LABELS, agentMetadata, comparisonIssue, isAgent, parseTrajectories, rosterChange, trajectoryUrl } from "../trajectoryData";
import type { Decision, Episode, Observation, Trajectories } from "../trajectoryData";
import { REPO } from "../site";
import "../trajectory.css";

const number = (n: number | undefined, digits = 1) => n === undefined ? "Unavailable" : n.toFixed(digits);
const signed = (n: number) => `${n > 0 ? "+" : ""}${n.toFixed(2)}`;
const label = (e: Episode) => LABELS[e.fixture.agent] ?? e.fixture.agent;
const kindLabel = (e: Episode) => isAgent(e) ? "agent run" : "scripted";
const toolCalls = (e: Episode) => e.fixture.decisions.reduce((n, d) => n + (d.tool_calls?.length ?? 0), 0);
type View = "actions" | "roster" | "observations";
type Selection = { index: number; left: string; right: string; view: View };
function readSelection(): Selection {
  const p = new URLSearchParams(window.location.search);
  const n = Number(p.get("window") ?? 1);
  return { index: Number.isInteger(n) ? Math.max(0, Math.min(19, n - 1)) : 0,
    left: p.get("left") ?? "claude-code-sonnet-5", right: p.get("right") ?? "pick-trader",
    view: p.get("view") === "roster" ? "roster" : p.get("view") === "observations" ? "observations" : "actions" };
}

function JsonEvidence({ title, value }: { title: string; value: unknown }) {
  return <details className="tx-json"><summary>{title}</summary><pre tabIndex={0}>{JSON.stringify(value, null, 2)}</pre></details>;
}

function ToolTrace({ decision }: { decision: Decision }) {
  const calls = decision.tool_calls ?? [];
  return <>
    <p className="tx-note">Every tool call in this window, from the agent's ledger. Phase ended by: {decision.ended_by ?? "unknown"}.</p>
    {calls.length ? <ol className="tx-action-log tx-tool-log">{calls.map(c => <li key={c.seq} className={c.ok ? "" : "tx-rejected"}>
      <span className="tx-action-no">{String(c.seq).padStart(3, "0")}</span>
      <div><span className="tx-verdict">{c.kind} · {c.ok ? "ok" : "refused"}{c.penalized ? " · penalized" : ""}{c.executed ? "" : " · not executed"}</span><h4><code>{c.tool}</code></h4><p>{c.message}</p>
        {Object.keys(c.arguments).length > 0 && <JsonEvidence title="Arguments" value={c.arguments} />}</div>
    </li>)}</ol> : <p className="tx-empty">No tool calls in this window.</p>}
  </>;
}

function ObservationView({ decision, episode }: { decision: Decision; episode: Episode }) {
  return <div className="tx-observations">
    {isAgent(episode) && <ToolTrace decision={decision} />}
    <p className="tx-note">{isAgent(episode)
      ? "League state at phase open, rebuilt from the ledger. The agent never received this object, only the tool replies above."
      : "The full observation this scripted policy received."}</p>
    {decision.interaction_rounds.length === 0 && <p>No interaction rounds recorded.</p>}
    {decision.interaction_rounds.map(round => <div key={round.round}>
      <h4>Round {round.round + 1}</h4>
      {round.observation ? <>
        <p>{round.actions.length} returned actions · observation and available markets included in the raw record.</p>
        <JsonEvidence title="Inspect recorded observation" value={round.observation} />
        <JsonEvidence title="Inspect logged scouting reports" value={round.observation.scout_reports ?? "Unavailable: no scouting reports logged in this observation."} />
      </> : <p>Observation unavailable for this round. No reconstruction is shown.</p>}
    </div>)}
    {!isAgent(episode) && <aside className="tx-note"><strong>Tool retrieval trace: unavailable.</strong> Scripted policies make no tool calls.</aside>}
  </div>;
}

function RosterView({ observation, previous, index }: { observation?: Observation; previous?: Observation; index: number }) {
  const roster = observation?.team?.roster;
  const change = rosterChange(previous, observation);
  return <>
    <p className="tx-note">Roster entering this window. Changes include other teams' moves and the season rollover.</p>
    {index === 0 ? <p className="tx-roster-change">Opening roster · no previous window.</p> : change ? <div className="tx-roster-change">
      <p><strong>In ({change.added.length})</strong> {change.added.map(p => p.name).join(", ") || "No additions"}</p>
      <p><strong>Out ({change.removed.length})</strong> {change.removed.map(p => p.name).join(", ") || "No departures"}</p>
    </div> : <p>Roster change unavailable: both observations are required.</p>}
    {roster ? <div className="tx-table-scroll" tabIndex={0} role="region" aria-label="Recorded roster, scroll horizontally">
      <table className="tx-roster"><caption>{roster.length} players · ratings as observed</caption><thead><tr><th>Player</th><th>Pos</th><th>Age</th><th>OVR</th><th>Salary</th><th>Years</th></tr></thead>
        <tbody>{roster.map(p => <tr key={p.id}><th scope="row">{p.name}<small>#{p.id}</small></th><td>{p.position ?? "—"}</td><td>{p.age ?? "—"}</td><td>{number(p.overall)}</td><td>{p.salary === undefined ? "—" : `$${number(p.salary, 2)}M`}</td><td>{p.contract_years ?? "—"}</td></tr>)}</tbody>
      </table></div> : <p>No roster observation was logged for this window.</p>}
  </>;
}

function ActionsView({ decision, episode }: { decision: Decision; episode: Episode }) {
  const names = new Map<number, string>();
  for (const pool of [episode.fixture.expected.state?.players, episode.fixture.expected.state?.prospects]) {
    for (const [id, player] of Object.entries(pool ?? {})) if (player.name) names.set(Number(id), player.name);
  }
  const teams = new Map(Object.entries(episode.fixture.expected.state?.teams ?? {}).map(([id, team]) => [Number(id), team.name ?? `Team ${id}`]));
  const accepted = decision.results.filter(r => r.accepted).length;
  const rejected = decision.results.length - accepted;
  return <>
    <div className="tx-action-summary"><span>{accepted} accepted</span><span>{rejected} rejected</span><span>{decision.interaction_rounds.length} rounds</span></div>
    <p className="tx-note">{isAgent(episode)
      ? "Simulator action results, in recorded order. Read-only tool calls are listed under Observations & tools."
      : "Simulator action results, in recorded order. Scripted policies make no MCP tool calls."}</p>
    {decision.results.length ? <ol className="tx-action-log">{decision.results.map((r, i) => <li key={i} className={r.accepted ? "" : "tx-rejected"}>
      <span className="tx-action-no">{String(i + 1).padStart(2, "0")}</span>
      <div><span className="tx-verdict">{r.accepted ? "Accepted" : "Rejected"}</span><h4>{describeAction(r.action, names, teams)}</h4><p>{r.message}</p>
        <JsonEvidence title="Action arguments" value={r.action} />
        <JsonEvidence title="Recorded action result" value={r} /></div>
    </li>)}</ol> : <p className="tx-empty">No action results were logged for this window.</p>}
    {rejected === 0 && <p className="tx-note">No rejected action results in this window.</p>}
    <JsonEvidence title="Submitted actions by interaction round" value={decision.interaction_rounds.map(r => ({ round: r.round, actions: r.actions }))} />
  </>;
}

function Lane({ episode, index, view, side }: { episode: Episode; index: number; view: View; side: string }) {
  const d = episode.fixture.decisions[index];
  const observation = d.interaction_rounds[0]?.observation;
  const team = observation?.team;
  const previous = episode.fixture.decisions[index - 1]?.interaction_rounds[0]?.observation;
  const delta = d.delta.cap_room;
  const previousCap = previous?.team?.cap_room;
  const summaries = episode.fixture.expected.state?.summaries ?? [];
  const prior = summaries.filter(s => s.season < d.season).at(-1);
  const wins = team?.wins === undefined ? undefined : team.wins - (prior?.wins ?? 0);
  const losses = team?.losses === undefined ? undefined : team.losses - (prior?.losses ?? 0);
  return <article className={`tx-lane tx-${side}`} aria-label={`${label(episode)} trajectory`}>
    <header><div><span className="tx-policy-tag">{side === "left" ? "A" : "B"} / {isAgent(episode) ? `agent run · ${agentMetadata(episode)?.harness} ${agentMetadata(episode)?.harness_version}` : "scripted demo"}</span><h3>{label(episode)}</h3></div><span className="tx-window-id">{String(index + 1).padStart(2, "0")} / 20</span></header>
    <dl className="tx-metrics">
      <div><dt>Cap room entering</dt><dd>{team?.cap_room === undefined ? "—" : `$${number(team.cap_room, 2)}M`}</dd></div>
      <div><dt>Payroll entering</dt><dd>{team?.payroll === undefined ? "—" : `$${number(team.payroll, 2)}M`}</dd></div>
      <div><dt>Season record so far</dt><dd>{wins === undefined || losses === undefined ? "—" : `${wins}–${losses}`}</dd></div>
    </dl>
    <div className="tx-evidence-note">
      <span>Recorded effect</span>
      <p>{delta === undefined ? "Immediate cap effect unavailable." : delta === 0 ? "This action window leaves cap room unchanged." : `This action window ${delta < 0 ? "uses" : "frees"} $${number(Math.abs(delta), 2)}M of cap room.`}
      {delta !== undefined && team?.cap_room !== undefined && <> About ${number(team.cap_room + delta, 2)}M remains immediately after the window.</>}</p>
      {index > 0 && previousCap !== undefined && team?.cap_room !== undefined && <small>Entering cap vs previous window: {signed(team.cap_room - previousCap)}M, including intervening simulation.</small>}
      <JsonEvidence title="Source: immediate component deltas" value={d.delta} />
    </div>
    {d.delta.future_pick_assets !== undefined && d.delta.future_pick_assets !== 0 && <p className="tx-note"><strong>Pick ledger:</strong> future-pick value {signed(d.delta.future_pick_assets)} ({signed(d.delta.future_pick_assets_contribution)} points).</p>}
    
    <div className="tx-lane-body" key={`${episode.fixture.agent}-${index}-${view}`}>
      {view === "actions" ? <ActionsView decision={d} episode={episode} /> : view === "roster" ? <RosterView observation={observation} previous={previous} index={index} /> : <ObservationView decision={d} episode={episode} />}
    </div>
  </article>;
}

function ScoreComparison({ left, right }: { left: Episode; right: Episode }) {
  return <section className="tx-scores" aria-labelledby="score-heading">
    <div className="tx-section-heading"><div><h2 id="score-heading">Final score by component</h2></div></div>
    <div className="tx-table-scroll" tabIndex={0} role="region" aria-label="Final score decomposition, scroll horizontally"><table className="tx-score-table">
      <caption>Score units · final state after season rollover · public seed 1</caption><thead><tr><th>Component</th><th>{label(left)}</th><th>{label(right)}</th></tr></thead>
      <tbody>{COMPONENTS.map(([key, title]) => <tr key={key}><th scope="row">{title}</th>{[left, right].map(e => {
        const v = e.components[`${key}_contribution`];
        return <td key={e.fixture.agent}><div className="tx-score-cell"><span className="tx-score-bar" style={{ width: `${Math.min(100, Math.abs(v))}%` }} aria-hidden="true" /><span>{number(v, 2)}</span></div></td>;
      })}</tr>)}<tr><th scope="row">Protocol penalty (subtracted)</th><td>{number(left.score.protocol_penalty, 2)}</td><td>{number(right.score.protocol_penalty, 2)}</td></tr></tbody>
      <tfoot><tr><th scope="row">Final score</th><td>{number(left.score.final_score, 2)}</td><td>{number(right.score.final_score, 2)}</td></tr></tfoot>
    </table></div>
    <p className="tx-note">Rounded for display. Season-end scores in the chart are taken before each rollover; the final score after it.</p>
  </section>;
}

function SeasonChart({ left, right, season }: { left: Episode; right: Episode; season: number }) {
  const values = [left, right].flatMap(e => e.fixture.expected.state?.summaries?.map(s => s.score_after_season ?? 0) ?? []);
  const max = Math.max(1, ...values), min = Math.min(0, ...values), span = max - min;
  return <div className="tx-chart"><div><span>Season-end score</span><span>A — {label(left)} <b> / </b> B – – {label(right)}</span></div>
    <svg viewBox="0 0 1000 108" role="img" aria-label="Season-end score trajectories; exact values in the table below">
      {[0, 1, 2].map(i => <line key={i} x1="40" x2="960" y1={18 + i * 35} y2={18 + i * 35} className="tx-gridline" />)}
      <line x1={40 + (season - 1) * 230} x2={40 + (season - 1) * 230} y1="6" y2="100" className="tx-chart-cursor" />
      {[left, right].map((e, lane) => <g key={e.fixture.agent} className={`tx-chart-line tx-chart-${lane}`}>
        <polyline points={(e.fixture.expected.state?.summaries ?? []).map((s, i) => `${40 + i * 230},${88 - ((s.score_after_season ?? 0) - min) / span * 70}`).join(" ")} />
        {(e.fixture.expected.state?.summaries ?? []).map((s, i) => <circle key={s.season} cx={40 + i * 230} cy={88 - ((s.score_after_season ?? 0) - min) / span * 70} r="4" />)}
      </g>)}
    </svg>
    <details><summary>Season scores and records</summary><div className="tx-table-scroll" tabIndex={0} role="region" aria-label="Season results"><table><thead><tr><th>Season</th><th>{label(left)}</th><th>{label(right)}</th></tr></thead><tbody>{[1, 2, 3, 4, 5].map(s => <tr key={s}><th scope="row">{s}</th>{[left, right].map(e => { const summaries = e.fixture.expected.state?.summaries ?? []; return <td key={e.fixture.agent}>{number(summaries.find(r => r.season === s)?.score_after_season, 2)} · {seasonRecord(summaries, s) ?? "record unavailable"} W–L</td>; })}</tr>)}</tbody></table></div></details>
  </div>;
}

export default function TrajectoryExplorer() {
  const [data, setData] = useState<Trajectories | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [selection, setSelection] = useState(readSelection);
  useEffect(() => {
    const controller = new AbortController();
    setError(null); setData(null);
    fetch(trajectoryUrl(), { signal: controller.signal }).then(response => {
      if (!response.ok) throw new Error(`The public export returned HTTP ${response.status}.`);
      return response.json();
    }).then(parseTrajectories).then(value => { if (!controller.signal.aborted) setData(value); }).catch((cause: unknown) => {
      if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Could not read the public export.");
    });
    return () => controller.abort();
  }, [attempt]);
  useEffect(() => {
    const handler = () => setSelection(readSelection());
    window.addEventListener("popstate", handler);
    return () => window.removeEventListener("popstate", handler);
  }, []);
  function choose(patch: Partial<Selection>) {
    const next = { ...selection, ...patch }; setSelection(next);
    const url = new URL(window.location.href);
    url.searchParams.set("window", String(next.index + 1));
    url.searchParams.set("left", next.left); url.searchParams.set("right", next.right); url.searchParams.set("view", next.view);
    window.history.pushState(null, "", url);
  }
  const left = data?.episodes.find(e => e.fixture.agent === selection.left);
  const right = data?.episodes.find(e => e.fixture.agent === selection.right);
  const issue = left && right ? comparisonIssue(left, right) : "The selected recording is unavailable. Choose an available policy on each side.";
  const season = Math.floor(selection.index / 4) + 1;
  return <section className="tx-explorer" id="replay" aria-label="Experimental trajectory explorer"><div className="shell">
    {!data && !error && <div className="tx-state" role="status"><h2>Opening the front-office ledger…</h2><p>Loading four five-season games with full observations.</p></div>}
    {error && <div className="tx-state" role="alert"><h2>The recordings could not be opened.</h2><p>{error}</p><p>No substitute data is displayed.</p><button onClick={() => setAttempt(n => n + 1)}>Retry loading</button><a href={trajectoryUrl()}>Open the source export</a></div>}
    {data && <>
      <div className="tx-scenario"><div><h2>{left?.fixture.decisions[0]?.interaction_rounds[0]?.observation?.team?.name ?? "Public scenario"}</h2><p>Same team, same opening roster and cap, public seed 1.</p></div><dl><div><dt>Horizon</dt><dd>05 <small>seasons</small></dd></div><div><dt>Opening cap room</dt><dd>{left?.fixture.decisions[0]?.interaction_rounds[0]?.observation?.team?.cap_room === undefined ? "—" : `$${number(left.fixture.decisions[0].interaction_rounds[0].observation.team.cap_room, 2)}`}<small>M</small></dd></div><div><dt>Tool calls A / B</dt><dd>{left && right ? `${toolCalls(left)} / ${toolCalls(right)}` : "—"}</dd></div></dl></div>
      <div className="tx-selectors"><label>A / Left policy<select value={selection.left} onChange={e => choose({ left: e.target.value })}>
        {!left && <option value={selection.left}>Unavailable recording</option>}{data.episodes.map(e => <option key={e.fixture.agent} value={e.fixture.agent}>{label(e)} · {kindLabel(e)}</option>)}</select></label>
        <button onClick={() => choose({ left: selection.right, right: selection.left })} aria-label="Swap left and right policies">⇄ <span>Swap</span></button>
        <label>B / Right policy<select value={selection.right} onChange={e => choose({ right: e.target.value })}>
          {!right && <option value={selection.right}>Unavailable recording</option>}{data.episodes.map(e => <option key={e.fixture.agent} value={e.fixture.agent}>{label(e)} · {kindLabel(e)}</option>)}</select></label></div>
      {data.episodes.length < 2 ? <div className="tx-state" role="status"><h2>No comparison available.</h2><p>Two public recordings are required. No private-panel trace is substituted.</p></div> : issue ? <div className="tx-state" role="status"><h2>Comparison paused.</h2><p>{issue}</p></div> : left && right && <>
        <p className="tx-comparability">One seed shows how each player behaves, not who is better: the standings use 32 private seeds.</p>
        <div className="tx-reading-path" role="group" aria-label="Suggested evidence checkpoints"><span>Jump to</span><button onClick={() => choose({ index: 0, view: "actions" })}>01 · Opening preseason</button><button onClick={() => choose({ index: 2, view: "actions" })}>02 · First trade deadline</button><button onClick={() => choose({ index: 19, view: "roster" })}>03 · Five seasons later</button></div>
        <nav className="tx-timeline" aria-label="Five-season timeline"><div className="tx-season-buttons">{[1, 2, 3, 4, 5].map(s => <button key={s} aria-pressed={s === season} onClick={() => choose({ index: (s - 1) * 4 + selection.index % 4 })}><span>Season</span><strong>0{s}</strong></button>)}</div>
          <SeasonChart left={left} right={right} season={season} />
          <div className="tx-phase-buttons" role="group" aria-label="Decision phase">{["preseason", "midseason", "trade_deadline", "draft"].map((p, i) => <button key={p} aria-pressed={selection.index % 4 === i} onClick={() => choose({ index: (season - 1) * 4 + i })}>{phaseLabel(p)}</button>)}</div>
        </nav>
        <div className="tx-decision-heading"><div><h2>Season {season}, {phaseLabel(left.fixture.decisions[selection.index].phase)}</h2></div><div className="tx-prev-next"><button disabled={selection.index === 0} onClick={() => choose({ index: selection.index - 1 })} aria-label="Previous decision">← Previous</button><span aria-live="polite" aria-atomic="true">Window {selection.index + 1} of 20</span><button disabled={selection.index === 19} onClick={() => choose({ index: selection.index + 1 })} aria-label="Next decision">Next →</button></div></div>
        <div className="tx-views" role="group" aria-label="Evidence view">{([["actions", "Actions & outcomes"], ["roster", "Roster & changes"], ["observations", "Observations & tools"]] as const).map(([view, title]) => <button key={view} aria-pressed={selection.view === view} onClick={() => choose({ view })}>{title}</button>)}</div>
        <div className="tx-lanes"><Lane episode={left} index={selection.index} view={selection.view} side="left" /><Lane episode={right} index={selection.index} view={selection.view} side="right" /></div>
        <ScoreComparison left={left} right={right} />
      </>}
      <details className="tx-provenance-toggle"><summary>Where these recordings come from, and how to check them</summary><section className="tx-provenance" aria-label="Where these recordings come from"><div><p>The agent runs are seed 1 of the committed Claude Code and Codex smoke rows. The export replays each ledger through the frozen engine and must reproduce every tool reply and the published score. The scripted runs replay to their recorded final states. Model reasoning is not included.</p></div><div className="tx-source-ledger"><h3>Reproduction ledger</h3><dl><dt>Track</dt><dd>{data.track}</dd><dt>Engine / recorder checkout</dt><dd><a href={`${REPO}/tree/${data.source_commit}`}>{data.source_commit.slice(0, 12)}</a></dd><dt>Starting-state SHA-256</dt><dd><code>{data.starting_state_digest}</code></dd>{data.episodes.map(e => <div key={e.fixture.agent}><dt>{label(e)} · final-state SHA-256</dt><dd><code>{e.fixture.expected.state_digest}</code></dd><dt>Contract fingerprint</dt><dd><code>{e.fixture.provenance?.contract_fingerprint}</code></dd>{agentMetadata(e) && <><dt>Agent ledger SHA-256</dt><dd><a href={`${REPO}/blob/main/${agentMetadata(e)!.ledger}`}><code>{agentMetadata(e)!.ledger_sha256}</code></a></dd><dt>Source row</dt><dd><a href={`${REPO}/blob/main/${agentMetadata(e)!.source_row}`}>{agentMetadata(e)!.source_row.split("/").at(-1)}</a></dd></>}</div>)}</dl><a href={trajectoryUrl()} download>Download all public recordings (JSON) ↓</a><a href={`${REPO}/blob/${data.source_commit}/gm_bench/scoring.py`}>Inspect the scoring function ↗</a><p className="tx-note">The download includes full observations, action arguments, results and score components. The browser validates structure and comparability; the Python export check re-simulates every episode.</p></div></section></details>
    </>}
  </div></section>;
}
