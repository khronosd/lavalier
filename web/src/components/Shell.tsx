import type { ComponentChildren } from "preact";
import type { DaySummary } from "../api";
import type { Route } from "../router";
import { Sidebar } from "./Sidebar";

interface Props {
  route: Route;
  days: DaySummary[] | null;
  today: string;
  pendant?: ComponentChildren;
  insightsTodo?: number;
  children: ComponentChildren;
}

/** The window: the sidebar on the left, the routed page on the right. */
export function Shell({ route, days, today, pendant, insightsTodo, children }: Props) {
  return (
    <div class="shell">
      <Sidebar route={route} days={days} today={today} pendant={pendant} insightsTodo={insightsTodo} />
      <main class="main">{children}</main>
    </div>
  );
}
