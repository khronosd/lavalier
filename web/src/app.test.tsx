import { act, cleanup, render, screen, within } from "@testing-library/preact";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { DaySummary, DayView, Status } from "./api";
import { App } from "./app";
import { status } from "./pendant.fixtures";
import { dataVersion } from "./refresh";

const json = (body: unknown, code = 200) =>
  new Response(JSON.stringify(body), { status: code, headers: { "Content-Type": "application/json" } });

const at = (h: number, m: number, s = 0) => new Date(2026, 9, 23, h, m, s).getTime();

const day23: DayView = {
  day: "2026-10-23", speech_ms: 16_000, stars: [], noise_clips: 0, audio_until: null, audio_kept_for_good: false,
  pending_pages: null,
  conversations: [{
    conversation_id: "conv_test", start_ms: at(22, 56), end_ms: at(22, 56, 16), speech_ms: 16_000, star_ms: [],
    pinned: false, label: null, clip_ids: ["clip_b"], audio_available: true,
    lines: [{ at_ms: at(22, 56, 9), text: "test test test one two three", clip_id: "clip_b", seq: 0 }],
  }],
};
const days: DaySummary[] = [{ day: "2026-10-23", speech_ms: 16_000, conversations: 1, stars: 0, noise_clips: 0 }];

const run = (id: number) => ({
  id, started_ms: 0, ended_ms: 1, outcome: "drained", reason: "", pages: 3, messages: 3, capture_id: 1,
  muted_by: null, unmute: "n/a", error: null,
});

let current: Status;
let calls: string[];
let dayReply: () => Promise<Response>;
let insightsIndex: unknown;

beforeEach(() => {
  vi.useFakeTimers();
  vi.spyOn(document, "hasFocus").mockReturnValue(false); // no live reads: this is about the data
  window.location.hash = "#/day/2026-10-23";
  current = status({ last_sync: run(7), last_process: '{"transcribed": 1, "processed_ms": 1}' });
  calls = [];
  dayReply = async () => json(day23);
  insightsIndex = {
    follow_ups: [], people: [], topics: [], generating: [], due: [], auto: true,
    days_without: [{ day: "2026-10-22", chars: 100, error: null }, { day: "2026-10-21", chars: 100, error: null }],
  };
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${url}`;
    calls.push(key);
    if (key === "GET /api/status") return json(current);
    if (key === "GET /api/days") return json(days);
    if (key === "GET /api/day/2026-10-23") return dayReply();
    if (key === "GET /api/insights") return json(insightsIndex);
    throw new Error(`unexpected ${key}`);
  }));
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  window.location.hash = "";
});

const flush = () => act(async () => { await vi.advanceTimersByTimeAsync(0); });
const poll = () => act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
const count = (key: string) => calls.filter((c) => c === key).length;

test("the data version follows the last process and the last sync, and is unknown without a status", () => {
  const a = status({ last_sync: run(7), last_process: "x" });
  expect(dataVersion(null)).toBeNull();
  expect(dataVersion(a)).toBe(dataVersion(status({ last_sync: run(7), last_process: "x", busy: true })));
  expect(dataVersion(a)).not.toBe(dataVersion(status({ last_sync: run(8), last_process: "x" })));
  expect(dataVersion(a)).not.toBe(dataVersion(status({ last_sync: run(7), last_process: "y" })));
});

test("an unchanged status refetches nothing", async () => {
  render(<App />);
  await flush();
  expect(await screen.findByText("test test test one two three")).toBeTruthy();
  expect([count("GET /api/days"), count("GET /api/day/2026-10-23")]).toEqual([1, 1]);
  await poll();
  await poll();
  expect(count("GET /api/status")).toBe(3);
  expect([count("GET /api/days"), count("GET /api/day/2026-10-23")]).toEqual([1, 1]);
});

test("a new sync or process refetches the days and the open day once, without blanking the page", async () => {
  render(<App />);
  await flush();
  await poll();

  let release!: () => void;
  dayReply = () => new Promise((resolve) => { release = () => resolve(json(day23)); });
  current = { ...current, last_sync: run(8) };
  await poll();
  expect([count("GET /api/days"), count("GET /api/day/2026-10-23")]).toEqual([2, 2]);
  // the refetch is in flight: the day stays on screen, no loading state
  expect(screen.getByText("test test test one two three")).toBeTruthy();
  expect(screen.queryByText("Loading this day")).toBeNull();
  release();
  await flush();

  dayReply = async () => json(day23);
  current = { ...current, last_process: '{"transcribed": 2, "processed_ms": 2}' };
  await poll();
  await poll();
  expect([count("GET /api/days"), count("GET /api/day/2026-10-23")]).toEqual([3, 3]);
});

test("a failed refetch keeps what is on screen", async () => {
  render(<App />);
  await flush();
  dayReply = async () => json({ error: "boom" }, 500);
  current = { ...current, last_sync: run(9) };
  await poll();
  await flush();
  expect(screen.getByText("test test test one two three")).toBeTruthy();
  expect(screen.queryByRole("alert")).toBeNull();
});

test("a status-driven refetch of an equal day does not restart the audio that is playing", async () => {
  window.location.hash = "#/day/2026-10-23?tab=audio&conv=conv_test";
  const blobs: string[] = [];
  vi.stubGlobal("URL", Object.assign(URL, {
    createObjectURL: vi.fn(() => `blob:${blobs.length}`), revokeObjectURL: vi.fn(),
  }));
  const play = vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
  const base = vi.mocked(fetch).getMockImplementation()!;
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (url.startsWith("/api/audio/")) {
      blobs.push(url);
      return new Response(new Blob(["aac"]), { status: 200 });
    }
    return base(url, init);
  }));
  const { container } = render(<App />);
  await flush();
  await flush();
  const audio = container.querySelector("audio")!;
  expect(blobs).toEqual(["/api/audio/clip_b.m4a"]);
  const src = audio.getAttribute("src");
  Object.defineProperty(audio, "currentTime", { configurable: true, value: 7 });
  const plays = play.mock.calls.length;

  current = { ...current, last_sync: run(8) }; // the scheduled sync's new row
  await poll();
  await flush();
  expect(count("GET /api/day/2026-10-23")).toBe(2);
  expect(blobs).toHaveLength(1);
  expect(audio.getAttribute("src")).toBe(src);
  expect(play.mock.calls.length).toBe(plays);
});

const insightsLink = () =>
  within(screen.getByRole("navigation", { name: "Sidebar" })).getByRole("link", { name: /^Insights/ });

test("the Insights link counts the days without insights once a provider is set", async () => {
  const insights = { days_done: 1, days_error: 0, provider: "ollama", model: "", auto: true, generating: [] };
  current = { ...current, insights };
  render(<App />);
  await flush();
  await flush();
  expect(insightsLink().querySelector(".nav-count")!.textContent).toBe("2 to do");
  expect(count("GET /api/insights")).toBe(1);
  await poll();
  expect(count("GET /api/insights")).toBe(1); // nothing changed: no refetch

  insightsIndex = { ...(insightsIndex as object), days_without: [] };
  current = { ...current, last_process: '{"transcribed": 3, "processed_ms": 3}' };
  await poll();
  await flush();
  expect(count("GET /api/insights")).toBe(2);
  expect(insightsLink().querySelector(".nav-count")).toBeNull();
});

test("with no provider the Insights link has no count and asks nothing", async () => {
  current = { ...current, insights: { days_done: 0, days_error: 0, provider: "", model: "", auto: true, generating: [] } };
  render(<App />);
  await flush();
  await flush();
  expect(insightsLink().querySelector(".nav-count")).toBeNull();
  expect(count("GET /api/insights")).toBe(0);
});
