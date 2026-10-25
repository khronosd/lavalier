import type { ComponentChildren } from "preact";
import type { DaySummary } from "../api";
import { dayTitle } from "../format";
import { type Route, toHash } from "../router";
import { ChevronLeftIcon, ChevronRightIcon } from "./icons";

interface Props {
  date: string;
  today: string;
  days: DaySummary[] | null;
  /** The current route, so the open tab carries over to the neighbouring day. */
  route: Route;
}

/** The nearest older and newer days with clips, given the days newest first. */
export function neighbours(date: string, days: DaySummary[]): { previous?: string; next?: string } {
  const older = days.filter((d) => d.day < date).map((d) => d.day);
  const newer = days.filter((d) => d.day > date).map((d) => d.day);
  return { previous: older.sort().at(-1), next: newer.sort()[0] };
}

function Step({ to, label, text, icon, route, today }: {
  to?: string; label: string; text: string; icon: ComponentChildren; route: Route; today: string;
}) {
  if (!to) return <span class="segment step" aria-disabled="true">{icon}<span class="sr">{text}</span></span>;
  const tab = route.query.tab;
  const target: Route = to === today
    ? { name: "today", params: {}, query: tab ? { tab } : {} }
    : { name: "day", params: { date: to }, query: tab ? { tab } : {} };
  return <a class="segment step" href={toHash(target)} aria-label={`${label}, ${dayTitle(to)}`}>{icon}<span class="sr">{text}</span></a>;
}

/** Previous, Today and next among the days with clips, as a small segmented group. */
export function DayNav({ date, today, days, route }: Props) {
  const { previous, next } = neighbours(date, days ?? []);
  const tab = route.query.tab;
  return (
    <nav class="day-nav segmented" aria-label="Days">
      <Step to={previous} label="Previous day" text="Previous" icon={<ChevronLeftIcon />} route={route} today={today} />
      {date === today
        ? <span class="segment" aria-disabled="true">Today</span>
        : <a class="segment" href={toHash({ name: "today", params: {}, query: tab ? { tab } : {} })}>Today</a>}
      <Step to={next} label="Next day" text="Next" icon={<ChevronRightIcon />} route={route} today={today} />
    </nav>
  );
}
