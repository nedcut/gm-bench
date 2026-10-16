import { useEffect, useMemo, useState, type ReactNode } from "react";
import type { Leaderboard } from "../types";
import { laneOf, useFilters, visible, type BotRow, type Contract, type Filters, type Lane, type ModelRow } from "../v2";
import Panel from "./Panel";

export interface WorkspaceView {
  /** The contract this page shows: its pick-trader, seeds and fingerprint. */
  lane: Lane;
  models: ModelRow[];
  bots: BotRow[];
  /** Models left after the reader's filters. */
  shown: ModelRow[];
  filters: Filters;
  setFilters: (next: Filters) => void;
  selected: string | null;
  select: (id: string) => void;
  /** The row to emphasize across a view: the hovered one, else the selected one. */
  focus: string | null;
  hover: (id: string | null) => void;
  /** Opens the filter sheet on phones; hidden on wider screens. */
  filterButton: ReactNode;
}

/* All stats sections share filters and selection beside one detail panel.
   A page shows one contract: 2.1 on the site, 2.0 on its archive page. */
export default function Workspace({
  data,
  contract = "2.1",
  hint,
  children,
}: {
  data: Leaderboard;
  contract?: Contract;
  hint: string;
  children: (view: WorkspaceView) => ReactNode;
}) {
  const lane = useMemo(() => laneOf(data, contract), [data, contract]);
  const { models, bots } = lane;
  const [filters, setFilters] = useFilters();
  const [selected, setSelected] = useState<string | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);

  useEffect(() => {
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setSelected(null);
        setSheetOpen(false);
      }
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, []);

  const select = (id: string) => {
    setSelected((current) => (current === id ? null : id));
    setSheetOpen(true);
  };
  const filterButton = (
    <button
      type="button"
      className="sheet-button"
      onClick={(event) => {
        event.currentTarget.focus();
        setSelected(null);
        setSheetOpen(true);
      }}
    >
      Filter
    </button>
  );
  const row = [...models, ...bots].find((item) => item.id === selected) ?? null;

  return (
    <div className="workspace">
      {children({
        lane,
        models,
        bots,
        shown: models.filter((model) => visible(model, filters)),
        filters,
        setFilters,
        selected,
        select,
        focus: hovered ?? selected,
        hover: setHovered,
        filterButton,
      })}
      <Panel
        models={models}
        filters={filters}
        onFilters={setFilters}
        row={row}
        onBack={() => setSelected(null)}
        open={sheetOpen}
        onClose={() => setSheetOpen(false)}
        hint={hint}
      />
    </div>
  );
}
