import type { ReactNode } from "react";

/* Header for the deep pages: a kicker, the page's one-line claim, a lede, and
   jump links to the sections below. */
export default function PageHeader({
  kicker,
  title,
  children,
  jumps = [],
  wide = false,
}: {
  kicker: string;
  title: ReactNode;
  children?: ReactNode;
  jumps?: { href: string; label: string }[];
  /** Match the 1480px results layout instead of the standard reading width. */
  wide?: boolean;
}) {
  return (
    <header className="page-head">
      <div className={wide ? "results-shell" : "shell"}>
        <p className="eyebrow">{kicker}</p>
        <h1 className="page-title">{title}</h1>
        {children && <div className="page-lede">{children}</div>}
        {jumps.length > 0 && (
          <nav className="page-jumps" aria-label="On this page">
            {jumps.map((jump) => (
              <a key={jump.href} href={jump.href}>
                {jump.label}
              </a>
            ))}
          </nav>
        )}
      </div>
    </header>
  );
}
