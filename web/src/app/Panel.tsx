import { useLayoutEffect, useRef, useState } from "react";
import { REPO_BLOB } from "../site";
import {
  HARNESSES,
  compact,
  costText,
  num,
  pText,
  signed,
  type BotRow,
  type Filters,
  type ModelRow,
  type StandingsRow,
} from "../v2";

const BOT_NOTES: Record<string, string> = {
  "pick-trader": "Strategic, plus careful trades for future draft picks. The bar every row is tested against.",
  strategic: "Shrewd, plus scouting, answering trade offers, pick trades and season notes.",
  shrewd: "Value, plus releasing bad contracts and dressing high-upside young players.",
  "win-now": "Signs the highest-rated players it can afford.",
  value: "Signs the free agents with the best value for their salary.",
  rebuild: "Drafts the best prospects and favors youth.",
  conservative: "Few moves; signs cautiously and keeps cap room.",
  random: "Random legal moves. The floor.",
};

function toggle(list: string[], key: string): string[] {
  return list.includes(key) ? list.filter((item) => item !== key) : [...list, key];
}

function FilterView({ models, filters, onFilters, hint }: { models: ModelRow[]; filters: Filters; onFilters: (f: Filters) => void; hint: string }) {
  const harnesses = [...new Set(models.map((m) => m.harnessKey))].sort();
  const vendors = [...new Map(models.map((m) => [m.vendor.key, m.vendor])).values()].sort((a, b) => a.name.localeCompare(b.name));
  const count = (pred: (m: ModelRow) => boolean) => models.filter(pred).length;
  const dirty = filters.hiddenHarnesses.length + filters.hiddenVendors.length > 0 || !filters.showBots;
  return (
    <>
      <div className="panel-head">
        <h2>Filter</h2>
        {dirty && (
          <button type="button" className="text-button" onClick={() => onFilters({ hiddenHarnesses: [], hiddenVendors: [], showBots: true })}>
            Reset
          </button>
        )}
      </div>
      <fieldset>
        <legend>Harness</legend>
        {harnesses.map((key) => (
          <label key={key} className="check">
            <input type="checkbox" checked={!filters.hiddenHarnesses.includes(key)} onChange={() => onFilters({ ...filters, hiddenHarnesses: toggle(filters.hiddenHarnesses, key) })} />
            <span>{HARNESSES[key] ?? key}</span>
            <small>{count((m) => m.harnessKey === key)}</small>
          </label>
        ))}
      </fieldset>
      <fieldset>
        <legend>Vendor</legend>
        {vendors.map((vendor) => (
          <label key={vendor.key} className="check">
            <input type="checkbox" className={`vendor-${vendor.key}`} checked={!filters.hiddenVendors.includes(vendor.key)} onChange={() => onFilters({ ...filters, hiddenVendors: toggle(filters.hiddenVendors, vendor.key) })} />
            <span>{vendor.name}</span>
            <small>{count((m) => m.vendor.key === vendor.key)}</small>
          </label>
        ))}
      </fieldset>
      <fieldset>
        <legend>Scripted bots</legend>
        <label className="check">
          <input type="checkbox" className="is-bot" checked={filters.showBots} onChange={() => onFilters({ ...filters, showBots: !filters.showBots })} />
          <span>Show bots</span>
        </label>
      </fieldset>
      <p className="panel-hint">{hint}</p>
    </>
  );
}

function Stat({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="stat">
      <dt>{label}</dt>
      <dd>
        {value}
        {note && <small>{note}</small>}
      </dd>
    </div>
  );
}

function ModelDetails({ row }: { row: ModelRow }) {
  return (
    <>
      <div className="detail-title">
        <span className={`dot vendor-${row.vendor.key}`} aria-hidden="true" />
        <div>
          <h2>{row.source.model}</h2>
          <p>
            {row.harness} {row.harnessVersion} · {row.vendor.name}
          </p>
        </div>
      </div>
      <dl className="stats">
        <Stat label="Score" value={num(row.score)} note={`± ${num(row.sd)} across seeds`} />
        <Stat
          label="vs pick-trader"
          value={signed(row.lift)}
          note={`${row.liftCi ? `[${signed(row.liftCi[0])}, ${signed(row.liftCi[1])}] · ` : ""}${pText(row)}`}
        />
        <Stat label="Beats pick-trader on" value={`${num(row.seedWinRate * 100, 0)}%`} note="of seeds" />
        <Stat label="Seed range" value={`${num(row.seedRange[0], 0)}–${num(row.seedRange[1], 0)}`} />
        <Stat label="Tool calls / game" value={num(row.toolCalls, 0)} />
        <Stat label="Tokens / game" value={`${compact(row.inputTokens)} in`} note={`${compact(row.outputTokens)} out`} />
        <Stat
          label="Cost / game"
          value={row.cost.kind === "unmeasured" ? "unmeasured" : costText(row.cost)}
          note={row.cost.kind === "estimate" ? `API list price${row.cost.lowerBound ? ", may be low" : ""}` : undefined}
        />
        <Stat label="Minutes / game" value={num(row.minutes)} />
        <Stat label="Empty phases" value={row.emptyPhases === null ? "—" : `${row.emptyPhases} / ${row.phases}`} note="status check, then end" />
        <Stat label="Illegal moves" value={row.illegal === null ? "—" : String(row.illegal)} note={`over ${row.source.panel.episodes} games`} />
      </dl>
      <ul className="detail-notes">
        <li>
          {row.seeds} private seeds, harness in a {row.isolation}.
        </li>
        {row.unpinned && <li>The model version is not pinned, so this row may not reproduce.</li>}
        {row.caveat && <li>{row.caveat}</li>}
      </ul>
      <a className="text-link" href={`${REPO_BLOB}${row.artifact}`}>
        Published result file
      </a>
    </>
  );
}

function BotDetails({ row }: { row: BotRow }) {
  return (
    <>
      <div className="detail-title">
        <span className="dot" aria-hidden="true" />
        <div>
          <h2>{row.label}</h2>
          <p>Scripted bot</p>
        </div>
      </div>
      <dl className="stats">
        <Stat label="Score" value={num(row.score)} />
      </dl>
      <p className="detail-copy">{BOT_NOTES[row.label] ?? "A scripted baseline policy."}</p>
      <a className="text-link" href={`${REPO_BLOB}gm_bench/agents.py`}>
        Source
      </a>
    </>
  );
}

export default function Panel({
  models,
  filters,
  onFilters,
  row,
  onBack,
  open,
  onClose,
  hint,
}: {
  models: ModelRow[];
  filters: Filters;
  onFilters: (f: Filters) => void;
  row: StandingsRow | null;
  onBack: () => void;
  open: boolean;
  onClose: () => void;
  hint: string;
}) {
  const panelRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const [mobile, setMobile] = useState(() => typeof window !== "undefined" && window.matchMedia("(max-width: 900px)").matches);

  useLayoutEffect(() => {
    const query = window.matchMedia("(max-width: 900px)");
    const update = () => setMobile(query.matches);
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  useLayoutEffect(() => {
    const panel = panelRef.current;
    if (!open || !mobile || !panel) return;
    const trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    // Inert each sibling along the ancestor path, leaving the sheet and scrim usable.
    const background: { element: HTMLElement; inert: boolean }[] = [];
    for (let node: HTMLElement | null = panel; node?.parentElement; node = node.parentElement) {
      for (const sibling of node.parentElement.children) {
        if (sibling instanceof HTMLElement && sibling !== node && !sibling.classList.contains("sheet-scrim")) {
          background.push({ element: sibling, inert: sibling.inert });
          sibling.inert = true;
        }
      }
    }
    closeRef.current?.focus();
    const contain = (event: KeyboardEvent) => {
      if (event.key !== "Tab") return;
      const controls = [...panel.querySelectorAll<HTMLElement>('button, a[href], input, select, textarea, [tabindex]')]
        .filter((el) => el.tabIndex >= 0 && !el.matches(":disabled") && el.getClientRects().length > 0);
      const first = controls[0];
      const last = controls.at(-1);
      if (event.shiftKey ? document.activeElement === first : document.activeElement === last) {
        event.preventDefault();
        (event.shiftKey ? last : first)?.focus();
      }
    };
    const keepInside = (event: FocusEvent) => {
      if (!panel.contains(event.target as Node)) closeRef.current?.focus();
    };
    document.addEventListener("keydown", contain);
    document.addEventListener("focusin", keepInside);
    return () => {
      document.removeEventListener("keydown", contain);
      document.removeEventListener("focusin", keepInside);
      for (const { element, inert } of background) element.inert = inert;
      if (trigger?.isConnected && trigger.getClientRects().length) trigger.focus();
      else document.querySelector<HTMLButtonElement>(".sheet-button")?.focus();
    };
  }, [open, mobile]);

  // Returning from details removes the focused back button.
  useLayoutEffect(() => {
    if (open && mobile && !panelRef.current?.contains(document.activeElement)) closeRef.current?.focus();
  }, [row, open, mobile]);

  return (
    <>
      {open && <button type="button" className="sheet-scrim" tabIndex={-1} aria-label="Close panel" onClick={onClose} />}
      <aside ref={panelRef} role={open && mobile ? "dialog" : undefined} aria-modal={open && mobile ? true : undefined} className={`side-panel${open ? " is-open" : ""}`} aria-label={row ? "Row details" : "Filters"}>
        <div className="panel-bar">
          {row ? (
            <button type="button" className="text-button" onClick={onBack}>
              ← Filters
            </button>
          ) : (
            <span />
          )}
          <button type="button" ref={closeRef} className="text-button sheet-close" onClick={onClose}>
            Close
          </button>
        </div>
        {row === null ? (
          <FilterView models={models} filters={filters} onFilters={onFilters} hint={hint} />
        ) : row.kind === "model" ? (
          <ModelDetails row={row} />
        ) : (
          <BotDetails row={row} />
        )}
      </aside>
    </>
  );
}
