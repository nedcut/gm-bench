import puzzleData from "../data/puzzles.json";
import type { PuzzleSet } from "../types";
import { mountPage } from "../mount";
import PageHeader from "../components/PageHeader";
import ReplayBrowser from "../components/ReplayBrowser";
import TrajectoryExplorer from "../components/TrajectoryExplorer";

mountPage(
  "replays",
  <>
    <PageHeader kicker="Replays" title="Same opening, different futures">
      <p>Two LLM agents and two scripted policies run the same team for five seasons. Pick any two and step through every decision.</p>
    </PageHeader>
    <TrajectoryExplorer />
    <div className="shell"><details className="tx-legacy"><summary>Original conservative replay &amp; browser verifier</summary>
      <ReplayBrowser puzzles={puzzleData as PuzzleSet} />
    </details></div>
  </>,
);
