// Hash routes: #/today, #/day/<date>, #/starred, #/search?q=, #/insights, #/settings/<tab>.

import { useEffect, useState } from "preact/hooks";

export type RouteName = "today" | "day" | "starred" | "search" | "insights" | "settings";

export interface Route {
  name: RouteName;
  params: Record<string, string>;
  query: Record<string, string>;
}

export const SETTINGS_TABS = ["general", "pendant", "retention", "appearance"] as const;
const DATE = /^\d{4}-\d{2}-\d{2}$/;

function route(name: RouteName, params: Record<string, string> = {}, query: Record<string, string> = {}): Route {
  return { name, params, query };
}

/** Parse a location hash; anything unknown is Today. */
export function parseHash(hash: string): Route {
  const raw = hash.replace(/^#/, "");
  const [path, qs = ""] = raw.split("?", 2);
  const query = Object.fromEntries(new URLSearchParams(qs));
  const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
  switch (parts[0]) {
    case "day":
      return parts.length === 2 && DATE.test(parts[1]) ? route("day", { date: parts[1] }) : route("today");
    case "starred":
      return route("starred");
    case "search":
      return route("search", {}, { q: query.q ?? "" });
    case "insights":
      return route("insights");
    case "settings": {
      const tab = (SETTINGS_TABS as readonly string[]).includes(parts[1]) ? parts[1] : "general";
      return route("settings", { tab });
    }
    default:
      return route("today");
  }
}

/** The hash for a route, "#/day/2026-10-24". */
export function toHash(r: Route): string {
  switch (r.name) {
    case "day":
      return `#/day/${r.params.date}`;
    case "search":
      return r.query.q ? `#/search?${new URLSearchParams({ q: r.query.q })}` : "#/search";
    case "settings":
      return `#/settings/${r.params.tab ?? "general"}`;
    default:
      return `#/${r.name}`;
  }
}

export function navigate(r: Route | string): void {
  window.location.hash = typeof r === "string" ? r : toHash(r);
}

export function useRoute(): Route {
  const [current, setCurrent] = useState(() => parseHash(window.location.hash));
  useEffect(() => {
    const onChange = () => setCurrent(parseHash(window.location.hash));
    window.addEventListener("hashchange", onChange);
    onChange();
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return current;
}
