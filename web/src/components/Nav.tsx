import { useTheme } from "../theme";

export function Logo({ size = 24 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="4" style={{ fill: "var(--card)", stroke: "var(--line-strong)" }} />
      <line x1="6" y1="13" x2="26" y2="13" style={{ stroke: "var(--red)" }} strokeWidth="3" />
      <line x1="6" y1="21" x2="26" y2="21" style={{ stroke: "var(--blue)" }} strokeWidth="2" />
    </svg>
  );
}

const LINKS = [
  { href: "#leaderboard", label: "Standings" },
  { href: "#protocol", label: "Protocol" },
  { href: "#quickstart", label: "Run" },
];

function ThemeToggle() {
  const [theme, toggle] = useTheme();
  const dark = theme === "dark";
  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={toggle}
      aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}
      title={dark ? "Light theme" : "Dark theme"}
    >
      {dark ? (
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
          <circle cx="12" cy="12" r="4.2" />
          <path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M19.1 4.9L17 7M7 17l-2.1 2.1" strokeLinecap="round" />
        </svg>
      ) : (
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
          <path d="M20 14.5A8 8 0 1 1 9.5 4a6.3 6.3 0 0 0 10.5 10.5Z" strokeLinejoin="round" />
        </svg>
      )}
    </button>
  );
}

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
          <ThemeToggle />
        </nav>
      </div>
    </header>
  );
}
