import { useCallback, useEffect, useRef, useState } from "react";

export interface Polled<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  refresh: () => void;
}

/**
 * Loads data now and then every `intervalMs`. Keeps the last good data when a refresh
 * fails, so a brief API outage shows an error banner instead of an empty page.
 */
export function usePolling<T>(
  load: (signal: AbortSignal) => Promise<T>,
  intervalMs: number,
  deps: unknown[] = [],
): Polled<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const loadRef = useRef(load);
  loadRef.current = load;

  const refresh = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    loadRef
      .current(controller.signal)
      .then((value) => {
        setData(value);
        setError(null);
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        setError(reason instanceof Error ? reason.message : String(reason));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    const timer = window.setTimeout(refresh, intervalMs);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [tick, intervalMs, refresh, ...deps]);

  return { data, error, loading, refresh };
}
