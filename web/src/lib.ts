export const AGENT_COLORS: Record<string, string> = {
  value: "#34e0a1",
  "win-now": "#8ab4ff",
  conservative: "#ffc46b",
  rebuild: "#c792ea",
  random: "#66779a",
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
