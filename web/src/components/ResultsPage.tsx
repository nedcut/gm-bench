import { useState } from "react";
import { buildBenchmarkView } from "../benchmarkData";
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
    { href: "#results", label: "1.0 results" },
    ...(hasAgenticRows ? [{ href: "#agentic-lane", label: "2.0 results" }] : []),
    { href: "#profile", label: "Model profile" },
    { href: "#analysis", label: "Illegal moves" },
    ...(hasDecisionRows ? [{ href: "#decision-lane", label: "Decision lane" }] : []),
  ];

  return (
    <>
      <PageHeader
        kicker={`${leaderboard.contract?.benchmark_version ?? "results"} · updated ${leaderboard.updated}`}
        title={
          <>
            {benchmark.modelsAboveBar === 0 ? "No model beats" : `${benchmark.modelsAboveBar} of ${benchmark.modelCount} models beat`} the scripted bar
          </>
        }
        jumps={jumps}
        wide
      >
        <p>
          Every model is compared with one scripted policy, <code>pick-trader</code>, on the same
          private seeds. <a href={`${REPO_BLOB}docs/blog/sota-v5-findings.md`}>Findings</a> ·{" "}
          <a href={`${REPO_BLOB}docs/REPRODUCING_SOTA_V5_RELEASE.md`}>Reproduce</a>
        </p>
      </PageHeader>
      <ResultsExplorer
        data={leaderboard}
        benchmark={benchmark}
        selectedModelId={selectedModelId}
        onSelectModel={setSelectedModelId}
      />
      <AgenticLane data={leaderboard} />
      <ModelProfile data={leaderboard} benchmark={benchmark} selectedModelId={selectedModelId} />
      <Analysis
        benchmark={benchmark}
        selectedModelId={selectedModelId}
        onSelectModel={setSelectedModelId}
      />
      <DecisionLane data={leaderboard} />
    </>
  );
}
