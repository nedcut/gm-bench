import { fmt } from "../lib";

/* One row per entry on a shared score axis: the mean as a dot, its 95%
   interval as a bar, and pick-trader as a red line through every row. Labels
   sit on the row, so nothing needs a hover to be read. */

export interface LadderRow {
  id: string;
  label: string;
  detail?: string;
  score: number;
  ci: [number, number] | null;
}

export default function ScoreLadder({
  rows,
  reference,
  referenceLabel = "pick-trader",
  domain,
  caption,
  selectedId,
  onSelect,
}: {
  rows: LadderRow[];
  reference: number;
  referenceLabel?: string;
  domain?: [number, number];
  caption: string;
  selectedId?: string;
  onSelect?: (id: string) => void;
}) {
  const values = rows.flatMap((r) => [r.score, ...(r.ci ?? [])]).concat(reference);
  const [lo, hi] = domain ?? [Math.floor(Math.min(...values) / 20) * 20 - 20, Math.ceil(Math.max(...values) / 20) * 20 + 20];
  const at = (v: number) => `${((v - lo) / (hi - lo)) * 100}%`;
  const ticks: number[] = [];
  const step = hi - lo > 200 ? 50 : 20;
  for (let t = Math.ceil(lo / step) * step; t <= hi; t += step) ticks.push(t);

  return (
    <figure className="ladder">
      <div className="ladder-grid" role="table" aria-label={caption}>
        <div className="ladder-row ladder-axis" role="row" aria-hidden="true">
          <span />
          <span className="ladder-track">
            {ticks
              .filter((t) => Math.abs(t - reference) > (hi - lo) * 0.08)
              .map((t) => (
                <span key={t} className="ladder-tick" style={{ left: at(t) }}>
                  {t}
                </span>
              ))}
            <span className="ladder-ref-label" style={{ left: at(reference) }}>
              {referenceLabel} {fmt(reference, 1)}
            </span>
          </span>
          <span />
        </div>
        {rows.map((row) => {
          const content = (
            <>
              <span className="ladder-name" role="cell">
                {row.label}
                {row.detail && <small>{row.detail}</small>}
              </span>
              <span className="ladder-track" role="cell" aria-label={row.ci ? `95% interval ${fmt(row.ci[0], 1)} to ${fmt(row.ci[1], 1)}` : undefined}>
                {ticks.map((t) => (
                  <span key={t} className="ladder-gridline" style={{ left: at(t) }} />
                ))}
                <span className="ladder-ref" style={{ left: at(reference) }} />
                {row.ci && <span className="ladder-ci" style={{ left: at(row.ci[0]), width: `calc(${at(row.ci[1])} - ${at(row.ci[0])})` }} />}
                <span className="ladder-dot" style={{ left: at(row.score) }} />
              </span>
              <span className="ladder-score" role="cell">
                {fmt(row.score, 1)}
              </span>
            </>
          );
          return onSelect ? (
            <button
              key={row.id}
              type="button"
              role="row"
              className="ladder-row"
              aria-pressed={row.id === selectedId}
              onClick={() => onSelect(row.id)}
            >
              {content}
            </button>
          ) : (
            <div key={row.id} role="row" className="ladder-row">
              {content}
            </div>
          );
        })}
      </div>
      <figcaption>{caption}</figcaption>
    </figure>
  );
}
