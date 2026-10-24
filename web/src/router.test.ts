import { expect, test } from "vitest";
import { isCalendarDate, navigate, parseHash, toHash } from "./router";

test.each([
  ["", { name: "today", params: {}, query: {} }],
  ["#/today", { name: "today", params: {}, query: {} }],
  ["#/day/2026-10-24", { name: "day", params: { date: "2026-10-24" }, query: {} }],
  ["#/day/nonsense", { name: "today", params: {}, query: {} }],
  ["#/day/9999-99-99", { name: "today", params: {}, query: {} }],
  ["#/day/2026-02-30", { name: "today", params: {}, query: {} }],
  ["#/day/%E0%A4%A", { name: "today", params: {}, query: {} }],
  ["#/settings/%E0%A4%A", { name: "today", params: {}, query: {} }],
  ["#/day/2026-10-23?tab=audio&conv=conv_1", { name: "day", params: { date: "2026-10-23" }, query: { tab: "audio", conv: "conv_1" } }],
  ["#/day/2026-10-23?tab=insights&other=x", { name: "day", params: { date: "2026-10-23" }, query: { tab: "insights" } }],
  ["#/today?tab=audio", { name: "today", params: {}, query: { tab: "audio" } }],
  ["#/starred", { name: "starred", params: {}, query: {} }],
  ["#/search?q=retention%20days", { name: "search", params: {}, query: { q: "retention days" } }],
  ["#/insights", { name: "insights", params: {}, query: {} }],
  ["#/settings/retention", { name: "settings", params: { tab: "retention" }, query: {} }],
  ["#/settings", { name: "settings", params: { tab: "general" }, query: {} }],
  ["#/elsewhere", { name: "today", params: {}, query: {} }],
])("parseHash %s", (hash, expected) => expect(parseHash(hash)).toEqual(expected));

test("toHash round-trips", () => {
  for (const h of ["#/today", "#/today?tab=audio", "#/day/2026-10-24", "#/day/2026-10-24?tab=audio&conv=conv_1", "#/starred", "#/search?q=a+b", "#/insights", "#/settings/pendant"]) {
    expect(toHash(parseHash(h))).toBe(h);
  }
});

test("navigate sets the location hash", () => {
  navigate({ name: "day", params: { date: "2026-10-23" }, query: {} });
  expect(window.location.hash).toBe("#/day/2026-10-23");
  navigate("#/starred");
  expect(window.location.hash).toBe("#/starred");
});

test.each([
  ["2026-10-24", true],
  ["2024-02-29", true],
  ["2026-02-29", false],
  ["9999-99-99", false],
  ["2026-13-01", false],
  ["2026-10-00", false],
  ["2026-1-01", false],
])("isCalendarDate %s", (text, ok) => expect(isCalendarDate(text)).toBe(ok));
