import { useState } from "react";

const BASELINE_CMDS = `# clone and run — Python 3.11+ required
python -m gm_bench run --agent value \\
    --seeds 1 2 3 --seasons 5

# rank every scripted baseline on identical seeds
python -m gm_bench compare \\
    --agents random conservative win-now rebuild value \\
    --seeds 1 2 3 --seasons 5`;

const CANDIDATE_CMDS = `# evaluate your agent against the baseline panel
python -m gm_bench evaluate \\
    --agent-cmd "python my_agent.py" \\
    --baselines random conservative win-now rebuild \\
    --seeds 1 2 3 4 5 --seasons 5

# every run logs to SQLite for later analysis
sqlite3 data/gm_bench.sqlite \\
    'select agent, seed, final_score from episodes
     order by final_score desc;'`;

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
          <p className="kicker">Quickstart</p>
          <h2>From clone to scoreboard in two commands.</h2>
          <p>
            Start with the scripted baselines to calibrate, then plug in your own agent with
            <code> --agent-cmd</code>. JSON Schemas for the observation and action protocol ship in{" "}
            <code>schemas/</code>.
          </p>
        </div>
        <div className="quickstart-grid">
          <CommandCard title="1 · calibrate with baselines" code={BASELINE_CMDS} />
          <CommandCard title="2 · benchmark your agent" code={CANDIDATE_CMDS} />
        </div>
      </div>
    </section>
  );
}
