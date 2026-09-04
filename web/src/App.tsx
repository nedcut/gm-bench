import { useState } from "react";
import snapshotData from "./data/snapshot.json";
import leaderboardData from "./data/leaderboard.json";
import puzzleData from "./data/puzzles.json";
import type { Leaderboard as LeaderboardData, PuzzleSet, Snapshot } from "./types";
import { buildBenchmarkView } from "./benchmarkData";
import Nav from "./components/Nav";
import ShotChart from "./components/ShotChart";
import ResultsExplorer from "./components/ResultsExplorer";
import ModelProfile from "./components/ModelProfile";
import ReplayBrowser from "./components/ReplayBrowser";
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
      <Nav contract={leaderboard.contract?.benchmark_version} />
      <main>
        <section className="homepage-lead" aria-labelledby="page-title">
          <div className="shell rink">
            <div className="rink-copy">
              <h1 id="page-title">
                LLMs ran a hockey franchise. A short script built the dynasties. They did not.
              </h1>
              <p>
                An agent takes over a fictional hockey team for five seasons: free agency,
                waivers, trades, the draft, all under a hard cap. The scoreboard is below, then a
                page for each model, then one recorded episode you can step through.
              </p>
              <div className="rink-actions">
                <a className="btn-primary" href="#results">
                  Read the results
                </a>
                <a
                  className="btn-quiet"
                  href="https://github.com/nedcut/gm-bench/blob/main/docs/REPRODUCING_SOTA_V5_RELEASE.md"
                >
                  Reproduce the release
                </a>
              </div>
            </div>
            <ShotChart
              models={benchmark.models}
              scriptedBar={benchmark.scriptedBar}
              panelMean={benchmark.models[0]?.baseline_panel_mean_score ?? null}
            />
          </div>
        </section>
        <ResultsExplorer
          data={leaderboard}
          benchmark={benchmark}
          selectedModelId={selectedModelId}
          onSelectModel={setSelectedModelId}
        />
        <ModelProfile
          data={leaderboard}
          benchmark={benchmark}
          selectedModelId={selectedModelId}
        />
        <Analysis
          benchmark={benchmark}
          selectedModelId={selectedModelId}
          onSelectModel={setSelectedModelId}
        />
        <ReplayBrowser puzzles={puzzles} />
        <HowItWorks snapshot={snapshot} />
        <Quickstart />
      </main>
      <Footer data={leaderboard} />
    </>
  );
}
