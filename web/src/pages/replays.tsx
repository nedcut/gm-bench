import puzzleData from "../data/puzzles.json";
import type { PuzzleSet } from "../types";
import { mountPage } from "../mount";
import ReplayExamples from "../components/ReplayExamples";
import PlayAlong from "../components/home/PlayAlong";
import RinkSidebar from "../app/RinkSidebar";
import "../legacy.css";

mountPage(
  "replays",
  <div className="rink-layout">
    <div className="replays-content">
      <header className="replays-head">
        <h1 id="replays-title">Replays</h1>
        <p className="lede">
          Real games from the benchmark, one decision at a time. Make a few front-office calls yourself, then read how the best AI
          game played out or compare an AI and the scripted GM move by move.
        </p>
      </header>
      <div className="legacy">
        <PlayAlong set={puzzleData as PuzzleSet} />
        <section className="replays-games" aria-labelledby="games-title">
          <h2 id="games-title" className="replays-section-title">Watch a real game</h2>
          <ReplayExamples />
        </section>
      </div>
    </div>
    <RinkSidebar />
  </div>,
);
