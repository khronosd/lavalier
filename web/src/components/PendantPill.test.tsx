import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/preact";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { Status } from "../api";
import { device, status } from "../pendant.fixtures";
import { usePendantStatus } from "../usePendantStatus";
import { PendantPill } from "./PendantPill";

/** The pill as the toolbar mounts it: with the status hook's state. */
function Pill() {
  return <PendantPill pendant={usePendantStatus()} />;
}

const json = (body: unknown, code = 200) =>
  new Response(JSON.stringify(body), { status: code, headers: { "Content-Type": "application/json" } });

const noAddressSync = {
  id: 1, started_ms: 0, ended_ms: 1, outcome: "error", reason: "", pages: 0, messages: 0, capture_id: null,
  muted_by: null, unmute: "n/a", error: "set pendant_address in config.toml",
};

const drained = {
  sync: { outcome: "drained", reason: "", pages: 3, messages: 3, capture: null, capture_complete: true, muted_by: null,
    unmute: "n/a", status: null, charger_signal: "none", error: null, orphans: 0 },
  process: null,
};

/** A fetch that answers GET /api/status with `s`; other routes come from `extra`. */
function server(s: Status, extra: Record<string, () => Promise<Response>> = {}) {
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${url}`;
    if (key === "GET /api/status") return json(s);
    const reply = extra[key];
    if (!reply) throw new Error(`unexpected ${key}`);
    return reply();
  }));
}

const flush = () => act(async () => { await vi.advanceTimersByTimeAsync(0); });

beforeEach(() => {
  vi.useFakeTimers();
  vi.spyOn(document, "hasFocus").mockReturnValue(false); // no live reads: this is about the pill
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test("the pill shows the lamp, the state word and the battery, and names it all for a screen reader", async () => {
  server(status({ device: device({ soc: 82, pages_waiting: 312 }) }));
  render(<Pill />);
  await flush();
  const pill = screen.getByRole("button", { name: "Pendant: listening, battery 82 percent, 312 pages waiting" });
  expect(pill.textContent).toBe("Listening82%");
  expect(pill.querySelector(".lamp")!.classList.contains("lamp-listening")).toBe(true);
  expect(pill.getAttribute("aria-expanded")).toBe("false");
  expect(pill.getAttribute("aria-busy")).toBeNull();
  expect(screen.queryByRole("dialog")).toBeNull();
});

test("the pill opens the pendant card as a popover; Escape and a click outside close it", async () => {
  server(status());
  render(<Pill />);
  await flush();
  const pill = screen.getByRole("button", { name: /^Pendant:/ });
  fireEvent.click(pill);
  const dialog = screen.getByRole("dialog", { name: "Pendant" });
  expect(within(dialog).getByRole("button", { name: "Sync now" })).toBeTruthy();
  expect(within(dialog).getByText("Battery 94%")).toBeTruthy();
  expect(pill.getAttribute("aria-expanded")).toBe("true");
  fireEvent.keyDown(document, { key: "Escape" });
  expect(screen.queryByRole("dialog")).toBeNull();
  fireEvent.click(pill);
  expect(screen.getByRole("dialog", { name: "Pendant" })).toBeTruthy();
  fireEvent.click(document.querySelector(".scrim")!);
  expect(screen.queryByRole("dialog")).toBeNull();
});

test("with no address the pill says Not set with an outline lamp, and the card says where to set it", async () => {
  server(status({ device: null, last_sync: noAddressSync }));
  render(<Pill />);
  await flush();
  const pill = screen.getByRole("button", { name: "Pendant: not set" });
  expect(pill.textContent).toBe("Not set");
  expect(pill.querySelector(".lamp")!.classList.contains("lamp-unknown")).toBe(true);
  fireEvent.click(pill);
  expect(screen.getByText("No pendant address set. Add it in Settings › Pendant.")).toBeTruthy();
});

test("while a sync runs the word is Syncing… and the pill is busy; the word comes back with the result", async () => {
  let release!: () => void;
  server(status(), {
    "POST /api/sync": () => new Promise<Response>((resolve) => { release = () => resolve(json(drained)); }),
  });
  render(<Pill />);
  await flush();
  fireEvent.click(screen.getByRole("button", { name: /^Pendant:/ }));
  fireEvent.click(screen.getByRole("button", { name: "Sync now" }));
  await flush();
  const busy = screen.getByRole("button", { name: "Pendant: syncing…, battery 94 percent, 787 pages waiting" });
  expect(busy.getAttribute("aria-busy")).toBe("true");
  expect(busy.textContent).toContain("Syncing…");
  release();
  await flush();
  await flush();
  expect(screen.getByRole("button", { name: /^Pendant: listening/ }).getAttribute("aria-busy")).toBeNull();
  expect(screen.getByText("Drained 3 pages")).toBeTruthy();
});

test("an unmute still pending shows as a dot after the word", async () => {
  server(status({ unmute_pending_since_ms: new Date(2026, 9, 23, 9, 5).getTime() }));
  render(<Pill />);
  await flush();
  const pill = screen.getByRole("button", { name: /^Pendant:/ });
  expect(pill.querySelector(".pill-pending")).toBeTruthy();
});
