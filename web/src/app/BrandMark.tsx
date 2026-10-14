/* The same theme-aware mark used in the header and at center ice. */
export default function BrandMark({ className = "brand-mark", x, y, width = 41, height = 22 }: {
  className?: string; x?: number; y?: number; width?: number; height?: number;
}) {
  return (
    <svg className={className} x={x} y={y} viewBox="2 10 256 136" width={width} height={height} aria-hidden="true">
      <path fill="currentColor" d="M116,14 H36 V95 H116 V58 H76 V78 H96 V90 H56 V34 H116 Z" />
      <path fill="currentColor" d="M128,95 V14 H152 L176,50 L200,14 H224 V95 H204 V50 L176,80 L148,50 V95 Z" />
      <path fill="var(--bar)" d="M14,98 H246 V111 H234 V139 H224 V111 H36 V139 H26 V111 H14 Z" />
      <rect fill="var(--rink-blue)" x="6" y="139.5" width="248" height="3" />
    </svg>
  );
}
