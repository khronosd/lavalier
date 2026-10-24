import { expect, test } from "vitest";
import type { ConversationView, DayView, Line } from "./api";
import { pendingSentence, placeStars, summarySentence } from "./day";

const T0 = Date.UTC(2026, 9, 23, 20, 56, 0);
const line = (offsetS: number, text: string, seq = 0): Line => ({ at_ms: T0 + offsetS * 1000, text, clip_id: "clip_a", seq });

function conv(lines: Line[], stars: number[], start = T0, end = T0 + 60_000): ConversationView {
  return {
    conversation_id: "conv_1", start_ms: start, end_ms: end, speech_ms: end - start, star_ms: stars.map((s) => T0 + s * 1000),
    pinned: false, label: null, clip_ids: ["clip_a"], lines, audio_available: true,
  };
}

const kinds = (items: ReturnType<typeof placeStars>) =>
  items.map((i) => (i.kind === "line" ? `L${(i.line.at_ms - T0) / 1000}` : `S${(i.at_ms - T0) / 1000}`));

test("placeStars interleaves stars inside the span at their times, a star before an equal-time line", () => {
  const c = conv([line(9, "a", 0), line(13, "b", 1), line(20, "c", 2)], [12, 20]);
  expect(kinds(placeStars(c))).toEqual(["L9", "S12", "L13", "S20", "L20"]);
});

test("placeStars puts a star before the first line first", () => {
  const c = conv([line(5, "a"), line(8, "b", 1)], [1]);
  expect(kinds(placeStars(c))).toEqual(["S1", "L5", "L8"]);
});

test("placeStars drops stars outside the conversation's span and sorts the rest", () => {
  const c = conv([line(5, "a")], [70, 30, -10, 2], T0, T0 + 60_000);
  expect(kinds(placeStars(c))).toEqual(["S2", "L5", "S30"]);
});

test("placeStars with no stars is the lines in time order", () => {
  const c = conv([line(8, "b", 1), line(5, "a", 0)], []);
  expect(kinds(placeStars(c))).toEqual(["L5", "L8"]);
});

function view(over: Partial<DayView>): DayView {
  return {
    day: "2026-10-23", speech_ms: (3 * 60 + 1) * 60_000, conversations: Array.from({ length: 6 }, () => conv([], [])),
    stars: [], noise_clips: 75, audio_until: "2026-11-07", audio_kept_for_good: false, pending_pages: null, ...over,
  };
}

test.each([
  [{}, "3 h 1 min of speech in 6 conversations. 75 noise clips were dropped. The audio is kept until 7 November."],
  [{ audio_kept_for_good: true }, "3 h 1 min of speech in 6 conversations. 75 noise clips were dropped. The audio is kept until 7 November."],
  [{ audio_until: null, audio_kept_for_good: true }, "3 h 1 min of speech in 6 conversations. 75 noise clips were dropped. The audio is kept for good."],
  [{ audio_until: null }, "3 h 1 min of speech in 6 conversations. 75 noise clips were dropped. The audio is no longer kept."],
])("summarySentence, audio state %o", (over, expected) => expect(summarySentence(view(over))).toBe(expected));

test("summarySentence uses singular forms and leaves out zero noise", () => {
  expect(summarySentence(view({ speech_ms: 16_000, conversations: [conv([], [])], noise_clips: 1 })))
    .toBe("16 s of speech in 1 conversation. 1 noise clip was dropped. The audio is kept until 7 November.");
  expect(summarySentence(view({ noise_clips: 0 })))
    .toBe("3 h 1 min of speech in 6 conversations. The audio is kept until 7 November.");
});

test("pendingSentence says how many pages wait on the pendant", () => {
  expect(pendingSentence(787)).toBe("787 pages are waiting on the pendant and will be added at the next sync.");
  expect(pendingSentence(1)).toBe("1 page is waiting on the pendant and will be added at the next sync.");
  expect(pendingSentence(0)).toBeNull();
  expect(pendingSentence(null)).toBeNull();
});
