import puzzleData from "./data/puzzles.json";
import type { PuzzleSet } from "./types";
import { buildBenchmarkView } from "./benchmarkData";
import { forwardLegacyHash } from "./site";
import { leaderboard, mountPage } from "./mount";
import Hero from "./components/home/Hero";
import Scoreboard from "./components/home/Scoreboard";
import Season from "./components/home/Season";
import PlayAlong from "./components/home/PlayAlong";
import NextUp from "./components/home/NextUp";
import Quickstart from "./components/Quickstart";

forwardLegacyHash();

const benchmark = buildBenchmarkView(leaderboard);

mountPage(
  "home",
  <>
    <Hero data={leaderboard} benchmark={benchmark} />
    <Scoreboard data={leaderboard} benchmark={benchmark} />
    <Season />
    <PlayAlong set={puzzleData as PuzzleSet} />
    <NextUp data={leaderboard} />
    <Quickstart />
  </>,
);
