import puzzleData from "../data/puzzles.json";
import type { PuzzleSet } from "../types";
import { mountPage } from "../mount";
import TrajectoryExplorer from "../components/TrajectoryExplorer";
import PlayAlong from "../components/home/PlayAlong";
import "../legacy.css";

mountPage(
  "replays",
  <>
    <div className="view replays-head">
      <div className="view-head">
        <h1 id="replays-title">Replays</h1>
        <span>One public seed, two GMs side by side, every move and tool call recorded.</span>
      </div>
    </div>
    <div className="legacy">
      <TrajectoryExplorer />
      <PlayAlong set={puzzleData as PuzzleSet} />
    </div>
  </>,
);
