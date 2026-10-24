import { act, cleanup, fireEvent, render, screen } from "@testing-library/preact";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { Status } from "../api";
import { device, status } from "../pendant.fixtures";
import { PendantCard } from "./PendantCard";

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
beforeEach(() => {
  vi.useFakeTimers();
  visibility = "visible";
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => visibility });
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

test("with no reading yet, the lamp is a grey outline and only Sync now is offered", async () => {
  const s = status({ device: null });
  server({ "GET /api/status": json(s), "POST /api/status-live": json({ ok: false, error: "Pendant not in range", summary: summaryOf(s) }) });
  const { container } = render(<PendantCard />);
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
  const { container } = render(<PendantCard />);
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
  const { container } = render(<PendantCard />);
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
  const { container } = render(<PendantCard />);
  await flush();
  expect(screen.getByText("Muted")).toBeTruthy();
  expect(container.querySelector(".lamp")!.classList.contains("lamp-muted")).toBe(true);
  expect(screen.getByText("Unmute pending since 09:05, hold the button or press Unmute")).toBeTruthy();
  expect(container.textContent).not.toContain("pages waiting");
  calls.length = 0;

  fireEvent.click(screen.getByRole("button", { name: "Unmute" }));
  expect((screen.getByRole("button", { name: "Sync now" }) as HTMLButtonElement).disabled).toBe(true);
  await flush();
  expect(calls).toEqual(["POST /api/unmute", "GET /api/status", "POST /api/status-live"]);
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
  render(<PendantCard />);
  await flush();
  expect((screen.getByRole("button", { name: "Sync now" }) as HTMLButtonElement).disabled).toBe(true);
  answer();
  await flush();
  expect((screen.getByRole("button", { name: "Sync now" }) as HTMLButtonElement).disabled).toBe(false);
});

test("while the app is busy every button is disabled and no live read is made", async () => {
  const s = status({ busy: true });
  const { calls } = server({ "GET /api/status": json(s) });
  render(<PendantCard />);
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
  render(<PendantCard />);
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
  const { container } = render(<PendantCard />);
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
  const { unmount } = render(<PendantCard />);
  await flush();
  expect(calls).toEqual(["GET /api/status", "POST /api/status-live"]);
  calls.length = 0;

  await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
  expect(calls.filter((c) => c === "GET /api/status")).toHaveLength(4);
  expect(calls.filter((c) => c === "POST /api/status-live")).toHaveLength(1);
  calls.length = 0;

  // hidden: the cheap status read goes on, the live read pauses
  visibility = "hidden";
  document.dispatchEvent(new Event("visibilitychange"));
  await act(async () => { await vi.advanceTimersByTimeAsync(120_000); });
  expect(calls.filter((c) => c === "POST /api/status-live")).toHaveLength(0);
  visibility = "visible";
  document.dispatchEvent(new Event("visibilitychange"));
  await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
  expect(calls.filter((c) => c === "POST /api/status-live")).toHaveLength(1);

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
  render(<PendantCard />);
  await flush();
  await act(async () => { await vi.advanceTimersByTimeAsync(180_000); });
  expect(calls.filter((c) => c.startsWith("POST"))).toEqual([]);
});
