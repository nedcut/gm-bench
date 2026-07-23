import snapshotData from "./data/snapshot.json";
import leaderboardData from "./data/leaderboard.json";
import type { Leaderboard as LeaderboardData, Snapshot } from "./types";
import { buildBenchmarkView } from "./benchmarkData";
import Nav from "./components/Nav";
import ResultsExplorer from "./components/ResultsExplorer";
import Analysis from "./components/Analysis";
import HowItWorks from "./components/HowItWorks";
import Quickstart from "./components/Quickstart";
import Footer from "./components/Footer";

const snapshot = snapshotData as Snapshot;
const leaderboard = leaderboardData as LeaderboardData;
const benchmark = buildBenchmarkView(leaderboard);

export default function App() {
  return (
    <>
      <Nav />
      <main>
        <ResultsExplorer data={leaderboard} benchmark={benchmark} />
        <Analysis benchmark={benchmark} />
        <HowItWorks snapshot={snapshot} />
        <Quickstart />
      </main>
      <Footer data={leaderboard} />
    </>
  );
}
