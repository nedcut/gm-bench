import { HARNESSES, type Filters } from "../v2";

/* Filters are set on the Standings panel and apply to every tab; say so when some are on. */
export default function FilterNote({ filters, onReset }: { filters: Filters; onReset: () => void }) {
  const hidden = [...filters.hiddenHarnesses.map((key) => HARNESSES[key] ?? key), ...filters.hiddenVendors];
  if (hidden.length === 0) return null;
  return (
    <p className="view-note filter-note">
      Hidden by your filter: {hidden.join(", ")}.{" "}
      <button type="button" className="text-button" onClick={onReset}>
        Show all
      </button>
    </p>
  );
}
