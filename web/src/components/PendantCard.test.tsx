import { act, cleanup, fireEvent, render, screen } from "@testing-library/preact";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { Status } from "../api";
import { device, status } from "../pendant.fixtures";
import { usePendantStatus } from "../usePendantStatus";
import { PendantCard } from "./PendantCard";

/** The card as the shell mounts it: with the status hook's state. */
function Card() {
  return <PendantCard pendant={usePendantStatus()} />;
}

const json = (body: unknown, code = 200) =>
  new Response(JSON.stringify(body), { status: code, headers: { "Content-Type": "application/json" } });

const summaryOf = (s: Status) => {
  const { busy: _b, next_poll_ms: _n, app: _a, ...rest } = s;
  return rest;
};

type Handler = (method: string, url: string) => Response;

/** A fetch that answers by route and records every call as "METHOD /path". */
function server(routes: Record<string, Response | (() => Response)>): { calls: string[]; handler: Handler } {
  const calls: string[] = [];
  const handler: Handler = (method, url) => {
    const key = `${method} ${url}`;
    calls.push(key);
    const r = routes[key];
    if (!r) throw new Error(`unexpected ${key}`);
    return typeof r === "function" ? r() : r.clone();
  };
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => handler(init?.method ?? "GET", url)));
  return { calls, handler };
}

const flush = () => act(async () => { await vi.advanceTimersByTimeAsync(0); });

let visibility: DocumentVisibilityState = "visible";
let focused = true;
beforeEach(() => {
  vi.useFakeTimers();
  visibility = "visible";
  focused = true;
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => visibility });
  vi.spyOn(document, "hasFocus").mockImplementation(() => focused);
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test("with no reading yet, the lamp is a grey outline and only Sync now is offered", async () => {
  const s = status({ device: null });
  server({ "GET /api/status": json(s), "POST /api/status-live": json({ ok: false, error: "Pendant not in range", summary: summaryOf(s) }) });
  const { container } = render(<Card />);
  await flush();
  expect(screen.getByText("No reading yet")).toBeTruthy();
  expect(container.querySelector(".lamp")!.classList.contains("lamp-unknown")).toBe(true);
  expect(screen.getByRole("button", { name: "Sync now" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Mute" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Unmute" })).toBeNull();
  expect(screen.getByText("Pendant not in range")).toBeTruthy();
});

test("listening: the lit lamp, age, battery, pages waiting and Mute", async () => {
  const s = status({ device: device({ charger_signal: "current", age_s: 125 }) });
  server({ "GET /api/status": json(s), "POST /api/status-live": json({ ok: true, error: null, summary: summaryOf(s) }) });
  const { container } = render(<Card />);
  await flush();
  expect(container.querySelector(".pendant")!.getAttribute("aria-label")).toBe("Pendant status");
  expect(screen.getByText("Listening")).toBeTruthy();
  expect(container.querySelector(".lamp")!.classList.contains("lamp-listening")).toBe(true);
  expect(screen.getByText("as of 2 min ago")).toBeTruthy();
  expect(screen.getByText("Battery 94%, charging")).toBeTruthy();
  expect(screen.getByText("787 pages waiting, about 20 minutes of speech")).toBeTruthy();
  expect((screen.getByRole("button", { name: "Mute" }) as HTMLButtonElement).disabled).toBe(false);
  expect(screen.queryByRole("button", { name: "Unmute" })).toBeNull();
});

test("recording lights the lamp with a ring", async () => {
  const s = status({ device: device({ recording_state: "RECORDING" }) });
  server({ "GET /api/status": json(s), "POST /api/status-live": json({ ok: true, error: null, summary: summaryOf(s) }) });
  const { container } = render(<Card />);
  await flush();
  expect(screen.getByText("Recording")).toBeTruthy();
  expect(container.querySelector(".lamp")!.classList.contains("lamp-recording")).toBe(true);
});

test("muted: a dark lamp, Unmute, the pending unmute, and Unmute's result with a fresh read after it", async () => {
  const since = new Date(2026, 9, 24, 9, 5).getTime();
  const muted = status({ device: device({ recording_state: "NOT_RECORDING", pages_waiting: 0 }), unmute_pending_since_ms: since });
  const listening = status({ device: device() });
  let current = muted;
  const { calls } = server({
    "GET /api/status": () => json(current),
    "POST /api/status-live": () => json({ ok: true, error: null, summary: summaryOf(current) }),
    "POST /api/unmute": () => { current = listening; return json({ ok: true, state: "LISTENING", error: null }); },
  });
  const { container } = render(<Card />);
  await flush();
  expect(screen.getByText("Muted")).toBeTruthy();
  expect(container.querySelector(".lamp")!.classList.contains("lamp-muted")).toBe(true);
  expect(screen.getByText("Unmute pending since 09:05, hold the button or press Unmute")).toBeTruthy();
  expect(container.textContent).not.toContain("pages waiting");
  calls.length = 0;

  fireEvent.click(screen.getByRole("button", { name: "Unmute" }));
  expect((screen.getByRole("button", { name: "Sync now" }) as HTMLButtonElement).disabled).toBe(true);
  await flush();
  expect(calls).toEqual(["POST /api/unmute", "GET /api/status", "POST /api/status-live", "GET /api/status"]);
  expect(container.querySelector(".pendant-result")!.textContent).toBe("Listening");
  expect(container.querySelector(".lamp")!.classList.contains("lamp-listening")).toBe(true);
  expect(screen.getByRole("button", { name: "Mute" })).toBeTruthy();
});

test("the buttons wait while a live read is in flight", async () => {
  const s = status();
  let answer!: () => void;
  const { handler } = server({ "GET /api/status": () => json(s) });
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/status-live") {
      await new Promise<void>((r) => { answer = r; });
      return json({ ok: true, error: null, summary: summaryOf(s) });
    }
    return handler(init?.method ?? "GET", url);
  }));
  render(<Card />);
  await flush();
  expect((screen.getByRole("button", { name: "Sync now" }) as HTMLButtonElement).disabled).toBe(true);
  answer();
  await flush();
  expect((screen.getByRole("button", { name: "Sync now" }) as HTMLButtonElement).disabled).toBe(false);
});

test("while the app is busy every button is disabled and no live read is made", async () => {
  const s = status({ busy: true });
  const { calls } = server({ "GET /api/status": json(s) });
  render(<Card />);
  await flush();
  for (const name of ["Sync now", "Mute"]) {
    expect((screen.getByRole("button", { name }) as HTMLButtonElement).disabled).toBe(true);
  }
  await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
  expect(calls.filter((c) => c.startsWith("POST"))).toEqual([]);
});

test("with no pendant address the card says where to set it and offers no buttons", async () => {
  const s = status({ device: null });
  server({
    "GET /api/status": json(s),
    "POST /api/status-live": json({ ok: false, error: "set pendant_address in config.toml", summary: summaryOf(s) }),
  });
  render(<Card />);
  await flush();
  expect(screen.getByText("No pendant address set. Add it in Settings › Pendant.")).toBeTruthy();
  expect(screen.queryAllByRole("button")).toEqual([]);
});

test("a sync shows what it drained; a busy app and a stopping app say so", async () => {
  const s = status();
  const answers = [
    json({ sync: { outcome: "drained", reason: "on charger", pages: 1021, messages: 3, capture: "x", capture_complete: true,
      muted_by: "recorder", unmute: "confirmed", status: null, charger_signal: "current", error: null, orphans: 0 }, process: "scheduled" }),
    json({ error: "busy" }, 409),
    json({ error: "stopping" }, 503),
  ];
  server({
    "GET /api/status": () => json(s),
    "POST /api/status-live": () => json({ ok: true, error: null, summary: summaryOf(s) }),
    "POST /api/sync": () => answers.shift()!,
  });
  const { container } = render(<Card />);
  await flush();
  const result = () => container.querySelector(".pendant-result")!.textContent;
  fireEvent.click(screen.getByRole("button", { name: "Sync now" }));
  await flush();
  expect(result()).toBe("Drained 1021 pages");
  fireEvent.click(screen.getByRole("button", { name: "Sync now" }));
  await flush();
  expect(result()).toBe("The pendant is busy, try again in a moment");
  fireEvent.click(screen.getByRole("button", { name: "Sync now" }));
  await flush();
  expect(result()).toBe("The app is stopping");
});

test("the timers: status every 15 s, a live read every 60 s while visible; none after unmount", async () => {
  const s = status();
  const { calls } = server({
    "GET /api/status": () => json(s),
    "POST /api/status-live": () => json({ ok: true, error: null, summary: summaryOf(s) }),
  });
  const { unmount } = render(<Card />);
  await flush();
  expect(calls).toEqual(["GET /api/status", "POST /api/status-live", "GET /api/status"]);
  calls.length = 0;

  await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
  expect(calls.filter((c) => c === "GET /api/status")).toHaveLength(5); // 4 polls and one after the live read
  expect(calls.filter((c) => c === "POST /api/status-live")).toHaveLength(1);
  calls.length = 0;

  // hidden: the cheap status read goes on, the live read pauses
  visibility = "hidden";
  document.dispatchEvent(new Event("visibilitychange"));
  await act(async () => { await vi.advanceTimersByTimeAsync(120_000); });
  expect(calls.filter((c) => c === "POST /api/status-live")).toHaveLength(0);
  // visible again: a live read at once, then the timer's
  visibility = "visible";
  document.dispatchEvent(new Event("visibilitychange"));
  await flush();
  expect(calls.filter((c) => c === "POST /api/status-live")).toHaveLength(1);
  await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
  expect(calls.filter((c) => c === "POST /api/status-live")).toHaveLength(2);

  unmount();
  calls.length = 0;
  await act(async () => { await vi.advanceTimersByTimeAsync(300_000); });
  expect(calls).toEqual([]);
  expect(vi.getTimerCount()).toBe(0);
});

test("after a sync that found no pendant, the live read waits", async () => {
  const s = status({ last_sync: { id: 3, started_ms: 0, ended_ms: 1, outcome: "not-in-range", reason: "not advertising",
    pages: 0, messages: 0, capture_id: null, muted_by: null, unmute: "n/a", error: null } });
  const { calls } = server({ "GET /api/status": () => json(s) });
  render(<Card />);
  await flush();
  await act(async () => { await vi.advanceTimersByTimeAsync(180_000); });
  expect(calls.filter((c) => c.startsWith("POST"))).toEqual([]);
});

test("a poll that saw the card's own live read as busy does not outlive the read", async () => {
  const idle = status();
  let polledBusy = false;
  let answer!: () => void;
  const { handler } = server({ "GET /api/status": () => json(polledBusy ? { ...idle, busy: true } : idle) });
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/status-live") {
      await new Promise<void>((r) => { answer = r; });
      polledBusy = false; // the read has let go of the pendant
      return json({ ok: true, error: null, summary: summaryOf(idle) });
    }
    return handler(init?.method ?? "GET", url);
  }));
  const { container } = render(<Card />);
  await flush();
  polledBusy = true; // the 15 s poll lands while the live read holds the pendant
  await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
  expect(container.querySelector(".pendant")!.getAttribute("aria-busy")).toBe("true");
  answer();
  await flush();
  expect((screen.getByRole("button", { name: "Sync now" }) as HTMLButtonElement).disabled).toBe(false);
  expect(container.querySelector(".pendant")!.getAttribute("aria-busy")).toBeNull();
});

test("when the app cannot be reached the card says so, and stops saying so once it answers", async () => {
  const s = status({ device: device({ age_s: 125 }) });
  let down = false;
  server({
    "GET /api/status": () => (down ? json({ error: "nope" }, 500) : json(s)),
    "POST /api/status-live": () => json({ ok: true, error: null, summary: summaryOf(s) }),
  });
  render(<Card />);
  await flush();
  expect(screen.getByText("as of 2 min ago")).toBeTruthy();
  down = true;
  await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
  expect(screen.getByText("Cannot reach the app")).toBeTruthy();
  expect(screen.queryByText("as of 2 min ago")).toBeNull();
  down = false;
  await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
  expect(screen.queryByText("Cannot reach the app")).toBeNull();
  expect(screen.getByText("as of 2 min ago")).toBeTruthy();
});

test("a failed fetch of the status also counts as the app out of reach", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
  render(<Card />);
  await flush();
  expect(screen.getByText("Cannot reach the app")).toBeTruthy();
});

test("a window visible but behind others makes no live reads; coming to the front reads at once", async () => {
  const s = status();
  const { calls } = server({
    "GET /api/status": () => json(s),
    "POST /api/status-live": () => json({ ok: true, error: null, summary: summaryOf(s) }),
  });
  render(<Card />);
  await flush();
  expect(calls.filter((c) => c === "POST /api/status-live")).toHaveLength(1);
  calls.length = 0;

  focused = false;
  window.dispatchEvent(new Event("blur"));
  await act(async () => { await vi.advanceTimersByTimeAsync(180_000); });
  expect(calls.filter((c) => c === "POST /api/status-live")).toHaveLength(0);
  expect(calls.filter((c) => c === "GET /api/status")).toHaveLength(12); // the cheap poll keeps running

  focused = true;
  window.dispatchEvent(new Event("focus"));
  await flush();
  expect(calls.filter((c) => c === "POST /api/status-live")).toHaveLength(1);
  await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
  expect(calls.filter((c) => c === "POST /api/status-live")).toHaveLength(2);
});
