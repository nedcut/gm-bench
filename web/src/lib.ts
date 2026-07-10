export const AGENT_COLORS: Record<string, string> = {
  value: "#34e0a1",
  "win-now": "#8ab4ff",
  conservative: "#ffc46b",
  rebuild: "#c792ea",
  random: "#66779a",
  // model providers on the leaderboard
  openai: "#7de3ff",
  claude: "#f2a37b",
  codex: "#b8ff7d",
  ollama: "#e08ad4",
  opencode: "#9fd0ff",
  cursor: "#7de3ff",
  shrewd: "#7de3ff",
  strategic: "#b8ff7d",
  "pick-trader": "#34e0a1",
};

export function agentColor(agent: string): string {
  return AGENT_COLORS[agent] ?? "#9fb0cc";
}

export function fmt(value: number, digits = 1): string {
  return value.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function pct(value: number, digits = 0): string {
  return `${fmt(value * 100, digits)}%`;
}
