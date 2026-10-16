import { useEffect } from "react";
import type { Leaderboard } from "../types";
import Workspace from "./Workspace";
import { StandingsIntro, StandingsSection, V21Section } from "./Standings";
import { CostSection } from "./CostView";
import { ToolsSection } from "./ToolsView";

export default function Stats({ data, start }: { data: Leaderboard; start?: "cost" | "tools" }) {
  useEffect(() => {
    // Wait for font metrics so old URLs and deep links land consistently.
    let cancelled = false;
    const cancel = () => { cancelled = true; };
    window.addEventListener("pointerdown", cancel, { once: true });
    window.addEventListener("keydown", cancel, { once: true });
    window.addEventListener("wheel", cancel, { once: true, passive: true });
    void document.fonts.ready.then(() => {
      const id = window.location.hash.slice(1) || start;
      if (!cancelled && (id === "v21" || id === "standings" || id === "cost" || id === "tools")) {
        document.getElementById(id)?.scrollIntoView();
      }
    });
    return () => {
      cancelled = true;
      window.removeEventListener("pointerdown", cancel);
      window.removeEventListener("keydown", cancel);
      window.removeEventListener("wheel", cancel);
    };
  }, [start]);

  return (
    <>
      <StandingsIntro data={data} />
      <Workspace data={data} hint="Filters apply to all three sections. Select a row, point or bar for its details.">
        {view => (
          <div className="stats-content">
            <nav className="stats-index" aria-label="Statistics sections">
              {view.v21.models.length > 0 && <a href="#v21">2.1</a>}
              <a href="#standings">Standings</a>
              <a href="#cost">Score vs cost</a>
              <a href="#tools">Tool use</a>
              <span className="stats-count">{view.shown.length} of {view.models.length} models</span>
              {view.filterButton}
            </nav>
            <V21Section data={data} view={view} />
            <StandingsSection data={data} view={view} />
            <CostSection data={data} view={view} />
            <ToolsSection data={data} view={view} />
          </div>
        )}
      </Workspace>
    </>
  );
}
