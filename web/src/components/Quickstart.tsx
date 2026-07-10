import { useState } from "react";

const REPO = "https://github.com/nedcut/gm-bench";

const BASELINE_CMDS = `# clone — Python 3.11+
git clone ${REPO}.git
cd gm-bench

# calibrate with scripted baselines
python -m gm_bench compare \\
    --agents random conservative win-now rebuild value shrewd strategic pick-trader \\
    --seeds 11 12 13 14 15 16 17 18 --seasons 5`;

const CANDIDATE_CMDS = `# official model run (leaderboard preset)
LLM_API_KEY=... python -m gm_bench model \\
    --provider openai --model gpt-5.4 \\
    --preset leaderboard --repeats 3 --json \\
    > results/leaderboard/openai-gpt-5.4.json

# validate before quoting
python -m gm_bench validate-result \\
    results/leaderboard/openai-gpt-5.4.json --policy sota-v1`;

function CommandCard({ title, code }: { title: string; code: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    await navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 1600);
  };
  return (
    <div className="code-card">
      <div className="code-card-head">
        <span>{title}</span>
        <button type="button" className="copy-btn" onClick={copy}>
          {copied ? "copied ✓" : "copy"}
        </button>
      </div>
      <pre>
        <code>{code}</code>
      </pre>
    </div>
  );
}

export default function Quickstart() {
  return (
    <section className="section" id="quickstart">
      <div className="shell">
        <div className="section-head">
          <p className="section-kicker">Run it</p>
          <h2>Clone, calibrate, then submit an official row.</h2>
          <p>
            Start with the scripted ladder so you know what “good” looks like. Then run the
            leaderboard preset and validate. Schemas live in{" "}
            <a href={`${REPO}/tree/main/schemas`} target="_blank" rel="noreferrer">
              <code>schemas/</code>
            </a>
            ; adapters in{" "}
            <a href={`${REPO}/tree/main/examples`} target="_blank" rel="noreferrer">
              <code>examples/</code>
            </a>
            .
          </p>
        </div>
        <div className="quickstart-grid">
          <CommandCard title="1 · calibrate with baselines" code={BASELINE_CMDS} />
          <CommandCard title="2 · official model run" code={CANDIDATE_CMDS} />
        </div>
        <div className="quickstart-links">
          <a href={`${REPO}/blob/main/docs/production_benchmark.md`} target="_blank" rel="noreferrer">
            Production standard →
          </a>
          <a href={`${REPO}/blob/main/docs/submitting_results.md`} target="_blank" rel="noreferrer">
            Submitting results →
          </a>
          <a href={`${REPO}/blob/main/docs/benchmark_spec.md`} target="_blank" rel="noreferrer">
            Benchmark spec →
          </a>
        </div>
      </div>
    </section>
  );
}
