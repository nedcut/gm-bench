import { useTheme } from "../theme";
import { REPO, routes, type PageKey } from "../site";

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

const LINKS: { page: PageKey; href: string; label: string }[] = [
  { page: "results", href: routes.results, label: "Results" },
  { page: "replays", href: routes.replays, label: "Replays" },
  { page: "protocol", href: routes.protocol, label: "Protocol" },
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

export default function Nav({ contract, page }: { contract?: string; page: PageKey }) {
  return (
    <header className="nav">
      <div className="shell nav-inner">
        <a href={routes.home} className="brand" aria-current={page === "home" ? "page" : undefined}>
          <Logo />
          GM-Bench
          {/* The release label is data, not decoration: it must move with the
              published dataset rather than be edited by hand. */}
          <span className="brand-tag">{contract ?? "unversioned"}</span>
        </a>
        <nav className="nav-links" aria-label="Primary navigation">
          {LINKS.map((link) => (
            <a
              key={link.page}
              href={link.href}
              className={page === link.page ? "is-active" : undefined}
              aria-current={page === link.page ? "page" : undefined}
            >
              {link.label}
            </a>
          ))}
          <a href={REPO} className="nav-github">
            GitHub
          </a>
          <ThemeToggle />
        </nav>
      </div>
    </header>
  );
}
