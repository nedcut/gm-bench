import { useState } from "react";
import { buildBenchmarkView } from "../benchmarkData";
import { fmt } from "../lib";
import { REPO_BLOB } from "../site";
import { leaderboard } from "../mount";
import PageHeader from "./PageHeader";
import ResultsExplorer from "./ResultsExplorer";
import ModelProfile from "./ModelProfile";
import Analysis from "./Analysis";
import DecisionLane from "./DecisionLane";
import AgenticLane from "./AgenticLane";

const benchmark = buildBenchmarkView(leaderboard);

export default function ResultsPage() {
  const [selectedModelId, setSelectedModelId] = useState(benchmark.models[0]?.id ?? "");
  const hasDecisionRows = (leaderboard.decision_lane_models ?? []).length > 0;
  const hasAgenticRows = (leaderboard.agentic_lane ?? []).length > 0;
  const jumps = [
    { href: "#results", label: "Scoreboard" },
    { href: "#profile", label: "Model profile" },
    { href: "#analysis", label: "Analysis" },
    ...(hasDecisionRows ? [{ href: "#decision-lane", label: "Decision lane" }] : []),
    ...(hasAgenticRows ? [{ href: "#agentic-lane", label: "2.0 agentic" }] : []),
  ];

  return (
    <>
      <PageHeader
        kicker={`${leaderboard.contract?.benchmark_version ?? "results"} · updated ${leaderboard.updated}`}
        title={
          <>
            {benchmark.modelsAboveBar} of {benchmark.modelCount} models beat the{" "}
            <span className="accent-red">scripted bar.</span>
          </>
        }
        jumps={jumps}
        wide
      >
        <p>
          Every model ran the same {leaderboard.preset.seed_count ?? "—"} private seeds for{" "}
          {leaderboard.preset.seasons} seasons and was compared with one reference: the{" "}
          <code>pick-trader</code> policy at {fmt(benchmark.scriptedBar, 1)}. Models are listed by
          score for reading; the study compares each one only with that bar, never with each other.
          Read the <a href={`${REPO_BLOB}docs/blog/sota-v5-findings.md`}>findings</a> or{" "}
          <a href={`${REPO_BLOB}docs/REPRODUCING_SOTA_V5_RELEASE.md`}>reproduce the release</a>.
        </p>
      </PageHeader>
      <ResultsExplorer
        data={leaderboard}
        benchmark={benchmark}
        selectedModelId={selectedModelId}
        onSelectModel={setSelectedModelId}
      />
      <ModelProfile data={leaderboard} benchmark={benchmark} selectedModelId={selectedModelId} />
      <Analysis
        benchmark={benchmark}
        selectedModelId={selectedModelId}
        onSelectModel={setSelectedModelId}
      />
      <DecisionLane data={leaderboard} />
      <AgenticLane data={leaderboard} />
    </>
  );
}
