// Settings › Connectors: the pure parts. normaliseNotionId mirrors src/lavalier/settings.py.

import type { CalendarAuth, ExportResult, ExportRow } from "./api";
import { dayMonth, hm } from "./format";

export const NOTION_SENTENCE =
  "Sends each day's text, and its Insights once generated, to the Notion database you choose. Audio is never sent.";
export const CALENDAR_SENTENCE =
  "Reads the calendars you pick on this Mac to name conversations after the event they overlap. Nothing leaves this Mac.";
export const BAD_DATABASE = "Paste the database's link from Notion, or its 32-character id.";
export const ALL_CALENDARS = "All calendars are read until you pick some.";
export const EXPORT_DAYS = 7;

const HEX32 = /^[0-9a-f]{32}$/i;
const UUID = /^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;
const URL_ID = /(?:^|-)([0-9a-f]{32})$/i;
const NOTION_HOSTS = ["notion.so", "www.notion.so"];

/** A Notion database id as 32 lower-case hex, from the raw id, a dashed uuid or a notion.so URL whose last
 *  path segment ends in the id; "" for an empty value, null for anything else. */
export function normaliseNotionId(value: string): string | null {
  const v = value.trim();
  if (v === "") return "";
  if (HEX32.test(v)) return v.toLowerCase();
  if (UUID.test(v)) return v.replace(/-/g, "").toLowerCase();
  let url: URL;
  try {
    url = new URL(v);
  } catch {
    return null;
  }
  if (!["http:", "https:"].includes(url.protocol) || !NOTION_HOSTS.includes(url.hostname)) return null;
  const segments = url.pathname.split("/").filter(Boolean);
  const m = segments.length ? URL_ID.exec(segments[segments.length - 1]) : null;
  return m ? m[1].toLowerCase() : null;
}

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/** "20 October", "20 October and 21 October", "a, b and c". */
function andList(items: string[]): string {
  return items.length <= 1 ? items.join("") : `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

/** What an export job did, in one line: "Exported 5 days, 1 unchanged; 1 stopped: 20 October was edited by
 *  hand; 1 failed: 22 October (its error)", and why it stopped part way when it did. */
export function exportResultLine(r: ExportResult): string {
  const parts: string[] = [];
  if (r.done || r.unchanged || (!r.stopped.length && !r.errors.length && !r.interrupted)) {
    if (!r.done && !r.unchanged) return "No days with speech to export";
    parts.push(`Exported ${plural(r.done, "day", "days")}${r.unchanged ? `, ${r.unchanged} unchanged` : ""}`);
  }
  if (r.stopped.length) {
    const days = andList(r.stopped.map(dayMonth));
    parts.push(`${r.stopped.length} stopped: ${days} ${r.stopped.length === 1 ? "was" : "were"} edited by hand`);
  }
  if (r.errors.length) {
    const days = r.errors.map((e) => (e.error ? `${dayMonth(e.day)} (${e.error})` : dayMonth(e.day)));
    parts.push(`${r.errors.length} failed: ${days.join(", ")}`);
  }
  if (r.interrupted) {
    const why = r.interrupted.charAt(0).toUpperCase() + r.interrupted.slice(1);
    parts.push(`${why} (${plural(r.not_sent?.length ?? 0, "day", "days")} not sent)`);
  }
  return parts.join("; ");
}

/** "exported 14:02", "stopped: <why>" or "error: <why>". */
export function exportRowState(row: ExportRow): string {
  if (row.state === "done") return row.exported_ms !== null ? `exported ${hm(row.exported_ms)}` : "exported";
  return `${row.state}: ${row.error ?? "no reason given"}`;
}

/** A row offers Export again when it was stopped by a hand edit or failed. */
export const canExportAgain = (row: ExportRow) => row.state === "stopped" || row.state === "error";

/** `calendar_ids` as identifiers: separated by commas or lines, blanks dropped (calendar.chosen_calendar_ids). */
export function calendarIds(raw: string): string[] {
  return raw.split(/[,\n]/).map((s) => s.trim()).filter(Boolean);
}

/** `calendar_ids` with one calendar picked or not, comma-separated; ids no longer listed are kept. */
export function toggleCalendar(raw: string, id: string, on: boolean): string {
  const ids = calendarIds(raw).filter((x) => x !== id);
  if (on) ids.push(id);
  return ids.join(",");
}

/** What the window says about calendar access. */
export function authLine(auth: CalendarAuth): string {
  switch (auth) {
    case "not-asked": return "Not asked yet";
    case "allowed": return "Allowed";
    case "denied": return "Denied: open System Settings › Privacy & Security › Calendars to allow it";
    case "restricted": return "Restricted on this Mac";
    case "unavailable": return "Calendar access is not available on this Mac";
    default: return "Not read yet";
  }
}
