const ADAPTERS = [
  {
    name: "Codex CLI",
    body: "Read-only sandbox, ephemeral sessions, structured output against the shared GM action schema.",
    snippet: "examples/codex_agent.py",
  },
  {
    name: "Claude Code",
    body: "Single-shot prompting with no tools and no session persistence, plus an optional per-run budget cap.",
    snippet: "examples/claude_agent.py",
  },
  {
    name: "Ollama",
    body: "Fully local evaluation. Compact observation profiles keep prompts small enough for edge models.",
    snippet: "examples/ollama_agent.py",
  },
  {
    name: "OpenAI-compatible",
    body: "Point LLM_API_BASE at any chat-completions endpoint — OpenAI, or any provider that speaks the same API.",
    snippet: "examples/openai_compatible_agent.py",
  },
  {
    name: "opencode",
    body: "Route through opencode's configured provider and model catalog with a one-line environment switch.",
    snippet: "examples/opencode_agent.py",
  },
  {
    name: "Any process",
    body: "The protocol is just stdin/stdout JSON. If it can be launched as a subprocess, it can play GM.",
    snippet: "--agent-cmd \"…\"",
  },
];

export default function Adapters() {
  return (
    <section className="section" id="adapters">
      <div className="shell">
        <div className="section-head">
          <p className="section-kicker">Bring your own model</p>
          <h2>Adapters for the tools you already run.</h2>
          <p>
            Every adapter speaks the same observation/action schema, so results are comparable
            across providers — from frontier APIs to a laptop-hosted 4B model.
          </p>
        </div>
        <div className="adapter-grid">
          {ADAPTERS.map((adapter) => (
            <article key={adapter.name} className="adapter-card">
              <h4>
                <i />
                {adapter.name}
              </h4>
              <p>{adapter.body}</p>
              <code>{adapter.snippet}</code>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
