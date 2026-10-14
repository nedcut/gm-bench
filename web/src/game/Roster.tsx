import { useState } from "react";
import type { Player, Snapshot } from "./types";
import { money, rating, ranked, type Act, type Review } from "./gameConfig";
import { PlayerTable, Contract } from "./common";

export default function Roster({
  s,
  act,
  review,
}: {
  s: Snapshot;
  act: Act;
  review: Review;
}) {
  const [selected, setSelected] = useState<number | null>(null);
  const [lineup, setLineup] = useState(s.effective_lineup);
  const player = s.team.roster.find((p) => p.id === selected);
  const counts = Object.fromEntries(
    Object.keys(s.rules.lineup_min_positions).map((pos) => [
      pos,
      s.team.roster.filter((p) => lineup.includes(p.id) && p.position === pos)
        .length,
    ]),
  );
  const valid =
    lineup.length === s.rules.lineup_size &&
    Object.entries(s.rules.lineup_min_positions).every(
      ([pos, n]) => counts[pos] >= n,
    );
  return (
    <>
      <h2>Roster & lineup</h2>
      <p>
        Dress {s.rules.lineup_size} players with at least 10 forwards, 4
        defensemen, and 1 goalie. Up to 3 centers add strength. Benched players
        develop at half speed.
      </p>
      <div className="gm-actions">
        <b>
          {lineup.length} / {s.rules.lineup_size} dressed · {counts.F} F /{" "}
          {counts.D} D / {counts.G} G
        </b>
        <button
          disabled={s.done || !valid}
          onClick={() => act("set_lineup", { player_ids: lineup })}
        >
          Save lineup
        </button>
        <button
          disabled={s.done}
          onClick={() => setLineup(autoLineup(s.team.roster, s))}
        >
          Select best by rating
        </button>
      </div>
      <PlayerTable players={s.team.roster} reports={s.scout_reports}>
        {(p) => (
          <div className="gm-actions">
            <label className="gm-check">
              <input
                type="checkbox"
                disabled={s.done}
                checked={lineup.includes(p.id)}
                onChange={(e) =>
                  setLineup((old) =>
                    e.target.checked
                      ? [...old, p.id]
                      : old.filter((id) => id !== p.id),
                  )
                }
                aria-label={`Dress ${p.name}`}
              />{" "}
              Dress
            </label>
            <button onClick={() => setSelected(p.id)}>Manage {p.name}</button>
          </div>
        )}
      </PlayerTable>
      {player && (
        <section className="gm-card">
          <h3>{player.name}</h3>
          <p>
            {player.sub_position ?? player.position} · Age {player.age} ·{" "}
            {rating(player.overall)} overall · {money(player.salary)} /{" "}
            {player.contract_years} years · Injury risk{" "}
            {(player.injury_risk * 100).toFixed(1)}%
          </p>
          {player.extension_quotes && (
            <Contract
              key={player.id}
              player={player}
              quotes={player.extension_quotes}
              tool="extend_contract"
              s={s}
              review={review}
            />
          )}
          <div className="gm-actions">
            <button
              disabled={
                s.done ||
                s.rules.scouting.points_remaining === 0 ||
                s.scout_reports[player.id] !== undefined
              }
              onClick={() => act("scout", { player_id: player.id })}
            >
              Scout potential
            </button>
            <button
              disabled={s.done || s.team.roster.length <= s.rules.roster_min}
              onClick={() =>
                review(
                  `Release ${player.name}?`,
                  <>
                    <p>
                      Lose this player immediately. They cannot re-sign with you
                      this season.
                    </p>
                    <p>
                      Dead cap:{" "}
                      {Object.entries(player.release_dead_cap?.by_season ?? {})
                        .map(([y, charge]) => `Season ${y}: ${money(charge)}`)
                        .join("; ")}
                      . Total: {money(player.release_dead_cap?.total ?? 0)}.
                    </p>
                    <p>
                      Cap room after:{" "}
                      {money(
                        s.team.cap_room +
                          player.salary -
                          (player.release_dead_cap?.by_season[s.season] ?? 0),
                      )}
                      .
                    </p>
                  </>,
                  "release_player",
                  { player_id: player.id },
                )
              }
            >
              Review release
            </button>
          </div>
        </section>
      )}
    </>
  );
}
function autoLineup(players: Player[], s: Snapshot) {
  const selected: number[] = [];
  const sorted = ranked(players);
  for (const [pos, min] of Object.entries(s.rules.lineup_min_positions))
    selected.push(
      ...sorted
        .filter((p) => p.position === pos)
        .slice(0, min)
        .map((p) => p.id),
    );
  selected.push(
    ...sorted
      .filter((p) => !selected.includes(p.id))
      .slice(0, Math.max(0, s.rules.lineup_size - selected.length))
      .map((p) => p.id),
  );
  return selected;
}
