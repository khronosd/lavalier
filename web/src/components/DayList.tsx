import type { DaySummary } from "../api";
import { dayTitle, duration, monthName } from "../format";
import type { Route } from "../router";
import { StarFillIcon } from "./icons";
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
      {day.stars > 0 && <span class="stars" aria-label={`${day.stars} starred`}><StarFillIcon />{day.stars}</span>}
      <span class="nav-len">{day.day === today ? "today" : duration(day.speech_ms)}</span>
    </>
  );
}

interface Month {
  key: string;
  name: string;
  days: DaySummary[];
}

/** The journal: every day with clips, newest first, under a head per month, the open one marked current. */
export function DayList({ route, days, today }: Props) {
  const open = route.name === "day" ? route.params.date : null;
  if (days === null) return <p class="nav-note">Loading days</p>;
  if (days.length === 0) return <p class="nav-note">No days yet</p>;
  const months: Month[] = [];
  for (const d of [...days].sort((a, b) => b.day.localeCompare(a.day))) {
    const key = d.day.slice(0, 7);
    const last = months[months.length - 1];
    if (last && last.key === key) last.days.push(d);
    else months.push({ key, name: monthName(d.day, today), days: [d] });
  }
  return (
    <>
      {months.map((m) => (
        <div class="nav-month" key={m.key}>
          <p class="hd nav-head">{m.name}</p>
          <ul class="nav" aria-label={`Days in ${m.name}`}>
            {m.days.map((d) => (
              <NavLink key={d.day} class="day" to={{ name: "day", params: { date: d.day }, query: {} }}
                current={open === d.day ? "page" : undefined} label={shortDay(d.day)} count={<DayCount day={d} today={today} />} />
            ))}
          </ul>
        </div>
      ))}
    </>
  );
}
