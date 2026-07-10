import leaderboardData from "./data/leaderboard.json";
import type { Leaderboard as LeaderboardData } from "./types";
import Nav from "./components/Nav";
import Hero from "./components/Hero";
import Why from "./components/Why";
import Leaderboard from "./components/Leaderboard";
import HowItWorks from "./components/HowItWorks";
import Adapters from "./components/Adapters";
import Quickstart from "./components/Quickstart";
import Footer from "./components/Footer";

const leaderboard = leaderboardData as LeaderboardData;

export default function App() {
  return (
    <>
      <Nav />
      <main>
        <Hero leaderboard={leaderboard} />
        <Why />
        <Leaderboard data={leaderboard} />
        <HowItWorks />
        <Adapters />
        <Quickstart />
      </main>
      <Footer leaderboard={leaderboard} />
    </>
  );
}
