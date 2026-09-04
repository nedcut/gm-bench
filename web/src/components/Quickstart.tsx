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
  const [copyStatus, setCopyStatus] = useState<"idle" | "copied" | "failed">("idle");
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopyStatus("copied");
      setTimeout(() => setCopyStatus("idle"), 1600);
    } catch {
      setCopyStatus("failed");
    }
  };
  return (
    <div className="code-card">
      <div className="code-card-head">
        <span>{title}</span>
        <button type="button" className="copy-btn" onClick={copy} aria-label={`Copy ${title} commands`}>
          {copyStatus === "copied" ? "copied" : "copy"}
        </button>
        <span className="sr-only" role="status" aria-live="polite">
          {copyStatus === "copied"
            ? `${title} commands copied to clipboard`
            : copyStatus === "failed"
              ? `Could not copy ${title} commands`
              : ""}
        </span>
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
          <h2>Run the scripted baselines first, then your agent.</h2>
          <p>
            Any subprocess works with <code>--agent-cmd</code>. The observation and action
            schemas are in <code>schemas/</code>.
          </p>
        </div>
        <div className="quickstart-grid">
          <CommandCard title="1. Run the scripted baselines" code={BASELINE_CMDS} />
          <CommandCard title="2. Evaluate your agent" code={CANDIDATE_CMDS} />
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
