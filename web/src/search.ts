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

/** A hit's line as the line element's id: "<clip_id>-<seq>". */
export const hitId = (hit: Hit) => `${hit.clip_id}-${hit.seq}`;

const OPERATORS = new Set(["AND", "OR", "NOT", "NEAR"]);

/** The query's words with quotes and FTS operators stripped, longest first (so a longer word wins a shared start). */
export function queryWords(query: string): string[] {
  const words = query.split(/\s+/).map((w) => w.replace(/["*()^:]/g, "")).filter((w) => w && !OPERATORS.has(w));
  return [...new Set(words)].sort((a, b) => b.length - a.length || a.localeCompare(b));
}

const escape = (word: string) => word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** A line's text with every occurrence of each query word in a <mark>, case-insensitively: plain strings
 *  (text nodes) and <mark> elements, never innerHTML. */
export function markWords(text: string, query: string): ComponentChildren[] {
  const words = queryWords(query);
  if (words.length === 0 || text === "") return text === "" ? [] : [text];
  const pattern = new RegExp(words.map(escape).join("|"), "gi");
  const parts: ComponentChildren[] = [];
  let from = 0;
  for (const m of text.matchAll(pattern)) {
    if (m.index > from) parts.push(text.slice(from, m.index));
    parts.push(h("mark", { key: m.index }, m[0]));
    from = m.index + m[0].length;
  }
  if (from < text.length) parts.push(text.slice(from));
  return parts;
}

// The last searches, for the inspector: kept in memory only, so a new window starts clean.
export const RECENT_MAX = 5;
let recent: string[] = [];

/** Remember a query, newest first, five at most; a query that was only the start of this one (typed on the
 *  way to it) gives way to it. */
export function rememberSearch(query: string): void {
  recent = [query, ...recent.filter((q) => q !== query && !query.startsWith(q))].slice(0, RECENT_MAX);
}

export function recentSearches(): string[] {
  return [...recent];
}

export function forgetSearches(): void {
  recent = [];
}
