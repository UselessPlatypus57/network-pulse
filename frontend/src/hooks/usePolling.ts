import { useCallback, useEffect, useRef, useState } from "react";

export interface Polled<T> {
  data: T | undefined;
  error: Error | undefined;
  lastSuccess: Date | undefined;
  refresh: () => void;
}

/**
 * Calls `fetcher` every `intervalMs`, keeping the last good value on errors so
 * the UI degrades to "stale" instead of going blank. Uses a setTimeout chain
 * (not setInterval) so slow responses never stack up, and pauses while the
 * tab is hidden unless `background` is set (for the one cheap poll that keeps
 * the tab title current).
 */
export function usePolling<T>(
  fetcher: () => Promise<T>,
  intervalMs: number,
  deps: unknown[] = [],
  { background = false }: { background?: boolean } = {},
): Polled<T> {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<Error>();
  const [lastSuccess, setLastSuccess] = useState<Date>();
  const [tick, setTick] = useState(0);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const refresh = useCallback(() => setTick((t) => t + 1), []);

  // New inputs (e.g. a different site) invalidate the old value immediately.
  useEffect(() => {
    setData(undefined);
    setError(undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const run = async () => {
      if (background || document.visibilityState === "visible") {
        try {
          const value = await fetcherRef.current();
          if (cancelled) return;
          setData(value);
          setError(undefined);
          setLastSuccess(new Date());
        } catch (e) {
          if (!cancelled) setError(e instanceof Error ? e : new Error(String(e)));
        }
      }
      if (!cancelled) timer = setTimeout(run, intervalMs);
    };
    run();

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs, tick, background, ...deps]);

  return { data, error, lastSuccess, refresh };
}
