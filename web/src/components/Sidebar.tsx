import type { DaySummary } from "../api";
import type { Route } from "../router";
import { DayList } from "./DayList";
import { InsightsIcon, SearchIcon, SettingsIcon, StarIcon, TodayIcon } from "./icons";
import { NavLink } from "./NavLink";

interface Props {
  route: Route;
  days: DaySummary[] | null;
  today: string;
  /** Complete days still without an insight, counted only while a provider is set. */
  insightsTodo?: number;
}

const r = (name: Route["name"], params: Record<string, string> = {}): Route => ({ name, params, query: {} });
const page = (on: boolean) => (on ? "page" : undefined);

/** The sidebar: Today, Starred, Search, Insights; the days under their month; Settings at the bottom. The
 * first 38 px stay free of controls for the native title bar. */
export function Sidebar({ route, days, today, insightsTodo }: Props) {
  return (
    <nav class="sidebar" aria-label="Sidebar">
      <div class="sidebar-scroll">
        <ul class="nav">
          <NavLink to={r("today")} current={page(route.name === "today")} icon={<TodayIcon />} label="Today" />
          <NavLink to={r("starred")} current={page(route.name === "starred")} icon={<StarIcon />} label="Starred" />
          <NavLink to={r("search")} current={page(route.name === "search")} icon={<SearchIcon />} label="Search" />
          <NavLink to={r("insights")} current={page(route.name === "insights")} icon={<InsightsIcon />} label="Insights"
            count={insightsTodo ? `${insightsTodo} to do` : undefined} />
        </ul>
        <DayList route={route} days={days} today={today} />
      </div>
      <div class="sidebar-foot">
        <ul class="nav">
          <NavLink to={r("settings", { tab: "general" })} current={page(route.name === "settings")}
            icon={<SettingsIcon />} label="Settings" />
        </ul>
      </div>
    </nav>
  );
}
