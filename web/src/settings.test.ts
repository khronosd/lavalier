import { expect, test } from "vitest";
import { minutesToSeconds, secondsToMinutes, validateLocally } from "./settings";

test.each([
  [{ retention_days: 0 }, null],
  [{ retention_days: 21 }, null],
  [{ retention_days: -1 }, "retention_days"],
  [{ retention_days: 1.5 }, "retention_days"],
  [{ retention_days: Number.NaN }, "retention_days"],
  [{ poll_interval_s: 60 }, null],
  [{ poll_interval_s: 59 }, "poll_interval_s"],
  [{ window_size: "1120x720" }, null],
  [{ window_size: "800x600" }, null],
  [{ window_size: "11200x720" }, "window_size"],
  [{ window_size: "1120 x 720" }, "window_size"],
  [{ window_size: "" }, "window_size"],
  [{ appearance: "dark" }, null],
  [{ appearance: "sepia" }, "appearance"],
  [{ drain_pages_threshold: 500 }, null],
  [{ drain_pages_threshold: 2.5 }, "drain_pages_threshold"],
  [{ drain_after_hours: 6 }, null],
  [{ drain_after_hours: Number.NaN }, "drain_after_hours"],
  [{ require_firmware: "" }, null],
  [{ whisper_language: "en" }, null],
  // the server's bounds (src/lavalier/settings.py), mirrored
  [{ retention_days: 36500 }, null],
  [{ retention_days: 36501 }, "retention_days"],
  [{ drain_pages_threshold: 1 }, null],
  [{ drain_pages_threshold: 0 }, "drain_pages_threshold"],
  [{ drain_after_hours: 0 }, null],
  [{ drain_after_hours: -1 }, "drain_after_hours"],
  [{ whisper_language: "yue" }, null],
  [{ whisper_language: "english" }, "whisper_language"],
  [{ whisper_language: "E" }, "whisper_language"],
  [{ whisper_language: "en\n" }, "whisper_language"],
  [{ whisper_language: "" }, "whisper_language"],
  [{ pendant_address: "ABC" }, null],
])("validateLocally %j", (patch, field) => {
  const got = validateLocally(patch as never);
  expect(got ? got.field : null).toBe(field);
  if (got) expect(got.message.length).toBeGreaterThan(8);
});

test("the poll interval is edited in minutes and stored in seconds", () => {
  expect(minutesToSeconds("5")).toBe(300);
  expect(minutesToSeconds("1")).toBe(60);
  expect(minutesToSeconds("0.5")).toBe(30);
  expect(Number.isNaN(minutesToSeconds("soon"))).toBe(true);
  expect(Number.isNaN(minutesToSeconds(""))).toBe(true);
  expect(secondsToMinutes(300)).toBe("5");
  expect(secondsToMinutes(90)).toBe("1.5");
  expect(validateLocally({ poll_interval_s: minutesToSeconds("0.5") })?.message).toBe("The poll interval must be at least 1 minute.");
});
