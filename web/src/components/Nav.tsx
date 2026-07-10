import { useEffect, useState } from "react";

export function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="7" fill="#0b1020" stroke="rgba(148,173,214,0.25)" />
      <path
        d="M16 5 7 9.2v6.3c0 5.5 3.7 9.4 9 11.5 5.3-2.1 9-6 9-11.5V9.2L16 5Z"
        fill="none"
        stroke="#34e0a1"
        strokeWidth="2"
        strokeLinejoin="round"
      />
      <path d="M11.5 15.5h9M13 19h6" stroke="#8ab4ff" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

const LINKS = [
  { href: "#why", id: "why", label: "Why" },
  { href: "#leaderboard", id: "leaderboard", label: "Leaderboard" },
  { href: "#how-it-works", id: "how-it-works", label: "How it works" },
  { href: "#quickstart", id: "quickstart", label: "Run" },
];

const REPO = "https://github.com/nedcut/gm-bench";

export default function Nav() {
  const [scrolled, setScrolled] = useState(false);
  const [active, setActive] = useState("");

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 18);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    const sections = LINKS.map((link) => document.getElementById(link.id)).filter(
      (node): node is HTMLElement => Boolean(node),
    );
    if (sections.length === 0) return;

    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries
          .filter((entry) => entry.isIntersecting)
          .sort((a, b) => b.intersectionRatio - a.intersectionRatio);
        if (visible[0]?.target.id) {
          setActive(visible[0].target.id);
        }
      },
      { rootMargin: "-28% 0px -55% 0px", threshold: [0.1, 0.35, 0.6] },
    );

    for (const section of sections) observer.observe(section);
    return () => observer.disconnect();
  }, []);

  return (
    <header className={`nav ${scrolled ? "is-scrolled" : ""}`}>
      <div className="shell nav-inner">
        <a href="#top" className="brand">
          <Logo />
          GM-Bench
        </a>
        <nav className="nav-links">
          {LINKS.map((link) => (
            <a
              key={link.href}
              href={link.href}
              className={active === link.id ? "is-active" : undefined}
            >
              {link.label}
            </a>
          ))}
          <a className="nav-link-ext" href={REPO} target="_blank" rel="noreferrer">
            GitHub
          </a>
          <a className="nav-cta" href="#quickstart">
            Run the benchmark
          </a>
        </nav>
      </div>
    </header>
  );
}
