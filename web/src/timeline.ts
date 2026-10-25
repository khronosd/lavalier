// The timeline band's geometry, as pure maths: the day's range, the hour ticks, a block per conversation
// and a dot per star, all as percentages of the band's width so the stylesheet can place them.

import type { DayView } from "./api";
import { span } from "./components/Conversation";

export interface TimeRange {
  start_ms: number;
  end_ms: number;
}

export const HOUR_MS = 3_600_000;
/** A day's range is never shorter than this. */
export const MIN_RANGE_MS = 6 * HOUR_MS;
/** What an unmeasured band (no layout yet) is taken to be. */
export const DEFAULT_WIDTH_PX = 1000;
/** Hour labels closer than this are thinned to every second hour. */
export const HOUR_LABEL_GAP_PX = 56;
/** A block label whose centre is within this of the last drawn label's centre is dropped. */
export const BLOCK_LABEL_GAP_PX = 90;
export const MIN_BLOCK_PX = 6;
export const BLOCK_HEIGHT_PX = { min: 26, max: 52 };

const floorHour = (ms: number) => { const d = new Date(ms); d.setMinutes(0, 0, 0); return d.getTime(); };
const ceilHour = (ms: number) => { const d = new Date(ms - 1); d.setMinutes(0, 0, 0); d.setHours(d.getHours() + 1); return d.getTime(); };
const localDate = (day: string, hour: number) => { const [y, m, d] = day.split("-").map(Number); return new Date(y, m - 1, d, hour).getTime(); };

/** The band's range: from the start of the first conversation's hour to the end of the last one's, at
 * least six hours, kept inside the day (a late or midnight-spanning conversation pushes the start back
 * instead); an empty day shows 8:00 to 20:00. */
export function timelineRange(view: DayView): TimeRange {
  const dayStart = localDate(view.day, 0);
  const dayEnd = localDate(view.day, 24);
  if (view.conversations.length === 0) return { start_ms: localDate(view.day, 8), end_ms: localDate(view.day, 20) };
  let start = Math.max(dayStart, floorHour(Math.min(...view.conversations.map((c) => c.start_ms))));
  let end = Math.min(dayEnd, ceilHour(Math.max(...view.conversations.map((c) => c.end_ms))));
  if (end - start < MIN_RANGE_MS) end = start + MIN_RANGE_MS;
  if (end > dayEnd) {
    end = dayEnd;
    start = Math.max(dayStart, end - MIN_RANGE_MS);
  }
  return { start_ms: start, end_ms: end };
}

const pct = (range: TimeRange, ms: number) => ((ms - range.start_ms) / (range.end_ms - range.start_ms)) * 100;
const widthOf = (px: number) => px > 0 ? px : DEFAULT_WIDTH_PX;

export interface Tick {
  ms: number;
  /** Percent of the band's width. */
  left: number;
  /** "8:00"; null for an hour left unlabelled. */
  label: string | null;
}

/** A tick per hour from the range's start to its end, both included; labels every second hour when a
 * band this wide would put them closer than 56 px. */
export function hourTicks(range: TimeRange, widthPx: number): Tick[] {
  const ticks: Tick[] = [];
  for (let ms = range.start_ms; ms <= range.end_ms; ms = ceilHour(ms + 1)) {
    ticks.push({ ms, left: pct(range, ms), label: `${new Date(ms).getHours()}:00` });
  }
  const hours = (range.end_ms - range.start_ms) / HOUR_MS;
  if (widthOf(widthPx) / hours < HOUR_LABEL_GAP_PX) {
    ticks.forEach((t, i) => { if (i % 2 === 1) t.label = null; });
  }
  return ticks;
}

export interface Block {
  id: string;
  /** Percent of the band's width. */
  left: number;
  width: number;
  /** Pixels, 26 to 52 by speech density. */
  height: number;
  /** The calendar label, else the time range. */
  name: string;
  range: string;
  /** The label's centre, percent. */
  centre: number;
  /** False when the label would crowd the last one drawn; the name stays in the block's title. */
  labelShown: boolean;
  selected: boolean;
}

/** A block per conversation inside the range, clamped to it (a conversation of the next day draws
 * nothing), no narrower than 6 px, 26 to 52 px tall by speech density, later ones drawn on top. */
export function blocks(view: DayView, range: TimeRange, selected: string | null, widthPx: number): Block[] {
  const px = widthOf(widthPx);
  const minWidth = (MIN_BLOCK_PX / px) * 100;
  const out: Block[] = [];
  let lastLabelPx: number | null = null;
  for (const c of view.conversations) {
    const start = Math.max(c.start_ms, range.start_ms);
    const end = Math.min(c.end_ms, range.end_ms);
    if (end <= range.start_ms || start >= range.end_ms) continue;
    const left = pct(range, start);
    const width = Math.max(pct(range, end) - left, minWidth);
    const density = c.end_ms > c.start_ms ? Math.min(1, Math.max(0, c.speech_ms / (c.end_ms - c.start_ms))) : 0;
    const height = Math.round(BLOCK_HEIGHT_PX.min + density * (BLOCK_HEIGHT_PX.max - BLOCK_HEIGHT_PX.min));
    const centre = left + width / 2;
    const centrePx = (centre / 100) * px;
    const labelShown = lastLabelPx === null || centrePx - lastLabelPx >= BLOCK_LABEL_GAP_PX;
    if (labelShown) lastLabelPx = centrePx;
    const time = span(c);
    out.push({
      id: c.conversation_id, left, width, height, name: c.label ?? time, range: time, centre, labelShown,
      selected: c.conversation_id === selected,
    });
  }
  return out;
}

/** The stars inside the range, as percentages along it. */
export function starDots(view: DayView, range: TimeRange): number[] {
  return view.stars.filter((s) => s.at_ms >= range.start_ms && s.at_ms <= range.end_ms).map((s) => pct(range, s.at_ms));
}
