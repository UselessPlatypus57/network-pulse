import { useEffect, useState } from "react";

/** Tracks the OS light/dark preference so non-CSS things (map tiles, chart ink) can follow it. */
export function useColorScheme(): "light" | "dark" {
  const query = "(prefers-color-scheme: light)";
  const [scheme, setScheme] = useState<"light" | "dark">(() =>
    window.matchMedia(query).matches ? "light" : "dark",
  );
  useEffect(() => {
    const mql = window.matchMedia(query);
    const onChange = () => setScheme(mql.matches ? "light" : "dark");
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, []);
  return scheme;
}

/** Read a CSS custom property (resolved for the current theme). */
export function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}
