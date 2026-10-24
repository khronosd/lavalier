// Hash routes: #/today, #/day/<date>, #/starred, #/search?q=, #/insights, #/settings/<tab>.
// Today and a day keep ?tab= (transcript, insights, audio) and ?conv= (the conversation the Audio tab plays).

import { useEffect, useState } from "preact/hooks";

export type RouteName = "today" | "day" | "starred" | "search" | "insights" | "settings";

export interface Route {
  name: RouteName;
  params: Record<string, string>;
  query: Record<string, string>;
}

export const SETTINGS_TABS = ["general", "pendant", "retention", "appearance"] as const;
const DATE = /^\d{4}-\d{2}-\d{2}$/;
/** The query keys a day page keeps; anything else in its hash is dropped. */
const DAY_QUERY = ["tab", "conv"] as const;

/** "2026-10-24" is a real calendar date; "9999-99-99" and "2026-02-30" are not. */
export function isCalendarDate(text: string): boolean {
  if (!DATE.test(text)) return false;
  const [y, m, d] = text.split("-").map(Number);
  const at = new Date(Date.UTC(y, m - 1, d));
  return at.getUTCFullYear() === y && at.getUTCMonth() === m - 1 && at.getUTCDate() === d;
}

function dayQuery(query: Record<string, string>): Record<string, string> {
  return Object.fromEntries(DAY_QUERY.filter((k) => query[k]).map((k) => [k, query[k]]));
}

function route(name: RouteName, params: Record<string, string> = {}, query: Record<string, string> = {}): Route {
  return { name, params, query };
}

/** Parse a location hash; anything unknown is Today. */
export function parseHash(hash: string): Route {
  const raw = hash.replace(/^#/, "");
  const [path, qs = ""] = raw.split("?", 2);
  const query = Object.fromEntries(new URLSearchParams(qs));
  let parts: string[];
  try {
    parts = path.split("/").filter(Boolean).map(decodeURIComponent);
  } catch {
    return route("today"); // a malformed escape
  }
  switch (parts[0]) {
    case "day":
      return parts.length === 2 && isCalendarDate(parts[1])
        ? route("day", { date: parts[1] }, dayQuery(query))
        : route("today");
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
    case "today":
      return route("today", {}, dayQuery(query));
    default:
      return route("today");
  }
}

function withQuery(path: string, query: Record<string, string>): string {
  const qs = new URLSearchParams(dayQuery(query)).toString();
  return qs ? `${path}?${qs}` : path;
}

/** The hash for a route, "#/day/2026-10-24". */
export function toHash(r: Route): string {
  switch (r.name) {
    case "day":
      return withQuery(`#/day/${r.params.date}`, r.query);
    case "today":
      return withQuery("#/today", r.query);
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
