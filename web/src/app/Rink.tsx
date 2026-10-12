/* Center-ice markings: the red line, both blue lines, the faceoff circle and
   the four neutral-zone dots, at the proportions of a 200 x 85 ft rink. */
export default function Rink() {
  return (
    <svg className="rink" viewBox="0 0 1600 600" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
      <rect x="1093" y="0" width="12" height="600" className="rink-red" />
      <rect x="873" y="0" width="12" height="600" className="rink-blue" />
      <rect x="1313" y="0" width="12" height="600" className="rink-blue" />
      <circle cx="1099" cy="300" r="120" className="rink-circle" />
      <circle cx="1099" cy="300" r="6" className="rink-blue" />
      {[
        [932, 130],
        [932, 470],
        [1266, 130],
        [1266, 470],
      ].map(([cx, cy]) => (
        <circle key={`${cx}-${cy}`} cx={cx} cy={cy} r="8" className="rink-red" />
      ))}
    </svg>
  );
}
