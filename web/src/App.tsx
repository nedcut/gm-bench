import snapshotData from "./data/snapshot.json";
import leaderboardData from "./data/leaderboard.json";
import type { Leaderboard as LeaderboardData, Snapshot } from "./types";
import Nav from "./components/Nav";
import Hero from "./components/Hero";
import Leaderboard from "./components/Leaderboard";
import Integrity from "./components/Integrity";
import Results from "./components/Results";
import HowItWorks from "./components/HowItWorks";
import Adapters from "./components/Adapters";
import Quickstart from "./components/Quickstart";
import Footer from "./components/Footer";

const snapshot = snapshotData as Snapshot;
const leaderboard = leaderboardData as LeaderboardData;

export default function App() {
  return (
    <>
      <Nav />
      <main>
        <Hero data={leaderboard} />
        <Leaderboard data={leaderboard} />
        <Integrity data={leaderboard} />
        <HowItWorks snapshot={snapshot} />
        <Results snapshot={snapshot} />
        <Adapters />
        <Quickstart />
      </main>
      <Footer data={leaderboard} />
    </>
  );
}
