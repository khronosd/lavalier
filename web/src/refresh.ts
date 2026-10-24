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
