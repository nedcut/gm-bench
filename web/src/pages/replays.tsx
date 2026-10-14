import puzzleData from "../data/puzzles.json";
import type { PuzzleSet } from "../types";
import { mountPage } from "../mount";
import ReplayExamples from "../components/ReplayExamples";
import PlayAlong from "../components/home/PlayAlong";
import "../legacy.css";

mountPage(
  "replays",
  <>
    <div className="view replays-head">
      <div className="view-head">
        <h1 id="replays-title">Replays</h1>
        <span>Explore a public replay or the verified outcomes of a selected best-case agent episode.</span>
      </div>
    </div>
    <div className="legacy">
      <ReplayExamples />
      <PlayAlong set={puzzleData as PuzzleSet} />
    </div>
  </>,
);
