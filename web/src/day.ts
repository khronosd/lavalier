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
