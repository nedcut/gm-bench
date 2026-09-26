import puzzleData from "../data/puzzles.json";
import type { PuzzleSet } from "../types";
import { mountPage } from "../mount";
import PageHeader from "../components/PageHeader";
import ReplayBrowser from "../components/ReplayBrowser";

mountPage(
  "replays",
  <>
    <PageHeader kicker="Inspect a run" title="Watch a GM work.">
      <p>
        One committed episode, every observation it saw and every move it made, plus a verifier
        that replays the file in your browser and checks it lands on the same final state.
      </p>
    </PageHeader>
    <ReplayBrowser puzzles={puzzleData as PuzzleSet} />
  </>,
);
