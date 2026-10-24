// Search results and starred moments: grouping by day, and the snippet's highlights as text plus <mark>.
// A snippet is raw transcript text in which FTS5 put literal "<mark>" and "</mark>"; nothing else in it
// is markup, so it is never parsed as HTML.

import { type ComponentChildren, h } from "preact";
import type { Hit, IsoDate } from "./api";
import { toHash } from "./router";

export interface DayGroup<T> {
  day: IsoDate;
  items: T[];
}

/** Items grouped by their day, newest day first; each day keeps the items' order. */
export function groupByDay<T extends { day: IsoDate }>(items: T[]): DayGroup<T>[] {
  const byDay = new Map<IsoDate, T[]>();
  for (const item of items) {
    const list = byDay.get(item.day);
    if (list) list.push(item);
    else byDay.set(item.day, [item]);
  }
  return [...byDay.entries()].sort(([a], [b]) => b.localeCompare(a)).map(([day, list]) => ({ day, items: list }));
}

/** Hits grouped by day, newest day first, each day's hits in time order. */
export function groupHits(hits: Hit[]): { day: IsoDate; hits: Hit[] }[] {
  const inTime = [...hits].sort((a, b) =>
    a.at_ms - b.at_ms || a.clip_id.localeCompare(b.clip_id) || a.seq - b.seq);
  return groupByDay(inTime).map(({ day, items }) => ({ day, hits: items }));
}

export interface SnippetPart {
  text: string;
  marked: boolean;
}

const MARKER = /<mark>|<\/mark>/g;

/** The snippet as runs of text, each marked or not. The markers are dropped; a nested marker stays
 *  marked until its matching close, a stray close is ignored, an unclosed open marks the rest. */
export function splitSnippet(snippet: string): SnippetPart[] {
  const parts: SnippetPart[] = [];
  let depth = 0;
  let from = 0;
  const push = (end: number) => {
    if (end > from) parts.push({ text: snippet.slice(from, end), marked: depth > 0 });
  };
  for (const m of snippet.matchAll(MARKER)) {
    push(m.index);
    depth = m[0] === "<mark>" ? depth + 1 : Math.max(0, depth - 1);
    from = m.index + m[0].length;
  }
  push(snippet.length);
  return parts;
}

/** The snippet for rendering: plain strings (text nodes) and <mark> elements, never innerHTML. */
export function renderSnippet(snippet: string): ComponentChildren[] {
  return splitSnippet(snippet).map((p, i) => (p.marked ? h("mark", { key: i }, p.text) : p.text));
}

const CONV_ID = /^c-\d{8}-(\d{2})(\d{2})\d{2}$/;

/** "c-20261023-225600" -> "22:56": a conversation id carries its local start; null for any other id. */
export function convStart(conversationId: string): string | null {
  const m = CONV_ID.exec(conversationId);
  if (!m || Number(m[1]) > 23 || Number(m[2]) > 59) return null;
  return `${m[1]}:${m[2]}`;
}

/** The hash that opens a day and brings one element (a line or a conversation) into view. */
export function jumpHref(day: IsoDate, at?: string): string {
  return toHash({ name: "day", params: { date: day }, query: at ? { at } : {} });
}
