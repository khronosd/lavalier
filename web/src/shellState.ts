// What the shell shares with the toolbar and the frames under it: the route, the pendant's status, and
// whether the sidebar and the inspector are shown at this window width.

import { createContext } from "preact";
import { useContext, useEffect, useState } from "preact/hooks";
import type { Route } from "./router";
import type { PendantStatus } from "./usePendantStatus";

/** The pendant's status, owned by App (its polls also tell the pages when to refetch); null outside the app. */
export const PendantContext = createContext<PendantStatus | null>(null);
export const usePendant = () => useContext(PendantContext);

export interface ShellState {
  route: Route;
  /** Narrower than 1000 px: the sidebar is an overlay behind its toggle. */
  narrow: boolean;
  /** Narrower than 1216 px: the inspector is a popover behind its toggle. */
  compact: boolean;
  sidebarShown: boolean;
  toggleSidebar(): void;
  closeSidebar(): void;
  inspectorShown: boolean;
  toggleInspector(): void;
  openInspector(): void;
  closeInspector(): void;
}

const noop = () => undefined;

/** Outside a Shell (a page rendered on its own): everything shown, nothing to toggle. */
export const ShellContext = createContext<ShellState>({
  route: { name: "today", params: {}, query: {} }, narrow: false, compact: false,
  sidebarShown: true, toggleSidebar: noop, closeSidebar: noop,
  inspectorShown: true, toggleInspector: noop, openInspector: noop, closeInspector: noop,
});
export const useShell = () => useContext(ShellContext);

export const NARROW = "(max-width: 999px)";
export const COMPACT = "(max-width: 1215px)";

/** Whether a media query matches, following changes; false where matchMedia is missing (tests). */
export function useMedia(query: string): boolean {
  const [on, setOn] = useState(() => window.matchMedia?.(query).matches ?? false);
  useEffect(() => {
    const media = window.matchMedia?.(query);
    if (!media) return;
    const onChange = (e: { matches: boolean }) => setOn(e.matches);
    setOn(media.matches);
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, [query]);
  return on;
}
