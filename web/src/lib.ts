// Semantic chart colors, validated for CVD separation and surface contrast
// (see docs in the dataviz pass): red is reserved site-wide for "the bar to
// beat" (pick-trader / baseline-panel mean), blue for measured candidates,
// steel for recessive reference marks, ink for the oracle ceiling. Identity
// never rides on color alone — every mark sits next to its label.
export const COLOR = {
  red: "#C8102E",
  blue: "#1A5F8F",
  steel: "#7E93A6",
  ink: "#0A1620",
  faint: "#8AA0B2",
  grid: "#C5D3DE",
} as const;

// Returns CSS variables (not raw hex) so panel bars and chips recolor with the
// active theme. COLOR above stays the canonical reference for the SVG-free spots
// and documents what each variable resolves to in the light register.
export function agentColor(agent: string): string {
  if (agent === "pick-trader") return "var(--red)";
  if (agent === "oracle") return "var(--mark-axis)";
  if (agent === "value" || agent === "candidate") return "var(--blue)";
  return "var(--mark-ref)";
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
