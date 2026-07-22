import { useEffect, useState } from "react";

export type Theme = "light" | "dark";

const STORAGE_KEY = "gm-bench-theme";

function initialTheme(): Theme {
  if (typeof window === "undefined") return "light";
  const stored = window.localStorage.getItem(STORAGE_KEY);
  if (stored === "light" || stored === "dark") return stored;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/* Single source of truth for the palette: the hook only sets data-theme on
   <html>; every color lives in CSS variables that key off that attribute, so
   the tables and the SVG ladder recolor from the same cascade. */
export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(initialTheme);

  useEffect(() => {
    const root = document.documentElement;
    root.setAttribute("data-theme", theme);
    window.localStorage.setItem(STORAGE_KEY, theme);
    const meta = document.querySelector('meta[name="theme-color"]');
    meta?.setAttribute("content", theme === "dark" ? "#0d141b" : "#eef2f5");
  }, [theme]);

  const toggle = () => setTheme((current) => (current === "dark" ? "light" : "dark"));
  return [theme, toggle];
}
