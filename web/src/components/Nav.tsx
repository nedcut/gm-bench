export function Logo({ size = 24 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="4" fill="#ffffff" stroke="#C5D3DE" />
      <line x1="6" y1="13" x2="26" y2="13" stroke="#C8102E" strokeWidth="3" />
      <line x1="6" y1="21" x2="26" y2="21" stroke="#1A5F8F" strokeWidth="2" />
    </svg>
  );
}

const LINKS = [
  { href: "#leaderboard", label: "Standings" },
  { href: "#protocol", label: "Protocol" },
  { href: "#quickstart", label: "Run" },
];

export default function Nav() {
  return (
    <header className="nav">
      <div className="shell nav-inner">
        <a href="#top" className="brand">
          <Logo />
          GM-Bench
          <span className="brand-tag">sota-v2</span>
        </a>
        <nav className="nav-links">
          {LINKS.map((link) => (
            <a key={link.href} href={link.href}>
              {link.label}
            </a>
          ))}
          <a className="nav-cta" href="#quickstart">
            Run locally
          </a>
        </nav>
      </div>
    </header>
  );
}
