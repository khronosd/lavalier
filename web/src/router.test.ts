import { expect, test } from "vitest";
import { isCalendarDate, navigate, parseHash, replaceHash, toHash } from "./router";

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
  ["#/day/2026-10-23?at=clip_b-1", { name: "day", params: { date: "2026-10-23" }, query: { at: "clip_b-1" } }],
  ["#/today?at=c-c-20261024-090000", { name: "today", params: {}, query: { at: "c-c-20261024-090000" } }],
  ["#/starred", { name: "starred", params: {}, query: {} }],
  ["#/search?q=retention%20days", { name: "search", params: {}, query: { q: "retention days" } }],
  ["#/insights", { name: "insights", params: {}, query: {} }],
  ["#/settings/retention", { name: "settings", params: { tab: "retention" }, query: {} }],
  ["#/settings/connectors", { name: "settings", params: { tab: "connectors" }, query: {} }],
  ["#/settings/model", { name: "settings", params: { tab: "model" }, query: {} }],
  ["#/settings/nonsense", { name: "settings", params: { tab: "general" }, query: {} }],
  ["#/settings", { name: "settings", params: { tab: "general" }, query: {} }],
  ["#/elsewhere", { name: "today", params: {}, query: {} }],
])("parseHash %s", (hash, expected) => expect(parseHash(hash)).toEqual(expected));

test("toHash round-trips", () => {
  for (const h of ["#/today", "#/today?tab=audio", "#/day/2026-10-24", "#/day/2026-10-24?tab=audio&conv=conv_1",
    "#/day/2026-10-23?at=clip_20261023T225609.000Z-1", "#/day/2026-10-23?tab=transcript&at=c-c-20261023-225600",
    "#/today?at=clip_b-0", "#/starred", "#/search?q=a+b", "#/insights", "#/settings/pendant"]) {
    expect(toHash(parseHash(h))).toBe(h);
  }
});

test("the at key survives toHash and parseHash in both directions", () => {
  const r = { name: "day" as const, params: { date: "2026-10-23" }, query: { at: "clip_x.123Z-4" } };
  expect(parseHash(toHash(r))).toEqual(r);
  expect(toHash({ ...r, query: {} })).toBe("#/day/2026-10-23");
});

test("replaceHash changes the hash without a history entry and tells the router", () => {
  window.location.hash = "#/day/2026-10-23?at=clip_b-1";
  const before = window.history.length;
  let heard = 0;
  const listen = () => { heard += 1; };
  window.addEventListener("hashchange", listen);
  replaceHash("#/day/2026-10-23");
  window.removeEventListener("hashchange", listen);
  expect(window.location.hash).toBe("#/day/2026-10-23");
  expect(window.history.length).toBe(before);
  expect(heard).toBe(1);
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
