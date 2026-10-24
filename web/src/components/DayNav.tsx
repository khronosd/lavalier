import type { DaySummary } from "../api";
import { dayTitle } from "../format";
import { type Route, toHash } from "../router";

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

function Step({ to, label, text, route, today }: { to?: string; label: string; text: string; route: Route; today: string }) {
  if (!to) return <span class="btn" aria-disabled="true">{text}</span>;
  const tab = route.query.tab;
  const target: Route = to === today
    ? { name: "today", params: {}, query: tab ? { tab } : {} }
    : { name: "day", params: { date: to }, query: tab ? { tab } : {} };
  return <a class="btn" href={toHash(target)} aria-label={`${label}, ${dayTitle(to)}`}>{text}</a>;
}

/** Previous and next among the days with clips, and Today. */
export function DayNav({ date, today, days, route }: Props) {
  const { previous, next } = neighbours(date, days ?? []);
  return (
    <nav class="day-nav" aria-label="Days">
      <Step to={previous} label="Previous day" text="Previous" route={route} today={today} />
      <Step to={next} label="Next day" text="Next" route={route} today={today} />
      {date === today
        ? <span class="btn" aria-disabled="true">Today</span>
        : <a class="btn" href={toHash({ name: "today", params: {}, query: route.query.tab ? { tab: route.query.tab } : {} })}>Today</a>}
    </nav>
  );
}
