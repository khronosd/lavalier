import { expect, test } from "vitest";
import { ApiError, type SyncReportJson } from "./api";
import { device, status } from "./pendant.fixtures";
import {
  batteryLine, buttonsDisabled, isNoAddress, lampState, pagesSentence, pagesShort, pendingUnmuteLine, pillLabel, pillWord,
  requestErrorLine, shouldRefresh, stateText, syncResultLine, toggleResultLine,
} from "./pendant";

const run = (outcome: string) => ({
  id: 1, started_ms: 0, ended_ms: 1, outcome, reason: "", pages: 0, messages: 0, capture_id: null,
  muted_by: null, unmute: "n/a", error: null,
});

const report = (over: Partial<SyncReportJson>): SyncReportJson => ({
  outcome: "skipped", reason: "nothing to do", pages: 0, messages: 0, capture: null, capture_complete: true,
  muted_by: null, unmute: "n/a", status: null, charger_signal: "none", error: null, orphans: 0, ...over,
});

test("the lamp follows only the latest full read", () => {
  expect(lampState(null)).toBe("unknown");
  expect(lampState(status({ device: null }))).toBe("unknown");
  expect(lampState(status())).toBe("listening");
  expect(lampState(status({ device: device({ recording_state: "RECORDING" }) }))).toBe("recording");
  expect(lampState(status({ device: device({ recording_state: "NOT_RECORDING" }) }))).toBe("muted");
  // a partial read decodes as NOT_RECORDING and proves nothing
  expect(lampState(status({ device: device({ has_all_fields: false, recording_state: "NOT_RECORDING" }) }))).toBe("unknown");
  expect(lampState(status({ device: device({ recording_state: "SOMETHING_NEW" }) }))).toBe("unknown");
  expect(["listening", "recording", "muted", "unknown"].map((s) => stateText(s as never)))
    .toEqual(["Listening", "Recording", "Muted", "No reading yet"]);
});

test("the buttons are disabled while the app is busy or a request is in flight", () => {
  expect(buttonsDisabled(null, false)).toBe(true);
  expect(buttonsDisabled(status(), false)).toBe(false);
  expect(buttonsDisabled(status({ busy: true }), false)).toBe(true);
  expect(buttonsDisabled(status(), true)).toBe(true);
});

test("the live read runs only when the window is in front, not busy, and the pendant was last in range", () => {
  const seen = { visible: true, focused: true, busy: false };
  expect(shouldRefresh(status(), { ...seen, visible: false })).toBe(false); // hidden
  expect(shouldRefresh(status(), { ...seen, focused: false })).toBe(false); // visible behind another window
  expect(shouldRefresh(status(), { ...seen, busy: true })).toBe(false);
  expect(shouldRefresh(status({ last_sync: run("not-in-range") }), seen)).toBe(false);
  expect(shouldRefresh(status({ last_sync: run("drained") }), seen)).toBe(true);
  expect(shouldRefresh(status(), seen)).toBe(true);
  expect(shouldRefresh(null, seen)).toBe(true);
});

test("pages waiting in words, at 1.5 s of speech a page", () => {
  expect(pagesSentence(787)).toBe("787 pages waiting, about 20 minutes of speech");
  expect(pagesSentence(40)).toBe("40 pages waiting, about 1 minute of speech");
  expect(pagesSentence(1)).toBe("1 page waiting");
  expect(pagesSentence(0)).toBe("");
});

test("the battery line carries the charger signal in plain words", () => {
  expect(batteryLine(device({ charger_signal: "current" }))).toBe("Battery 94%, charging");
  expect(batteryLine(device({ charger_signal: "usb-cdc" }))).toBe("Battery 94%, on the charger");
  expect(batteryLine(device({ charger_signal: "quiet-polls" }))).toBe("Battery 94%, near the Mac");
  expect(batteryLine(device({ charger_signal: "none" }))).toBe("Battery 94%");
});

test("a sync result in one line", () => {
  const sync = (over: Partial<SyncReportJson>) => syncResultLine({ sync: report(over), process: null });
  expect(sync({ outcome: "drained", pages: 1021 })).toBe("Drained 1021 pages");
  expect(sync({ outcome: "drained", pages: 1 })).toBe("Drained 1 page");
  expect(sync({ outcome: "drained", pages: 0 })).toBe("Nothing to drain");
  expect(sync({ outcome: "skipped" })).toBe("Nothing to drain");
  expect(sync({ outcome: "not-in-range", reason: "not advertising" })).toBe("Pendant not in range");
  expect(sync({ outcome: "locked", reason: "pid 4242" })).toBe("Another process is using the pendant");
  expect(sync({ outcome: "error", error: "link dropped" })).toBe("link dropped");
  expect(sync({ outcome: "refused", reason: "firmware 1.1.20 is not 1.1.3" })).toBe("firmware 1.1.20 is not 1.1.3");
});

test("a mute or unmute result in one line", () => {
  expect(toggleResultLine({ ok: true, state: "NOT_RECORDING", error: null })).toBe("Muted");
  expect(toggleResultLine({ ok: true, state: "LISTENING", error: null })).toBe("Listening");
  expect(toggleResultLine({ ok: true, state: "RECORDING", error: null })).toBe("Recording");
  expect(toggleResultLine({ ok: false, state: null, error: "Pendant not in range" })).toBe("Pendant not in range");
});

test("a refused request says what to do", () => {
  expect(requestErrorLine(new ApiError(409, "busy"))).toBe("The pendant is busy, try again in a moment");
  expect(requestErrorLine(new ApiError(503, "stopping"))).toBe("The app is stopping");
  expect(requestErrorLine(new ApiError(504, "timeout"))).toBe("The pendant took too long to answer");
  expect(requestErrorLine(new ApiError(500, "boom"))).toBe("boom");
  expect(requestErrorLine(new TypeError("Failed to fetch"))).toBe("Failed to fetch");
});

test("the missing pendant address is recognised wherever the app reports it", () => {
  expect(isNoAddress("set pendant_address in config.toml")).toBe(true);
  expect(isNoAddress("Pendant not in range")).toBe(false);
  expect(isNoAddress(null)).toBe(false);
});

test("a pending unmute is named with its time", () => {
  expect(pendingUnmuteLine(status())).toBe("");
  const since = new Date(2026, 9, 24, 9, 5).getTime();
  expect(pendingUnmuteLine(status({ unmute_pending_since_ms: since })))
    .toBe("Unmute pending since 09:05, hold the button or press Unmute");
});

test("the pill's word follows the lamp, the address and the action in flight", () => {
  expect(pillWord("listening", false, null)).toBe("Listening");
  expect(pillWord("recording", false, null)).toBe("Recording");
  expect(pillWord("muted", false, null)).toBe("Muted");
  expect(pillWord("unknown", false, null)).toBe("No reading yet");
  expect(pillWord("unknown", true, null)).toBe("Not set");
  expect(pillWord("listening", false, "sync")).toBe("Syncing…");
  expect(pillWord("listening", false, "mute")).toBe("Muting…");
  expect(pillWord("muted", false, "unmute")).toBe("Unmuting…");
});

test("the pill's label says the lamp, the battery and the pages in one breath", () => {
  expect(pillLabel(status(), false, null)).toBe("Pendant: listening, battery 94 percent, 787 pages waiting");
  expect(pillLabel(status({ device: device({ pages_waiting: 0 }) }), false, null)).toBe("Pendant: listening, battery 94 percent");
  expect(pillLabel(status({ device: device({ pages_waiting: 1 }) }), false, null)).toBe("Pendant: listening, battery 94 percent, 1 page waiting");
  expect(pillLabel(status({ device: device({ pages_waiting: 12_345 }) }), false, null)).toBe("Pendant: listening, battery 94 percent, 12k pages waiting");
  expect(pillLabel(status({ device: null }), false, null)).toBe("Pendant: no reading yet");
  expect(pillLabel(status({ device: null }), true, null)).toBe("Pendant: not set");
  expect(pillLabel(status(), false, "sync")).toBe("Pendant: syncing…, battery 94 percent, 787 pages waiting");
});

test("pages in the pill are short above 9,999", () => {
  expect(pagesShort(0)).toBe("");
  expect(pagesShort(1)).toBe("1 page");
  expect(pagesShort(787)).toBe("787 pages");
  expect(pagesShort(9999)).toBe("9999 pages");
  expect(pagesShort(10_000)).toBe("10k pages");
  expect(pagesShort(15_400)).toBe("15k pages");
});
