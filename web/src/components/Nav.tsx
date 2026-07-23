import { useEffect, useState } from "react";
import { useTheme } from "../theme";

export function Logo({ size = 24 }: { size?: number }) {
  return (
    <img
      src={`${import.meta.env.BASE_URL}favicon.svg`}
      width={size}
      height={size}
      alt=""
      aria-hidden="true"
    />
  );
}

const LINKS = [
  { href: "#results", label: "Results" },
  { href: "#analysis", label: "Analysis" },
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
      {dark ? "Light" : "Dark"}
    </button>
  );
}

export default function Nav() {
  const [active, setActive] = useState(() =>
    typeof window === "undefined" ? "#results" : window.location.hash || "#results",
  );

  useEffect(() => {
    const update = () => setActive(window.location.hash || "#results");
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);

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
            <a
              key={link.href}
              href={link.href}
              className={active === link.href ? "is-active" : undefined}
            >
              {link.label}
            </a>
          ))}
          <ThemeToggle />
        </nav>
      </div>
    </header>
  );
}
