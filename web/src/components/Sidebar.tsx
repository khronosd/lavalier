import type { ComponentChildren } from "preact";
import type { DaySummary } from "../api";
import type { Route } from "../router";
import { DayList } from "./DayList";
import { InsightsIcon, JournalIcon, SearchIcon, SettingsIcon, StarIcon, TodayIcon } from "./icons";
import { NavLink } from "./NavLink";
import { SearchBox } from "./SearchBox";

interface Props {
  route: Route;
  days: DaySummary[] | null;
  today: string;
  /** The pendant card (PendantCard); nothing is drawn while it is empty. */
  pendant?: ComponentChildren;
  /** Complete days still without an insight, counted only while a provider is set. */
  insightsTodo?: number;
}

const r = (name: Route["name"], params: Record<string, string> = {}): Route => ({ name, params, query: {} });
const page = (on: boolean) => (on ? "page" : undefined);

export function Sidebar({ route, days, today, pendant, insightsTodo }: Props) {
  const journalCount = days && days.length > 0 ? `${days.length} ${days.length === 1 ? "day" : "days"}` : undefined;
  return (
    <aside class="sidebar" aria-label="Sections">
      <SearchBox route={route} />
      <nav class="sidebar-scroll">
        <ul class="nav">
          <NavLink to={r("today")} current={page(route.name === "today")} icon={<TodayIcon />} label="Today" />
          <NavLink to={days?.[0] ? r("day", { date: days[0].day }) : r("today")}
            current={route.name === "day" ? "true" : undefined}
            icon={<JournalIcon />} label="Journal" count={journalCount} />
        </ul>
        <DayList route={route} days={days} today={today} />
        <ul class="nav">
          <NavLink to={r("starred")} current={page(route.name === "starred")} icon={<StarIcon />} label="Starred" />
          <NavLink to={r("search")} current={page(route.name === "search")} icon={<SearchIcon />} label="Search" />
          <NavLink to={r("insights")} current={page(route.name === "insights")} icon={<InsightsIcon />} label="Insights"
            count={insightsTodo ? `${insightsTodo} to do` : undefined} />
        </ul>
      </nav>
      <div class="sidebar-foot">
        <div class="pendant-slot">{pendant}</div>
        <ul class="nav">
          <NavLink to={r("settings", { tab: "general" })} current={page(route.name === "settings")}
            icon={<SettingsIcon />} label="Settings" />
        </ul>
      </div>
    </aside>
  );
}
