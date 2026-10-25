import { expect, test } from "vitest";
import { seedOf, waveBars } from "./wave";

test("waveBars gives n heights within the range, the same for the same seed", () => {
  const bars = waveBars(2);
  expect(bars).toHaveLength(14);
  expect(bars.every((h) => Number.isInteger(h) && h >= 3 && h <= 16)).toBe(true);
  expect(waveBars(2)).toEqual(bars);
  expect(waveBars(3)).not.toEqual(bars);
  expect(waveBars(9, 30, 4, 24)).toHaveLength(30);
  expect(waveBars(9, 30, 4, 24).every((h) => h >= 4 && h <= 24)).toBe(true);
});

test("seedOf is a small stable number from an id", () => {
  expect(seedOf("c-20261023-091200")).toBe(seedOf("c-20261023-091200"));
  expect(seedOf("c-20261023-091200")).not.toBe(seedOf("c-20261023-113000"));
  expect(seedOf("")).toBe(0);
  expect(seedOf("anything at all")).toBeLessThan(1000);
});
