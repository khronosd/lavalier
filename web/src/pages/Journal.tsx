import type { DaySummary } from "../api";
import { DayNav } from "../components/DayNav";
import type { Route } from "../router";
import { Day } from "./Day";

interface Props {
  /** A today or day route. */
  route: Route;
  today: string;
  days: DaySummary[] | null;
}

/** The journal's page: Today (the local date) or the chosen day, with the way to its neighbours. */
export function Journal({ route, today, days }: Props) {
  const date = route.name === "day" ? route.params.date : today;
  return (
    <Day key={date} date={date} isToday={date === today} route={route}
      nav={<DayNav date={date} today={today} days={days} route={route} />} />
  );
}
