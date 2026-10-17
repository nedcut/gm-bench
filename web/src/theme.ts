import { useEffect, useState } from "react";

export type Theme = "light" | "dark";

const STORAGE_KEY = "gm-bench-theme";

/* Light unless the reader chose dark; the device preference is ignored. */
function initialTheme(): Theme {
  if (typeof window === "undefined") return "light";
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "dark" ? "dark" : "light";
  } catch {
    return "light";
  }
}

/* All colors live in CSS variables keyed off data-theme on <html>. */
export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(initialTheme);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", theme === "dark" ? "#0c1522" : "#f4f7fa");
  }, [theme]);

  const toggle = () => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Blocked storage only means the choice is not remembered.
    }
  };
  return [theme, toggle];
}
