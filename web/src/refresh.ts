// When the window's data is stale. The pendant card polls GET /api/status every 15 s; the shell
// derives a data version from it, and the days index and the open day refetch when it moves.

import { createContext } from "preact";
import { useContext, useEffect, useRef } from "preact/hooks";
import type { Status } from "./api";

/** Changes when the app may have new days or lines: a processing run finished (last_process carries
 * its time) or a sync ran. null until the first status. */
export function dataVersion(status: Status | null): string | null {
  if (!status) return null;
  return `${status.last_sync?.id ?? ""}|${status.last_process ?? ""}`;
}

/** The shell's current data version, for the pages under it. */
export const DataVersion = createContext<string | null>(null);

/** Calls onChange each time version moves from one known value to another; never for the first value
 * (a page's own first load covers that). */
export function useOnVersionChange(version: string | null, onChange: () => void): void {
  const seen = useRef<string | null>(version);
  const latest = useRef(onChange);
  latest.current = onChange;
  useEffect(() => {
    if (version === null) return;
    if (seen.current !== null && seen.current !== version) latest.current();
    seen.current = version;
  }, [version]);
}

/** useOnVersionChange on the shell's data version. */
export function useOnDataChange(onChange: () => void): void {
  useOnVersionChange(useContext(DataVersion), onChange);
}

// Insights change without a sync or a processing run (a Generate, a range): whoever ran one says so,
// and the sidebar's count reads the index again.
const insightsListeners = new Set<() => void>();

/** Tell the window that a day's insight may have changed. */
export function notifyInsightsChanged(): void {
  for (const listener of [...insightsListeners]) listener();
}

/** Calls onChange after each notifyInsightsChanged, until the component unmounts. */
export function useOnInsightsChange(onChange: () => void): void {
  const latest = useRef(onChange);
  latest.current = onChange;
  useEffect(() => {
    const listener = () => latest.current();
    insightsListeners.add(listener);
    return () => { insightsListeners.delete(listener); };
  }, []);
}
