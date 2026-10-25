import type { ComponentChildren } from "preact";
import { useEffect, useRef, useState } from "preact/hooks";
import type { DaySummary } from "../api";
import { type Route, toHash } from "../router";
import { COMPACT, NARROW, PendantContext, ShellContext, type ShellState, useMedia } from "../shellState";
import type { PendantStatus } from "../usePendantStatus";
import { Sidebar } from "./Sidebar";

interface Props {
  route: Route;
  days: DaySummary[] | null;
  today: string;
  /** The pendant's status; the toolbar draws it as a pill. */
  pendant?: PendantStatus | null;
  insightsTodo?: number;
  children: ComponentChildren;
}

/** The window: the sidebar on the left, then the frame each page fills with its toolbar and panes. Below
 * 1216 px the inspector folds into a popover, below 1000 px the sidebar into an overlay; a choice made at
 * one width is forgotten when the window crosses the breakpoint, and the overlay closes on navigation. */
export function Shell({ route, days, today, pendant = null, insightsTodo, children }: Props) {
  const narrow = useMedia(NARROW);
  const compact = useMedia(COMPACT);
  const [sidebarChoice, setSidebarChoice] = useState<boolean | null>(null);
  const [inspectorChoice, setInspectorChoice] = useState<boolean | null>(null);
  const mounted = useRef(false);
  useEffect(() => {
    if (!mounted.current) { mounted.current = true; return; }
    setSidebarChoice(null);
    setInspectorChoice(null);
  }, [narrow, compact]);
  const hash = toHash(route);
  useEffect(() => { if (narrow) setSidebarChoice(null); }, [hash]);

  const sidebarShown = narrow ? sidebarChoice === true : sidebarChoice !== false;
  const inspectorShown = compact ? inspectorChoice === true : true;
  const state: ShellState = {
    route, narrow, compact, sidebarShown,
    toggleSidebar: () => setSidebarChoice(!sidebarShown),
    closeSidebar: () => setSidebarChoice(false),
    inspectorShown,
    toggleInspector: () => setInspectorChoice(!inspectorShown),
    openInspector: () => setInspectorChoice(true),
    closeInspector: () => setInspectorChoice(false),
  };
  const overlay = narrow && sidebarShown;
  const cls = ["shell", narrow ? "narrow" : "", sidebarShown ? "" : "sidebar-hidden", overlay ? "sidebar-overlay" : ""]
    .filter(Boolean).join(" ");
  return (
    <PendantContext.Provider value={pendant}>
      <ShellContext.Provider value={state}>
        <div class={cls}>
          {overlay && <div class="scrim" onClick={state.closeSidebar} />}
          <Sidebar route={route} days={days} today={today} insightsTodo={insightsTodo} />
          <div class="frame">{children}</div>
        </div>
      </ShellContext.Provider>
    </PendantContext.Provider>
  );
}
