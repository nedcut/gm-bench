import puzzleData from "../data/puzzles.json";
import type { PuzzleSet } from "../types";
import { mountPage } from "../mount";
import PageHeader from "../components/PageHeader";
import ReplayBrowser from "../components/ReplayBrowser";
import TrajectoryExplorer from "../components/TrajectoryExplorer";

mountPage(
  "replays",
  <>
    <PageHeader kicker="Research desk / Experimental public track" title="Same opening. Different futures.">
      <p>
        A testbed for long-horizon planning, tool use and resource allocation, played out in a
        hockey front office. Inspect two real scripted trajectories through five seasons
        of trades, cap pressure and roster decisions. No model performance claim is made.
      </p>
    </PageHeader>
    <TrajectoryExplorer />
    <div className="shell"><details className="tx-legacy"><summary>Original conservative replay &amp; browser verifier</summary>
      <ReplayBrowser puzzles={puzzleData as PuzzleSet} />
    </details></div>
  </>,
);
