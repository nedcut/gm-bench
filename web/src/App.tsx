import { useState } from "react";
import snapshotData from "./data/snapshot.json";
import leaderboardData from "./data/leaderboard.json";
import puzzleData from "./data/puzzles.json";
import type { Leaderboard as LeaderboardData, PuzzleSet, Snapshot } from "./types";
import { buildBenchmarkView } from "./benchmarkData";
import Nav from "./components/Nav";
import Puzzles from "./components/Puzzles";
import ResultsExplorer from "./components/ResultsExplorer";
import Analysis from "./components/Analysis";
import HowItWorks from "./components/HowItWorks";
import Quickstart from "./components/Quickstart";
import Footer from "./components/Footer";

const snapshot = snapshotData as Snapshot;
const leaderboard = leaderboardData as LeaderboardData;
const puzzles = puzzleData as PuzzleSet;
const benchmark = buildBenchmarkView(leaderboard);

export default function App() {
  const [selectedModelId, setSelectedModelId] = useState(
    benchmark.models[0]?.id ?? "",
  );

  return (
    <>
      <a className="skip-link" href="#results">
        Skip to results
      </a>
      <Nav />
      <main>
        <Puzzles data={puzzles} />
        <ResultsExplorer
          data={leaderboard}
          benchmark={benchmark}
          selectedModelId={selectedModelId}
          onSelectModel={setSelectedModelId}
        />
        <Analysis
          benchmark={benchmark}
          selectedModelId={selectedModelId}
          onSelectModel={setSelectedModelId}
        />
        <HowItWorks snapshot={snapshot} />
        <Quickstart />
      </main>
      <Footer data={leaderboard} />
    </>
  );
}
