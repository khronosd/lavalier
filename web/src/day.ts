// Pure helpers for a day page: where stars fall in a conversation, and the day's one-sentence summary.

import type { ConversationView, DayView, Line } from "./api";
import { dayMonth, duration } from "./format";

export type TranscriptItem = { kind: "line"; line: Line } | { kind: "star"; at_ms: number };

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

/**
 * The conversation's lines with a star item at each star's time, in time order. Stars outside the
 * conversation's span are left out; a star at the same time as a line comes before it (the quote
 * under a star is the speech at or just after it).
 */
export function placeStars(conv: ConversationView): TranscriptItem[] {
  const lines = [...conv.lines].sort((a, b) => a.at_ms - b.at_ms || a.seq - b.seq);
  const stars = conv.star_ms.filter((ms) => ms >= conv.start_ms && ms <= conv.end_ms).sort((a, b) => a - b);
  const items: TranscriptItem[] = [];
  let s = 0;
  for (const line of lines) {
    while (s < stars.length && stars[s] <= line.at_ms) items.push({ kind: "star", at_ms: stars[s++] });
    items.push({ kind: "line", line });
  }
  while (s < stars.length) items.push({ kind: "star", at_ms: stars[s++] });
  return items;
}

function audioSentence(view: DayView): string {
  if (view.audio_until) return `The audio is kept until ${dayMonth(view.audio_until)}.`;
  if (view.audio_kept_for_good) return "The audio is kept for good.";
  return "The audio is no longer kept.";
}

/** "3 h 1 min of speech in 6 conversations. 75 noise clips were dropped. The audio is kept until 7 November." */
export function summarySentence(view: DayView): string {
  const parts = [`${duration(view.speech_ms)} of speech in ${plural(view.conversations.length, "conversation", "conversations")}.`];
  if (view.noise_clips > 0) {
    parts.push(view.noise_clips === 1 ? "1 noise clip was dropped." : `${view.noise_clips} noise clips were dropped.`);
  }
  parts.push(audioSentence(view));
  return parts.join(" ");
}

/** "787 pages are waiting on the pendant and will be added at the next sync.", or null with none waiting. */
export function pendingSentence(pages: number | null): string | null {
  if (!pages) return null;
  return `${pages === 1 ? "1 page is" : `${pages} pages are`} waiting on the pendant and will be added at the next sync.`;
}

export type TranscriptPiece =
  | { kind: "line"; line: Line; starred: boolean }
  | { kind: "star"; at_ms: number }
  | { kind: "gap"; minutes: number };

/** Lines further apart than this get a quiet gap between them. */
export const QUIET_MS = 5 * 60_000;

/**
 * What the transcript draws: the conversation's lines in time order, each star marking the line at or just
 * after it (the quote under a star is that line); a star past the last line keeps its own item at its exact
 * time; and a quiet gap between two lines more than five minutes apart. Every star the server gave the
 * conversation counts, including one pressed just before its first clip began (so before start_ms).
 */
export function transcriptItems(conv: ConversationView): TranscriptPiece[] {
  const lines = [...conv.lines].sort((a, b) => a.at_ms - b.at_ms || a.seq - b.seq);
  const stars = [...conv.star_ms].sort((a, b) => a - b);
  const items: TranscriptPiece[] = [];
  let s = 0;
  let lastAt: number | null = null;
  for (const line of lines) {
    let starred = false;
    while (s < stars.length && stars[s] <= line.at_ms) {
      starred = true;
      s++;
    }
    if (lastAt !== null && line.at_ms - lastAt > QUIET_MS) {
      items.push({ kind: "gap", minutes: Math.round((line.at_ms - lastAt) / 60_000) });
    }
    items.push({ kind: "line", line, starred });
    lastAt = line.at_ms;
  }
  while (s < stars.length) items.push({ kind: "star", at_ms: stars[s++] });
  return items;
}

function audioWords(view: DayView): string {
  if (view.audio_until) return `audio kept until ${dayMonth(view.audio_until)}`;
  if (view.audio_kept_for_good) return "audio kept for good";
  return "audio no longer kept";
}

/** The band's line: "7 conversations · 3 h 1 min of speech · 4 starred moments · audio kept until 22 November". */
export function summaryLine(view: DayView): string {
  const parts = [plural(view.conversations.length, "conversation", "conversations"), `${duration(view.speech_ms)} of speech`];
  if (view.stars.length > 0) parts.push(plural(view.stars.length, "starred moment", "starred moments"));
  parts.push(audioWords(view));
  return parts.join(" · ");
}

/** Where a conversation sits in the list column: before noon, before six, or after. */
export function partOfDay(ms: number): "Morning" | "Afternoon" | "Evening" {
  const h = new Date(ms).getHours();
  return h < 12 ? "Morning" : h < 18 ? "Afternoon" : "Evening";
}

/** The lines around a moment: the line at or just after it (the last line when the moment is past them all)
 *  and up to `n` lines either side, in time order; none when the conversation has no lines. */
export function linesAround(conv: ConversationView, at_ms: number, n = 3): Line[] {
  const lines = [...conv.lines].sort((a, b) => a.at_ms - b.at_ms || a.seq - b.seq);
  if (lines.length === 0) return [];
  let i = lines.findIndex((l) => l.at_ms >= at_ms);
  if (i < 0) i = lines.length - 1;
  return lines.slice(Math.max(0, i - n), i + n + 1);
}
