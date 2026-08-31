import { useEffect, useMemo, useState } from "react";
import type { Puzzle, PuzzleSet, ReplayFixture } from "../types";
import {
  decisionOutcome,
  describeAction,
  loadReplayFixture,
  nameIndex,
  phaseLabel,
  rosterTable,
  seasonRecord,
  teamNameIndex,
  teamRecord,
  transactionHistory,
  transactionLine,
} from "../replayData";
import { fmt } from "../lib";
import PuzzleCard from "./PuzzleCard";
import ReplayVerifier from "./ReplayVerifier";

/* Browse the committed episode.
 *
 * The fixture is fetched rather than imported: it is the same file the Pyodide
 * verifier replays, and it is far too large to belong in the JS bundle. If the
 * fetch fails the rest of the page is unaffected -- this view is an inspection
 * aid, not a dependency of the results. */

const MAX_CONTEXT_CARDS = 2;

/**
 * Anchor puzzle cards to the decision on screen.
 *
 * Exact anchoring (same seed, season and phase) is preferred, but the committed
 * fixture is seed 1 and the puzzle deck was built from other seeds, so in
 * practice the match is by phase. Cards therefore carry their own seed and
 * season in their header and are labelled as coming from another recorded
 * episode when they do.
 */
function contextPuzzles(
  puzzles: Puzzle[],
  seed: number,
  season: number,
  phase: string,
): { cards: Puzzle[]; exact: boolean } {
  const exact = puzzles.filter(
    (puzzle) => puzzle.seed === seed && puzzle.season === season && puzzle.phase === phase,
  );
  if (exact.length > 0) return { cards: exact.slice(0, MAX_CONTEXT_CARDS), exact: true };
  const samePhase = puzzles.filter((puzzle) => puzzle.phase === phase);
  return { cards: samePhase.slice(0, MAX_CONTEXT_CARDS), exact: false };
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

export default function ReplayBrowser({ puzzles }: { puzzles: PuzzleSet }) {
  const [fixture, setFixture] = useState<ReplayFixture | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [decisionIndex, setDecisionIndex] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    loadReplayFixture(controller.signal)
      .then(setFixture)
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        setError(cause instanceof Error ? cause.message : "could not load the replay fixture");
      });
    return () => controller.abort();
  }, []);

  const names = useMemo(() => (fixture ? nameIndex(fixture) : new Map<number, string>()), [fixture]);
  const teams = useMemo(
    () => (fixture ? teamNameIndex(fixture) : new Map<number, string>()),
    [fixture],
  );
  const history = useMemo(() => (fixture ? transactionHistory(fixture) : []), [fixture]);

  const decision = fixture?.decisions[Math.min(decisionIndex, fixture.decisions.length - 1)];
  const rounds = decision?.interaction_rounds ?? [];
  const observation = rounds[0]?.observation;
  const team = observation?.team;
  const roster = rosterTable(observation);
  const outcome = fixture && decision ? decisionOutcome(fixture, decision) : [];
  const context =
    fixture && decision
      ? contextPuzzles(puzzles.puzzles, fixture.seed, decision.season, decision.phase)
      : null;
  const summaries = fixture?.expected.state?.summaries ?? [];
  const finalScore = summaries.at(-1)?.score_after_season;

  return (
    <section className="section replay-section" id="replay" tabIndex={-1}>
      <div className="shell">
        <div className="section-head">
          <p className="kicker">Replays</p>
          <h2>Follow one episode, decision by decision.</h2>
          <p>
            The committed replay fixture is the benchmark's own reproducibility artifact:
            the observation each decision saw, the actions it returned, and the moves the
            league actually recorded. The verifier below replays the same file in the
            browser and checks its final-state digest.
          </p>
        </div>

        <ReplayVerifier />

        {error && (
          <div className="panel">
            <div className="panel-title">
              <h3>Replay browser unavailable</h3>
            </div>
            <p>
              The fixture could not be loaded ({error}). The verifier and the rest of the
              page are unaffected.
            </p>
          </div>
        )}

        {!fixture && !error && (
          <div className="panel">
            <p>Loading the committed episode…</p>
          </div>
        )}

        {fixture && decision && (
          <>
            <div className="panel">
              <div className="panel-title">
                <h3>
                  {teams.get(fixture.user_team_id) ?? `Team ${fixture.user_team_id}`} ·{" "}
                  <code>{fixture.agent}</code>
                </h3>
                <span>
                  seed {fixture.seed} · {fixture.decisions.length} decision points
                </span>
              </div>
              <dl className="replay-stats">
                <Stat label="Seasons recorded" value={String(summaries.length || 1)} />
                <Stat
                  label="Score after final season"
                  value={finalScore === undefined ? "—" : fmt(finalScore, 1)}
                />
                <Stat
                  label="Contract fingerprint"
                  value={fixture.provenance?.contract_fingerprint ?? "—"}
                />
                <Stat label="State digest" value={`${fixture.expected.state_digest.slice(0, 12)}…`} />
              </dl>

              <div className="replay-stepper" role="tablist" aria-label="Decision points">
                {fixture.decisions.map((entry, index) => (
                  <button
                    key={entry.decision_index}
                    type="button"
                    role="tab"
                    aria-selected={index === decisionIndex}
                    className={index === decisionIndex ? "is-active" : ""}
                    onClick={() => setDecisionIndex(index)}
                  >
                    S{entry.season} · {phaseLabel(entry.phase)}
                  </button>
                ))}
              </div>

              <div className="replay-decision">
                <div className="replay-column">
                  <h4>Observation</h4>
                  {team ? (
                    <>
                      <dl className="replay-facts">
                        <Stat label="Record" value={teamRecord(observation)} />
                        <Stat
                          label="Cap room"
                          value={team.cap_room === undefined ? "—" : `$${fmt(team.cap_room, 2)}M`}
                        />
                        <Stat
                          label="Payroll"
                          value={team.payroll === undefined ? "—" : `$${fmt(team.payroll, 2)}M`}
                        />
                        <Stat
                          label="Candidates"
                          value={`${observation?.free_agents?.length ?? 0} FA · ${observation?.draft_class?.length ?? 0} draft · ${observation?.trade_market?.length ?? 0} trade`}
                        />
                        <Stat
                          label="Offers in"
                          value={String(observation?.incoming_offers?.length ?? 0)}
                        />
                      </dl>
                      {roster && (
                        <details className="replay-roster">
                          <summary>Roster as the model saw it ({roster.rows.length})</summary>
                          <div className="replay-roster-scroll">
                            <table>
                              <thead>
                                <tr>
                                  {roster.columns.map((column) => (
                                    <th key={column}>{column}</th>
                                  ))}
                                </tr>
                              </thead>
                              <tbody>
                                {roster.rows.map((row, rowIndex) => (
                                  <tr key={rowIndex}>
                                    {row.map((cell, cellIndex) => (
                                      <td key={cellIndex}>{cell}</td>
                                    ))}
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        </details>
                      )}
                    </>
                  ) : (
                    <p>This decision's observation is not included in the fixture.</p>
                  )}
                  {observation?.memo ? (
                    <p className="replay-memo">
                      <span>memo</span> {observation.memo}
                    </p>
                  ) : (
                    <p className="replay-memo">
                      <span>memo</span> empty
                    </p>
                  )}
                </div>

                <div className="replay-column">
                  <h4>Actions returned</h4>
                  {rounds.map((round) => (
                    <div key={round.round}>
                      {rounds.length > 1 && (
                        <p className="replay-round-label">round {round.round + 1}</p>
                      )}
                      <ul className="replay-actions">
                        {round.actions.map((action, index) => (
                          <li key={`${round.round}-${index}`}>
                            {describeAction(action, names, teams)}
                          </li>
                        ))}
                        {round.actions.length === 0 && <li>No actions returned.</li>}
                      </ul>
                    </div>
                  ))}
                </div>

                <div className="replay-column">
                  <h4>What the league recorded</h4>
                  <ul className="replay-outcome">
                    {outcome.map((txn, index) => (
                      <li
                        key={`${txn.season}-${txn.phase}-${index}`}
                        className={txn.accepted ? undefined : "is-rejected"}
                      >
                        {transactionLine(txn)}
                      </li>
                    ))}
                    {outcome.length === 0 && <li>Nothing changed the roster here.</li>}
                  </ul>
                </div>
              </div>
            </div>

            {context && context.cards.length > 0 && (
              <div className="panel replay-puzzles">
                <div className="panel-title">
                  <h3>Play this situation</h3>
                  <span>
                    {context.exact
                      ? "recorded at this decision point"
                      : "same phase, other recorded episodes"}
                  </span>
                </div>
                <p>
                  Every option below is a move some scripted policy actually made from the
                  same observation, graded by the immediate change in score components.
                  Illustrative content, not a benchmark artifact.
                </p>
                {context.cards.map((puzzle) => (
                  <PuzzleCard key={puzzle.id} puzzle={puzzle} />
                ))}
                <p className="replay-note">{puzzles.note}</p>
              </div>
            )}

            <div className="panel">
              <div className="panel-title">
                <h3>Transaction history</h3>
                <span>
                  {teams.get(fixture.user_team_id) ?? `team ${fixture.user_team_id}`} only ·
                  rejected attempts marked
                </span>
              </div>
              {history.length === 0 ? (
                <p>This episode recorded no transactions for the managed team.</p>
              ) : (
                history.map((season) => {
                  const summary = summaries.find((row) => row.season === season.season);
                  return (
                    <div key={season.season} className="replay-season">
                      <div className="replay-season-head">
                        <h4>Season {season.season}</h4>
                        {summary && (
                          <span>
                            {seasonRecord(summaries, season.season) ?? "—"} ·{" "}
                            {summary.playoff_rounds} playoff round
                            {summary.playoff_rounds === 1 ? "" : "s"}
                            {summary.score_after_season === undefined
                              ? ""
                              : ` · score ${fmt(summary.score_after_season, 1)}`}
                          </span>
                        )}
                      </div>
                      {season.phases.map((phase) => (
                        <div key={phase.phase} className="txn-list">
                          {phase.transactions.map((txn, index) => (
                            <div
                              key={`${phase.phase}-${index}`}
                              className={txn.accepted ? "txn-row" : "txn-row is-rejected"}
                            >
                              <span className="txn-phase">{phaseLabel(txn.phase)}</span>
                              <span className="txn-msg">{transactionLine(txn)}</span>
                              <span className="txn-season">S{txn.season}</span>
                            </div>
                          ))}
                        </div>
                      ))}
                    </div>
                  );
                })
              )}
            </div>
          </>
        )}
      </div>
    </section>
  );
}
