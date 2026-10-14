import { useState } from "react";
import type { Snapshot } from "./types";
import { money, type Act, type Review } from "./gameConfig";
import { PlayerTable, Contract } from "./common";

export default function Market({
  s,
  review,
  act,
  waiver = false,
}: {
  s: Snapshot;
  review: Review;
  act: Act;
  waiver?: boolean;
}) {
  const [position, setPosition] = useState("");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<number | null>(null);
  const all = waiver ? s.waiver_wire : s.free_agents;
  const players = all.filter(
    (p) =>
      (!position || p.position === position) &&
      p.name.toLowerCase().includes(search.toLowerCase()),
  );
  const player = all.find((p) => p.id === selected);
  return (
    <>
      <h2>{waiver ? "Waiver wire" : "Free agency"}</h2>
      <p>
        {waiver
          ? "Claims take on the existing contract. The waiver wire opens at midseason."
          : "Published quotes account for your team's record and the player's role. Choose a length to see the exact cap impact."}
      </p>
      <div className="gm-actions">
        <label>
          Position
          <select
            value={position}
            onChange={(e) => setPosition(e.target.value)}
          >
            <option value="">All positions</option>
            {["F", "D", "G"].map((p) => (
              <option key={p}>{p}</option>
            ))}
          </select>
        </label>
        <label>
          Search players
          <input value={search} onChange={(e) => setSearch(e.target.value)} />
        </label>
        <span>{players.length} players</span>
      </div>
      <PlayerTable
        players={players}
        reports={s.scout_reports}
        quotes={!waiver}
        open={waiver ? null : selected}
        detail={
          player && (
            <section className="gm-card">
              <Contract
                key={`${player.id}-${s.actions_taken}`}
                player={player}
                quotes={
                  player.contract_quotes ?? { "1": player.asking_salary ?? 0 }
                }
                tool="sign_free_agent"
                s={s}
                review={review}
              />
              <button
                disabled={
                  s.done ||
                  s.rules.scouting.points_remaining === 0 ||
                  s.scout_reports[player.id] !== undefined
                }
                onClick={() => act("scout", { player_id: player.id })}
              >
                {s.scout_reports[player.id] !== undefined
                  ? "Scouted ✓"
                  : `Scout potential (${s.rules.scouting.points_remaining} left)`}
              </button>
            </section>
          )
        }
      >
        {(p) =>
          waiver ? (
            <button
              disabled={
                s.done ||
                !s.legal_tools.includes("claim_waiver") ||
                Boolean(p.resign_blocked) ||
                s.team.cap_room - p.salary < -s.rules.hard_cap_buffer
              }
              onClick={() =>
                review(
                  `Claim ${p.name}?`,
                  <p>
                    Take on {money(p.salary)} per year for {p.contract_years}{" "}
                    years. Cap room after: {money(s.team.cap_room - p.salary)}.
                  </p>,
                  "claim_waiver",
                  { player_id: p.id },
                )
              }
            >
              Review claim
            </button>
          ) : (
            <button
              disabled={s.done || Boolean(p.resign_blocked)}
              aria-expanded={selected === p.id}
              onClick={() => setSelected(selected === p.id ? null : p.id)}
            >
              {p.resign_blocked
                ? `Released this season: ${p.name}`
                : `Negotiate ${p.name}`}
            </button>
          )
        }
      </PlayerTable>
    </>
  );
}
