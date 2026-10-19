import puzzleData from "../data/puzzles.json";
import type { PuzzleSet } from "../types";
import { mountPage } from "../mount";
import ReplayExamples from "../components/ReplayExamples";
import PlayAlong from "../components/home/PlayAlong";
import RinkSidebar from "../app/RinkSidebar";
import "../legacy.css";

mountPage(
  "replays",
  <div className="rink-layout">
    <div className="replays-content">
      <div className="view replays-head">
        <div className="view-head">
          <h1 id="replays-title">Replays</h1>
          <span>Two GMs side by side on public seed 1, move by move, and gpt-6-astra's best-case episode.</span>
        </div>
      </div>
      <div className="legacy">
        <ReplayExamples />
        <PlayAlong set={puzzleData as PuzzleSet} />
      </div>
    </div>
    <RinkSidebar />
  </div>,
);
