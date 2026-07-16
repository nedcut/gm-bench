// Semantic chart colors, validated for CVD separation and surface contrast
// (see docs in the dataviz pass): red is reserved site-wide for "the bar to
// beat" (pick-trader / baseline-panel mean), blue for measured candidates,
// steel for recessive reference marks, ink for the oracle ceiling. Identity
// never rides on color alone — every mark sits next to its label.
export const COLOR = {
  red: "#C8102E",
  blue: "#155B9A",
  steel: "#7E93A6",
  ink: "#0C1D2E",
  faint: "#8AA0B2",
  grid: "#D9E4EB",
} as const;

export function agentColor(agent: string): string {
  if (agent === "pick-trader") return COLOR.red;
  if (agent === "oracle") return COLOR.ink;
  if (agent === "value" || agent === "candidate") return COLOR.blue;
  return COLOR.steel;
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
