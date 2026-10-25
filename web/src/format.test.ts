import { expect, test } from "vitest";
import { age, bytes, clock, dayTitle, duration, hm, hms, isoDay, monthName } from "./format";

test.each([
  [16_000, "16 s"],
  [16 * 60_000, "16 min"],
  [3 * 3_600_000 + 60_000, "3 h 1 min"],
  [2 * 3_600_000, "2 h"],
  [0, "0 s"],
])("duration %i", (ms, s) => expect(duration(ms)).toBe(s));

// the brief's example pairs 2026-10-24 with Friday; that date is a Saturday (2025-10-24 was the Friday)
test("dayTitle", () => expect(dayTitle("2025-10-24")).toBe("Friday, 24 October"));
test("dayTitle 2026-10-24", () => expect(dayTitle("2026-10-24")).toBe("Saturday, 24 October"));
test("dayTitle on another day", () => expect(dayTitle("2026-01-01")).toBe("Thursday, 1 January"));

test.each([
  [20, "just now"],
  [130, "as of 2 min ago"],
  [7200, "as of 2 h ago"],
])("age %i", (s, t) => expect(age(s)).toBe(t));

test("hms and hm give the local wall-clock time of an epoch ms", () => {
  const ms = new Date(2026, 9, 23, 22, 56, 7).getTime();
  expect(hms(ms)).toBe("22:56:07");
  expect(hm(ms)).toBe("22:56");
  expect(hm(new Date(2026, 9, 23, 7, 5, 0).getTime())).toBe("07:05");
});

test("isoDay is the local date", () => {
  expect(isoDay(new Date(2026, 9, 24, 0, 30).getTime())).toBe("2026-10-24");
  expect(isoDay(new Date(2026, 0, 5, 23, 59).getTime())).toBe("2026-01-05");
});

test("monthName names the month, with the year only when it is not this year", () => {
  expect(monthName("2026-10-23", "2026-10-24")).toBe("October");
  expect(monthName("2026-01-02", "2026-10-24")).toBe("January");
  expect(monthName("2025-12-31", "2026-10-24")).toBe("December 2025");
});

test("clock shows seconds as minutes and seconds, and nothing finite as 0:00", () => {
  expect([0, 7, 59.9, 60, 252.4, 3599, Number.NaN, Number.POSITIVE_INFINITY].map(clock))
    .toEqual(["0:00", "0:07", "0:59", "1:00", "4:12", "59:59", "0:00", "0:00"]);
});

test("bytes rounds to the unit that fits", () => {
  expect([0, 512, 12_288, 340 * 1024 * 1024, 1_234_567_890, 12 * 1024 ** 3].map(bytes))
    .toEqual(["0 kB", "1 kB", "12 kB", "340 MB", "1.1 GB", "12 GB"]);
});
