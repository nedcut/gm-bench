import { useEffect, useRef, useState, type ReactNode } from "react";
import type { Player, Snapshot } from "./types";

import { money, rating, ranked, type Review } from "./gameConfig";

export function Confirm({
  title,
  children,
  onCancel,
  onConfirm,
}: {
  title: string;
  children: ReactNode;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    ref.current?.showModal();
  }, []);
  return (
    <dialog
      ref={ref}
      className="gm-dialog"
      onCancel={onCancel}
      aria-labelledby="gm-confirm-title"
    >
      <h2 id="gm-confirm-title">{title}</h2>
      <div>{children}</div>
      <div className="gm-actions">
        <button autoFocus onClick={onCancel}>
          Cancel
        </button>
        <button className="gm-primary" onClick={onConfirm}>
          Confirm
        </button>
      </div>
    </dialog>
  );
}

export function PlayerTable({
  players,
  reports,
  quotes = false,
  children,
}: {
  players: Player[];
  reports?: Snapshot["scout_reports"];
  quotes?: boolean;
  children?: (p: Player) => ReactNode;
}) {
  return (
    <div
      className="gm-scroll"
      tabIndex={0}
      role="region"
      aria-label="Player table"
    >
      <table className="data-table gm-table">
        <thead>
          <tr>
            <th>Player</th>
            <th>Pos</th>
            <th className="r">Age</th>
            <th className="r">Ovr</th>
            <th className="r">Pot*</th>
            <th className="r">{quotes ? "1-year quote" : "Salary / yrs"}</th>
            {children && <th>Manage</th>}
          </tr>
        </thead>
        <tbody>
          {ranked(players).map((p) => (
            <tr key={p.id}>
              <th scope="row">{p.name}</th>
              <td>{p.sub_position ?? p.position}</td>
              <td className="r">{p.age}</td>
              <td className="r">{rating(p.overall)}</td>
              <td className="r">
                {rating(reports?.[p.id] ?? p.potential)}
                {reports?.[p.id] !== undefined ? " ✓" : ""}
              </td>
              <td className="r">
                {quotes
                  ? money(p.asking_salary ?? p.salary)
                  : `${money(p.salary)} / ${p.contract_years}`}
              </td>
              {children && <td>{children(p)}</td>}
            </tr>
          ))}
        </tbody>
      </table>
      {players.length === 0 && (
        <p className="gm-empty">No players available.</p>
      )}
    </div>
  );
}

export function Contract({
  player,
  quotes,
  tool,
  s,
  review,
}: {
  player: Player;
  quotes: Record<string, number>;
  tool: string;
  s: Snapshot;
  review: Review;
}) {
  const [years, setYears] = useState(Object.keys(quotes)[0]);
  const salary = quotes[years];
  const capDelta = salary - (tool === "extend_contract" ? player.salary : 0);
  return (
    <div className="gm-contract">
      <label>
        Contract length
        <select value={years} onChange={(e) => setYears(e.target.value)}>
          {Object.keys(quotes).map((y) => (
            <option key={y} value={y}>
              {y} years · {money(quotes[y])}/yr
            </option>
          ))}
        </select>
      </label>
      <p>
        Cap room after: <b>{money(s.team.cap_room - capDelta)}</b> · Total
        commitment: {money(salary * Number(years))}
      </p>
      {s.team.cap_room - capDelta < -s.rules.hard_cap_buffer && (
        <p className="neg">
          This contract would exceed the hard cap. Free up salary first.
        </p>
      )}
      <button
        disabled={
          s.done ||
          !s.legal_tools.includes(tool) ||
          Boolean(player.resign_blocked) ||
          s.team.cap_room - capDelta < -s.rules.hard_cap_buffer
        }
        onClick={() =>
          review(
            `${tool === "extend_contract" ? "Extend" : "Sign"} ${player.name}?`,
            <p>
              {years} years at {money(salary)} per year. Cap room changes from{" "}
              {money(s.team.cap_room)} to {money(s.team.cap_room - capDelta)}.
              The simulator checks cap and contract eligibility.
            </p>,
            tool,
            { player_id: player.id, years: Number(years), salary },
          )
        }
      >
        {tool === "extend_contract" ? "Review extension" : "Review signing"}
      </button>
    </div>
  );
}
