import puzzleData from "../data/puzzles.json";
import type { PuzzleSet } from "../types";
import { mountPage } from "../mount";
import TrajectoryExplorer from "../components/TrajectoryExplorer";
import PlayAlong from "../components/home/PlayAlong";
import "../legacy.css";

mountPage(
  "replays",
  <div className="legacy">
    <TrajectoryExplorer />
    <PlayAlong set={puzzleData as PuzzleSet} />
  </div>,
);
