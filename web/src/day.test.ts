import { expect, test } from "vitest";
import type { ConversationView, DayView, Line } from "./api";
import { partOfDay, pendingSentence, placeStars, summaryLine, summarySentence, transcriptItems } from "./day";

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

const marks = (items: ReturnType<typeof transcriptItems>) =>
  items.map((i) => i.kind === "line" ? `L${(i.line.at_ms - T0) / 1000}${i.starred ? "★" : ""}`
    : i.kind === "star" ? `S${(i.at_ms - T0) / 1000}` : `G${i.minutes}`);

test("transcriptItems marks the line at or just after each star; a star past the last line keeps its own item", () => {
  expect(marks(transcriptItems(conv([line(9, "a", 0), line(13, "b", 1), line(20, "c", 2)], [12, 20])))).toEqual(["L9", "L13★", "L20★"]);
  expect(marks(transcriptItems(conv([line(5, "a"), line(8, "b", 1)], [1])))).toEqual(["L5★", "L8"]);
  expect(marks(transcriptItems(conv([line(5, "a")], [30])))).toEqual(["L5", "S30"]);
  expect(marks(transcriptItems(conv([line(8, "b", 1), line(5, "a", 0)], [])))).toEqual(["L5", "L8"]);
});

test("transcriptItems puts a quiet gap between lines more than five minutes apart", () => {
  const c = conv([line(0, "a", 0), line(400, "b", 1), line(701, "c", 2), line(1001, "d", 3)], [], T0, T0 + 1200_000);
  expect(marks(transcriptItems(c))).toEqual(["L0", "G7", "L400", "G5", "L701", "L1001"]);
});

test("summaryLine counts the day in one line, singulars and missing parts included", () => {
  expect(summaryLine(view({}))).toBe("6 conversations · 3 h 1 min of speech · audio kept until 7 November");
  expect(summaryLine(view({ speech_ms: 16_000, conversations: [conv([], [])], stars: [{ at_ms: T0, conversation_id: "conv_1", quote: null }] })))
    .toBe("1 conversation · 16 s of speech · 1 starred moment · audio kept until 7 November");
  expect(summaryLine(view({ stars: [{ at_ms: T0, conversation_id: null, quote: null }, { at_ms: T0 + 1, conversation_id: null, quote: null }],
    audio_until: null, audio_kept_for_good: true })))
    .toBe("6 conversations · 3 h 1 min of speech · 2 starred moments · audio kept for good");
  expect(summaryLine(view({ audio_until: null }))).toBe("6 conversations · 3 h 1 min of speech · audio no longer kept");
});

test("partOfDay splits the day at noon and six", () => {
  const local = (h: number, m = 0) => new Date(2026, 9, 23, h, m).getTime();
  expect([local(0), local(8, 5), local(11, 59), local(12), local(17, 59), local(18), local(23, 30)].map(partOfDay))
    .toEqual(["Morning", "Morning", "Morning", "Afternoon", "Afternoon", "Evening", "Evening"]);
});
