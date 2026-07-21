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

const ADAPTERS = [
  { name: "Codex CLI", snippet: "examples/codex_agent.py" },
  { name: "Claude Code", snippet: "examples/claude_agent.py" },
  { name: "Ollama", snippet: "examples/ollama_agent.py" },
  { name: "OpenAI-compatible", snippet: "examples/openai_compatible_agent.py" },
  { name: "opencode", snippet: "examples/opencode_agent.py" },
  { name: "Any process", snippet: '--agent-cmd "…"' },
];

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
          {copied ? "copied" : "copy"}
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
          <p className="kicker">Run</p>
          <h2>Calibrate on baselines, then plug in an agent.</h2>
          <p>
            Use <code>--agent-cmd</code> for any subprocess. Observation and action schemas ship in{" "}
            <code>schemas/</code>.
          </p>
        </div>
        <div className="quickstart-grid">
          <CommandCard title="1 · baselines" code={BASELINE_CMDS} />
          <CommandCard title="2 · your agent" code={CANDIDATE_CMDS} />
        </div>
        <div className="adapter-line">
          <strong>Compatible with</strong> Codex CLI, Claude Code, Ollama, OpenAI-compatible
          endpoints, opencode, or any stdin/stdout process:
          <div className="adapter-chips">
            {ADAPTERS.map((adapter) => (
              <code key={adapter.name} title={adapter.name}>
                {adapter.snippet}
              </code>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
