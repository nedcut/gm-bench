import { useState } from "react";
import type { Snapshot } from "./types";
import {
  PHASES,
  LABEL,
  NOTE,
  SCORE_LABEL,
  money,
  rating,
  type Act,
  type Review,
} from "./gameConfig";
import { PlayerTable } from "./common";

export function Draft({
  s,
  act,
  review,
}: {
  s: Snapshot;
  act: Act;
  review: Review;
}) {
  const count = s.team.draft_picks[s.season] ?? 0;
  return (
    <>
      <h2>Draft room</h2>
      <p>
        {s.phase === "draft" && !s.done
          ? `You have ${count} pick${count === 1 ? "" : "s"} remaining this season. Rivals ahead of your first pick have already selected.`
          : "The draft board opens in the draft phase. Scouting points can also be spent on your roster and free agents."}
      </p>
      <p>
        <b>{s.rules.scouting.points_remaining} scouting points left.</b>{" "}
        Potential is an estimate. A scouting report gives a closer reading and
        persists across seasons.
      </p>
      <PlayerTable players={s.draft_class} reports={s.scout_reports}>
        {(p) => (
          <div className="gm-actions">
            <button
              disabled={
                s.done ||
                s.rules.scouting.points_remaining === 0 ||
                s.scout_reports[p.id] !== undefined
              }
              onClick={() => act("scout", { player_id: p.id })}
            >
              Scout {p.name}
            </button>
            <button
              disabled={
                s.done || count === 0 || !s.legal_tools.includes("draft")
              }
              onClick={() =>
                review(
                  `Draft ${p.name}?`,
                  <p>
                    Use one season-{s.season} pick on {p.name},{" "}
                    {p.sub_position ?? p.position}, age {p.age},{" "}
                    {rating(p.overall)} overall /{" "}
                    {rating(s.scout_reports[p.id] ?? p.potential)} potential.
                    The simulator assigns a rookie contract.
                  </p>,
                  "draft",
                  { prospect_id: p.id },
                )
              }
            >
              Draft {p.name}
            </button>
          </div>
        )}
      </PlayerTable>
      <h3>Your picks</h3>
      <div className="gm-scroll">
        <table className="data-table gm-table">
          <thead>
            <tr>
              <th>Season</th>
              <th>Original team</th>
              <th>Projected slot</th>
            </tr>
          </thead>
          <tbody>
            {s.team.picks?.map((p, i) => (
              <tr key={i}>
                <td>{p.season}</td>
                <td>{p.from_team_name}</td>
                <td>{p.projected_slot}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted">
        Future slots are projections. The four non-playoff teams enter a
        weighted lottery; picks keep the original team's slot when traded.
      </p>
    </>
  );
}

export function League({ s }: { s: Snapshot }) {
  const [selected, setSelected] = useState<number | null>(null);
  const team = s.teams.find((t) => t.id === selected);
  const played = s.standings.some((t) => t.wins + t.losses > 0);
  return (
    <>
      <h2>League standings</h2>
      <p>
        12 teams. The top 8 make the playoffs.{" "}
        {played
          ? "Records are for the current or most recently completed season."
          : "No games played yet; teams are tied."}
      </p>
      <div className="gm-scroll">
        <table className="data-table gm-table">
          <thead>
            <tr>
              <th>Rank</th>
              <th>Team</th>
              <th className="r">W</th>
              <th className="r">L</th>
              <th className="r">Strength</th>
              <th className="r">Titles</th>
            </tr>
          </thead>
          <tbody>
            {s.standings.map((t, i) => (
              <tr
                key={t.team_id}
                className={t.team_id === s.team.id ? "gm-you" : undefined}
              >
                <td>{played ? i + 1 : "—"}</td>
                <th scope="row">
                  <button
                    className="gm-link"
                    onClick={() => setSelected(t.team_id)}
                  >
                    {t.team_name}
                    {t.team_id === s.team.id ? " · You" : ""}
                  </button>
                </th>
                <td className="r">{t.wins}</td>
                <td className="r">{t.losses}</td>
                <td className="r">{rating(t.public_strength)}</td>
                <td className="r">{t.championships}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {team && (
        <section className="gm-card">
          <h3>{team.name}</h3>
          <p>
            Payroll: {money(team.payroll)} · Cap room: {money(team.cap_room)}
          </p>
          <PlayerTable players={team.roster} />
        </section>
      )}
    </>
  );
}
export function HistoryView({ s }: { s: Snapshot }) {
  return (
    <>
      <h2>Season history</h2>
      {s.history.length === 0 ? (
        <p>Finish your first season to see the results here.</p>
      ) : (
        <div className="gm-scroll">
          <table className="data-table gm-table">
            <thead>
              <tr>
                <th>Season</th>
                <th>Record</th>
                <th>Playoff rounds won</th>
                <th>Champion</th>
                <th>Score</th>
              </tr>
            </thead>
            <tbody>
              {s.history.map((h) => (
                <tr key={h.season}>
                  <th scope="row">{h.season}</th>
                  <td>
                    {h.wins}–{h.losses}
                  </td>
                  <td>{h.playoff_rounds}</td>
                  <td>
                    {s.teams.find((t) => t.id === h.champion_team_id)?.name}
                  </td>
                  <td>{rating(h.score_after_season)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <h3>Score breakdown</h3>
      <p>
        Provisional during play; final after five seasons. Contributions add up
        to the strategy score, then illegal-action penalties are subtracted.
      </p>
      <dl className="gm-score-terms">
        {Object.entries(s.score_terms).map(([key, value]) => (
          <div key={key}>
            <dt>{SCORE_LABEL[key] ?? key.replaceAll("_", " ")}</dt>
            <dd>{rating(value)}</dd>
          </div>
        ))}
        <div>
          <dt>Penalties</dt>
          <dd>−{rating(s.score.protocol_penalty)}</dd>
        </div>
        <div>
          <dt>{s.done ? "Final score" : "Score so far"}</dt>
          <dd>{rating(s.score.final_score)}</dd>
        </div>
      </dl>
      <h3>Recent league transactions</h3>
      <p className="muted">
        Current and previous season. Your complete action history is included in
        your exported save.
      </p>
      <ol className="gm-transactions">
        {[...s.recent_transactions].reverse().map((t, i) => (
          <li key={i}>
            <small>
              Season {t.season} · {LABEL[t.phase] ?? t.phase} ·{" "}
              {s.teams.find((team) => team.id === t.team_id)?.name}
            </small>
            {t.message}{" "}
            <span className="muted">({String(t.action.type ?? "move")})</span>
          </li>
        ))}
      </ol>
    </>
  );
}
export function Rules({ s }: { s: Snapshot }) {
  return (
    <>
      <h2>How to play</h2>
      <p>
        Run the Anchorage Auroras for five seasons. Make as many moves as you
        need in each of four decision windows, then advance. Opponents run
        automatically. The game uses the benchmark simulator and scoring rules.
      </p>
      <h3>Your score</h3>
      <p>
        Wins, playoff rounds, titles, roster assets, young talent, future picks,
        cap room, lineup strength, and depth all contribute. Illegal moves cost
        points; a rival declining a reasonable offer does not. The score shown
        during play is provisional. This is a public practice challenge,
        separate from the private-seed model leaderboard.
      </p>
      <h3>Roster & money</h3>
      <p>
        Salary cap: {money(s.rules.salary_cap)}. Hard-cap buffer:{" "}
        {money(s.rules.hard_cap_buffer)}. Minimum roster: {s.rules.roster_min}.
        Dress {s.rules.lineup_size} players, including at least 10 F, 4 D, and 1
        G. Three dressed centers maximize the center bonus. Players outside the
        lineup develop at half speed.
      </p>
      <p>
        Releasing a player leaves 25% of salary as dead cap for up to two
        seasons, and blocks re-signing them this season. Preseason extensions
        are available only for eligible players in the last year of a contract.
        Quotes are annual salaries in millions. The cap and market inflate 4%
        each season.
      </p>
      <h3>The calendar</h3>
      <ol>
        {PHASES.map((p) => (
          <li key={p}>
            <b>{LABEL[p]}.</b> {NOTE[p]}
          </li>
        ))}
      </ol>
      <p>
        The benchmark draft happens before the remaining games and playoffs.
        There is no daily schedule or box-score simulation. Standings retain the
        last completed record into preseason until the next midseason games run.
      </p>
      <h3>Scouting & trading</h3>
      <p>
        You have 3 scouting points each season. Potential ratings are estimates,
        including on your own roster; ✓ marks a scouted estimate. Picks up to 3
        seasons ahead can be traded. Other GMs use hidden valuations. After
        repeated declines they may stop negotiating until the next phase.
      </p>
      <h3>Saves</h3>
      <p>
        One challenge autosaves in this browser after every action. Export a
        file to back it up or move it to another browser. Saves replay your
        decisions and require the same simulator version. The first launch
        downloads Python from jsDelivr; there are no model calls or provider
        accounts.
      </p>
    </>
  );
}
