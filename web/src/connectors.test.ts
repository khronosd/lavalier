import { expect, test } from "vitest";
import { exportResultLine, exportRowState, normaliseNotionId, toggleCalendar } from "./connectors";

const HEX = "0123456789abcdef0123456789abcdef";

test("normaliseNotionId takes an empty value, 32 hex, a dashed uuid and a notion.so URL", () => {
  expect(normaliseNotionId("")).toBe("");
  expect(normaliseNotionId("   ")).toBe("");
  expect(normaliseNotionId(` ${HEX.toUpperCase()} `)).toBe(HEX);
  expect(normaliseNotionId("01234567-89AB-cdef-0123-456789abcdef")).toBe(HEX);
  expect(normaliseNotionId(`https://www.notion.so/team/Journal-${HEX}?v=ffff`)).toBe(HEX);
  expect(normaliseNotionId(`https://notion.so/${HEX.toUpperCase()}`)).toBe(HEX);
});

test("normaliseNotionId refuses anything else, as the server does", () => {
  expect(normaliseNotionId("journal")).toBeNull();
  expect(normaliseNotionId(HEX.slice(1))).toBeNull();
  expect(normaliseNotionId(`https://example.com/${HEX}`)).toBeNull();
  expect(normaliseNotionId(`ftp://notion.so/${HEX}`)).toBeNull();
  expect(normaliseNotionId(`https://www.notion.so/Journal${HEX}`)).toBeNull(); // the id must stand alone or after a dash
  expect(normaliseNotionId(`https://www.notion.so/${HEX}/view`)).toBeNull(); // the last segment counts
});

test("exportResultLine counts the days, then says which stopped and which failed", () => {
  const none = { done: 0, unchanged: 0, stopped: [], errors: [], days: [] };
  expect(exportResultLine({ ...none, done: 5, unchanged: 1, stopped: ["2026-10-20"] }))
    .toBe("Exported 5 days, 1 unchanged; 1 stopped: 20 October was edited by hand");
  expect(exportResultLine({ ...none, done: 1 })).toBe("Exported 1 day");
  expect(exportResultLine({ ...none, unchanged: 3 })).toBe("Exported 0 days, 3 unchanged");
  expect(exportResultLine(none)).toBe("No days with speech to export");
  expect(exportResultLine({ ...none, done: 2, stopped: ["2026-10-20", "2026-10-21"],
    errors: [{ day: "2026-10-22", error: "Notion refused the token" }, { day: "2026-10-23", error: null }] }))
    .toBe("Exported 2 days; 2 stopped: 20 October and 21 October were edited by hand; " +
      "2 failed: 22 October (Notion refused the token), 23 October");
});

test("exportResultLine says when an export was stopped part way and how many days did not go", () => {
  const none = { done: 0, unchanged: 0, stopped: [], errors: [], days: [] };
  expect(exportResultLine({ ...none, done: 1, not_sent: ["2026-10-21", "2026-10-22"],
    interrupted: "stopped: the connector was turned off" }))
    .toBe("Exported 1 day; Stopped: the connector was turned off (2 days not sent)");
  expect(exportResultLine({ ...none, not_sent: ["2026-10-21"], interrupted: "stopped: the connector was turned off" }))
    .toBe("Stopped: the connector was turned off (1 day not sent)");
  expect(exportResultLine({ ...none, done: 1, not_sent: [], interrupted: null })).toBe("Exported 1 day");
});

test("an export row says when it was exported, or why not", () => {
  const at = new Date(2026, 9, 23, 14, 2).getTime();
  const row = { day: "2026-10-23", connector: "notion", page_id: "p", block_id: "b", content_hash: "h",
    exported_ms: at, state: "done" as const, error: null };
  expect(exportRowState(row)).toBe("exported 14:02");
  expect(exportRowState({ ...row, state: "stopped", error: "edited by hand" })).toBe("stopped: edited by hand");
  expect(exportRowState({ ...row, state: "error", error: "rate limited" })).toBe("error: rate limited");
});

test("toggleCalendar keeps the list comma-separated and keeps ids it does not show", () => {
  expect(toggleCalendar("", "work", true)).toBe("work");
  expect(toggleCalendar("work", "home", true)).toBe("work,home");
  expect(toggleCalendar("gone, work,\nhome", "work", false)).toBe("gone,home");
  expect(toggleCalendar("work", "work", true)).toBe("work");
  expect(toggleCalendar("work", "work", false)).toBe("");
});
