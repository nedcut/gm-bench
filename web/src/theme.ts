import { useEffect, useState } from "react";

export type Theme = "light" | "dark";
type ThemePreference = "system" | Theme;

const STORAGE_KEY = "gm-bench-theme";

function systemTheme(): Theme {
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

function initialPreference(): ThemePreference {
  if (typeof window === "undefined") return "system";
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    return saved === "light" || saved === "dark" ? saved : "system";
  } catch {
    return "system";
  }
}

function initialTheme(): Theme {
  if (typeof window === "undefined") return "dark";
  const preference = initialPreference();
  return preference === "system" ? systemTheme() : preference;
}

/* All colors live in CSS variables keyed off data-theme on <html>. */
export function useTheme(): [Theme, ThemePreference, () => void] {
  const [preference, setPreference] = useState<ThemePreference>(initialPreference);
  const [theme, setTheme] = useState<Theme>(initialTheme);

  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: light)");
    const applyTheme = () => {
      const next = preference === "system" ? (media.matches ? "light" : "dark") : preference;
      setTheme(next);
      document.documentElement.setAttribute("data-theme", next);
      document.querySelector('meta[name="theme-color"]')?.setAttribute("content", next === "dark" ? "#0c1522" : "#f4f7fa");
    };
    applyTheme();
    media.addEventListener("change", applyTheme);
    return () => media.removeEventListener("change", applyTheme);
  }, [preference]);

  const cycle = () => {
    const next: ThemePreference = preference === "system" ? "light" : preference === "light" ? "dark" : "system";
    setPreference(next);
    try {
      if (next === "system") window.localStorage.removeItem(STORAGE_KEY);
      else window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Blocked storage only means an override is not remembered.
    }
  };
  return [theme, preference, cycle];
}
