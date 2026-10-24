import type { ComponentChildren } from "preact";
import type { DaySummary } from "../api";
import { dayTitle, duration } from "../format";
import { type Route, toHash } from "../router";
import { InsightsIcon, JournalIcon, SearchIcon, SettingsIcon, StarIcon, TodayIcon } from "./icons";

interface Props {
  route: Route;
  days: DaySummary[] | null;
  today: string;
  /** The pendant card, filled by a later task; nothing is drawn while it is empty. */
  pendant?: ComponentChildren;
}

const r = (name: Route["name"], params: Record<string, string> = {}): Route => ({ name, params, query: {} });

function NavLink({ to, current, icon, label, count, class: cls }: {
  to: Route; current: boolean; icon?: ComponentChildren; label: ComponentChildren; count?: ComponentChildren;
  class?: string;
}) {
  return (
    <li>
      <a class={cls ? `nav-item ${cls}` : "nav-item"} href={toHash(to)} aria-current={current ? "page" : undefined}>
        {icon}
        <span>{label}</span>
        {count !== undefined && <span class="nav-count">{count}</span>}
      </a>
    </li>
  );
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

export function Sidebar({ route, days, today, pendant }: Props) {
  const onDay = (d: string) => route.name === "day" && route.params.date === d;
  const journalCount = days && days.length > 0 ? `${days.length} ${days.length === 1 ? "day" : "days"}` : undefined;
  return (
    <aside class="sidebar" aria-label="Sections">
      <nav class="sidebar-scroll">
        <ul class="nav">
          <NavLink to={r("today")} current={route.name === "today"} icon={<TodayIcon />} label="Today" />
          <NavLink to={days?.[0] ? r("day", { date: days[0].day }) : r("today")} current={false}
            icon={<JournalIcon />} label="Journal" count={journalCount} />
          <NavLink to={r("starred")} current={route.name === "starred"} icon={<StarIcon />} label="Starred" />
          <NavLink to={r("search")} current={route.name === "search"} icon={<SearchIcon />} label="Search" />
          <NavLink to={r("insights")} current={route.name === "insights"} icon={<InsightsIcon />} label="Insights" />
        </ul>
        <h2 class="nav-heading">Journal</h2>
        <ul class="nav" aria-label="Days">
          {days === null && <li class="nav-note">Loading days</li>}
          {days !== null && days.length === 0 && <li class="nav-note">No days yet</li>}
          {days?.map((d) => (
            <NavLink key={d.day} class="day" to={r("day", { date: d.day })} current={onDay(d.day)}
              label={shortDay(d.day)} count={<DayCount day={d} today={today} />} />
          ))}
        </ul>
      </nav>
      <div class="sidebar-foot">
        <div class="pendant-slot">{pendant}</div>
        <ul class="nav">
          <NavLink to={r("settings", { tab: "general" })} current={route.name === "settings"}
            icon={<SettingsIcon />} label="Settings" />
        </ul>
      </div>
    </aside>
  );
}
