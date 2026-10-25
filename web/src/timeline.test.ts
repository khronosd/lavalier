import { expect, test } from "vitest";
import type { ConversationView, DayView, StarView } from "./api";
import { blocks, hourTicks, starDots, timelineRange } from "./timeline";

const at = (h: number, m = 0, d = 23) => new Date(2026, 9, d, h, m).getTime();
const conv = (id: string, start: number, end: number, over: Partial<ConversationView> = {}): ConversationView => ({
  conversation_id: id, start_ms: start, end_ms: end, speech_ms: Math.round((end - start) / 2), star_ms: [], pinned: false,
  label: null, clip_ids: [], lines: [], audio_available: true, ...over,
});
const view = (conversations: ConversationView[], stars: StarView[] = []): DayView => ({
  day: "2026-10-23", speech_ms: 0, conversations, stars, noise_clips: 0, audio_until: null, audio_kept_for_good: false,
  pending_pages: null,
});
const RANGE = { start_ms: at(8), end_ms: at(19) }; // 11 hours

test("the range runs from the first hour to the end of the last, at least six hours, 8 to 20 when empty", () => {
  expect(timelineRange(view([conv("a", at(8, 5), at(8, 22)), conv("b", at(18, 40), at(18, 52))]))).toEqual(RANGE);
  expect(timelineRange(view([conv("a", at(9, 12), at(9, 41))]))).toEqual({ start_ms: at(9), end_ms: at(15) });
  expect(timelineRange(view([conv("a", at(18), at(19))]))).toEqual({ start_ms: at(18), end_ms: at(24) });
  expect(timelineRange(view([]))).toEqual({ start_ms: at(8), end_ms: at(20) });
});

test("the range stays inside the day: a late or midnight-spanning conversation pushes it back, never past midnight", () => {
  expect(timelineRange(view([conv("a", at(20, 30), at(21, 10))]))).toEqual({ start_ms: at(18), end_ms: at(24) });
  expect(timelineRange(view([conv("a", at(23, 30), at(0, 40, 24))]))).toEqual({ start_ms: at(18), end_ms: at(24) });
  expect(timelineRange(view([conv("a", at(23, 30, 22), at(0, 40))]))).toEqual({ start_ms: at(0), end_ms: at(6) });
});

test("hour ticks every hour, labelled every second hour when labels would be closer than 56 px", () => {
  const ticks = hourTicks(RANGE, 1100);
  expect(ticks).toHaveLength(12);
  expect(ticks[0]).toEqual({ ms: at(8), left: 0, label: "8:00" });
  expect(ticks[1].left).toBeCloseTo(100 / 11);
  expect(ticks[11]).toEqual({ ms: at(19), left: 100, label: "19:00" });
  expect(hourTicks(RANGE, 500).map((t) => t.label))
    .toEqual(["8:00", null, "10:00", null, "12:00", null, "14:00", null, "16:00", null, "18:00", null]);
  expect(hourTicks(RANGE, 0).every((t) => t.label !== null)).toBe(true); // an unmeasured band is taken as 1000 px
  expect(hourTicks({ start_ms: at(23), end_ms: at(24) }, 1000).map((t) => t.label)).toEqual(["23:00", "0:00"]);
});

test("blocks sit by their times, no narrower than 6 px, 26 to 52 px tall by speech density", () => {
  const v = view([
    conv("a", at(8, 5), at(8, 22)),
    conv("b", at(9), at(9, 1)),
    conv("c", at(10), at(11), { speech_ms: 0 }),
    conv("d", at(12), at(13), { speech_ms: 2 * 3_600_000 }),
  ]);
  const [a, b, c, d] = blocks(v, RANGE, null, 1100); // 100 px per hour
  expect(a.left).toBeCloseTo((5 / 660) * 100);
  expect(a.width).toBeCloseTo((17 / 660) * 100);
  expect(a.height).toBe(39);
  expect(b.width).toBeCloseTo((6 / 1100) * 100);
  expect(c.height).toBe(26);
  expect(d.height).toBe(52);
  expect([a, b, c, d].every((x) => !x.selected)).toBe(true);
  expect(blocks(v, RANGE, "c", 1100).map((x) => x.selected)).toEqual([false, false, true, false]);
});

test("a block's label is the calendar label, else the range; one within 90 px of the last drawn label is dropped", () => {
  const v = view([
    conv("a", at(8, 5), at(8, 22), { label: "Coffee with Dana" }),
    conv("b", at(8, 30), at(8, 50)),
    conv("c", at(11, 30), at(11, 52)),
  ]);
  const out = blocks(v, RANGE, null, 1100);
  expect(out.map((x) => x.name)).toEqual(["Coffee with Dana", "08:30 to 08:50", "11:30 to 11:52"]);
  expect(out.map((x) => x.range)).toEqual(["08:05 to 08:22", "08:30 to 08:50", "11:30 to 11:52"]);
  expect(out.map((x) => x.labelShown)).toEqual([true, false, true]);
  expect(out[0].centre).toBeCloseTo((13.5 / 660) * 100);
  // the first label is always drawn; thinning compares with the last one drawn, not the last block
  const tight = view([conv("a", at(8), at(8, 10)), conv("b", at(8, 20), at(8, 30)), conv("c", at(8, 40), at(8, 50)), conv("d", at(9, 30), at(9, 40))]);
  expect(blocks(tight, RANGE, null, 1100).map((x) => x.labelShown)).toEqual([true, false, false, true]);
});

test("blocks are clamped to the range, and a conversation of the next day draws nothing", () => {
  const v = view([conv("a", at(23, 30), at(0, 40, 24)), conv("b", at(0, 10, 24), at(0, 30, 24))]);
  const range = timelineRange(v);
  const out = blocks(v, range, null, 1200); // 6 hours, 200 px per hour
  expect(out).toHaveLength(1);
  expect(out[0].left).toBeCloseTo((5.5 / 6) * 100);
  expect(out[0].width).toBeCloseTo((0.5 / 6) * 100);
});

test("star dots are percentages along the range; stars outside it are left out", () => {
  const stars: StarView[] = [
    { at_ms: at(9, 14), conversation_id: null, quote: null },
    { at_ms: at(13, 25), conversation_id: null, quote: null },
    { at_ms: at(23), conversation_id: null, quote: null },
  ];
  const dots = starDots(view([], stars), RANGE);
  expect(dots).toHaveLength(2);
  expect(dots[0]).toBeCloseTo((74 / 660) * 100);
  expect(dots[1]).toBeCloseTo((325 / 660) * 100);
});
