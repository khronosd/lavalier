import { expect, test } from "vitest";
import { navigate, parseHash, toHash } from "./router";

test.each([
  ["", { name: "today", params: {}, query: {} }],
  ["#/today", { name: "today", params: {}, query: {} }],
  ["#/day/2026-10-24", { name: "day", params: { date: "2026-10-24" }, query: {} }],
  ["#/day/nonsense", { name: "today", params: {}, query: {} }],
  ["#/starred", { name: "starred", params: {}, query: {} }],
  ["#/search?q=retention%20days", { name: "search", params: {}, query: { q: "retention days" } }],
  ["#/insights", { name: "insights", params: {}, query: {} }],
  ["#/settings/retention", { name: "settings", params: { tab: "retention" }, query: {} }],
  ["#/settings", { name: "settings", params: { tab: "general" }, query: {} }],
  ["#/elsewhere", { name: "today", params: {}, query: {} }],
])("parseHash %s", (hash, expected) => expect(parseHash(hash)).toEqual(expected));

test("toHash round-trips", () => {
  for (const h of ["#/today", "#/day/2026-10-24", "#/starred", "#/search?q=a+b", "#/insights", "#/settings/pendant"]) {
    expect(toHash(parseHash(h))).toBe(h);
  }
});

test("navigate sets the location hash", () => {
  navigate({ name: "day", params: { date: "2026-10-23" }, query: {} });
  expect(window.location.hash).toBe("#/day/2026-10-23");
  navigate("#/starred");
  expect(window.location.hash).toBe("#/starred");
});
