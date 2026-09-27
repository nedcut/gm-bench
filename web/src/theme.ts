import { useEffect, useState } from "react";

export type Theme = "light" | "dark";

const STORAGE_KEY = "gm-bench-theme";

/* The site is dark by default (the rink under arena lights); a reader's saved
   choice wins. The HTML entries apply the same rule before first paint. */
function initialTheme(): Theme {
  if (typeof window === "undefined") return "dark";
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "light" ? "light" : "dark";
  } catch {
    // Storage can be blocked (privacy settings, sandboxed frames); fall back to the default.
    return "dark";
  }
}

/* Single source of truth for the palette: the hook only sets data-theme on
   <html>; every color lives in CSS variables that key off that attribute, so
   the tables and the SVG ladder recolor from the same cascade. */
export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(initialTheme);

  useEffect(() => {
    const root = document.documentElement;
    root.setAttribute("data-theme", theme);
    try {
      window.localStorage.setItem(STORAGE_KEY, theme);
    } catch {
      // Blocked storage only means the choice is not remembered.
    }
    const meta = document.querySelector('meta[name="theme-color"]');
    meta?.setAttribute("content", theme === "dark" ? "#0c1522" : "#f4f7fa");
  }, [theme]);

  const toggle = () => setTheme((current) => (current === "dark" ? "light" : "dark"));
  return [theme, toggle];
}
