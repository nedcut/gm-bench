import RinkBoard from "./RinkBoard";

/** A schematic rink, rather than a representation of a recorded game. */
export default function RinkSidebar() {
  return (
    <aside className="rink-sidebar" aria-label="Rink">
      <RinkBoard />
    </aside>
  );
}
