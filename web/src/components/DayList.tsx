import type { DaySummary } from "../api";
import { dayTitle, duration } from "../format";
import type { Route } from "../router";
import { NavLink } from "./NavLink";

interface Props {
  route: Route;
  days: DaySummary[] | null;
  today: string;
}

/** "Friday 24" for the days list: the title without the month. */
function shortDay(iso: string): string {
  return dayTitle(iso).replace(",", "").split(" ").slice(0, 2).join(" ");
}

function DayCount({ day, today }: { day: DaySummary; today: string }) {
  return (
    <>
      {day.day === today ? "today" : duration(day.speech_ms)}
      {day.stars > 0 && <span class="stars" aria-label={`${day.stars} starred`}>★{day.stars}</span>}
    </>
  );
}

/** The journal: every day with clips, newest first, the open one marked current. */
export function DayList({ route, days, today }: Props) {
  const open = route.name === "day" ? route.params.date : null;
  return (
    <ul class="nav" aria-label="Days">
      {days === null && <li class="nav-note">Loading days</li>}
      {days !== null && days.length === 0 && <li class="nav-note">No days yet</li>}
      {days && [...days].sort((a, b) => b.day.localeCompare(a.day)).map((d) => (
        <NavLink key={d.day} class="day" to={{ name: "day", params: { date: d.day }, query: {} }}
          current={open === d.day ? "page" : undefined} label={shortDay(d.day)} count={<DayCount day={d} today={today} />} />
      ))}
    </ul>
  );
}
