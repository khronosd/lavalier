import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/preact";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { InsightsIndex, Job, ProviderFacts } from "../api";
import { anthropic, at, job, noProvider, ollama } from "../insights.fixtures";
import { MODEL_PRIVACY } from "../insights";
import { Insights } from "./Insights";

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const opus: ProviderFacts = {
  ...anthropic, model: "claude-opus-5-5",
  facts: { sends: "each day's transcript text and your questions, never audio", to: "Anthropic",
    cost: "about $0.20 per 3-hour day" },
  models: [{ id: "claude-opus-5-5", label: "Claude Opus 5.5", recommended: true, cost_per_day: "about $0.20 per 3-hour day" }],
};

const without = (n: number, chars = 160_000) =>
  Array.from({ length: n }, (_, i) => ({ day: `2026-10-${String(22 - i).padStart(2, "0")}`, chars, error: null }));

const on22 = (h: number, m: number) => new Date(2026, 9, 22, h, m).getTime();

const full = (over: Partial<InsightsIndex> = {}): InsightsIndex => ({
  follow_ups: [
    { day: "2026-10-23", text: "Plug the pendant in before the sync", at_ms: at(23, 4), line_id: null },
    { day: "2026-10-23", text: "Check the mute survives a reboot", at_ms: at(22, 56, 9), line_id: "clip_b-0" },
    { day: "2026-10-22", text: "Call <b>Ana</b> back", at_ms: on22(9, 30), line_id: "clip_a-3" },
  ],
  people: [{ name: "Ana", days: ["2026-10-23", "2026-10-22"] }, { name: "Ben", days: ["2026-10-23"] }],
  topics: [{ name: "pendant firmware", days: ["2026-10-23"] }],
  days_without: [], generating: [], due: [], auto: true, ...over,
});

let calls: { key: string; body: unknown }[];
let facts: ProviderFacts;
let indexes: InsightsIndex[]; // one per GET; the last repeats
let jobs: Job[];
let post: () => Response;
let jobGone: boolean;
let jobFails: number; // how many job GETs answer 500 before the queue

beforeEach(() => {
  vi.useFakeTimers();
  calls = [];
  facts = opus;
  indexes = [full()];
  jobs = [job({ kind: "generate_range", key: "range" })];
  post = () => json({ job: "j1" }, 202);
  jobGone = false;
  jobFails = 0;
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${url}`;
    calls.push({ key, body: init?.body ? JSON.parse(init.body as string) : undefined });
    if (key === "GET /api/insights/providers") return json(facts);
    if (key === "GET /api/insights") return json(indexes.length > 1 ? indexes.shift() : indexes[0]);
    if (key === "GET /api/jobs/j1" && jobGone) return json({ error: "not found" }, 404);
    if (key === "GET /api/jobs/j1" && jobFails > 0) { jobFails--; return json({ error: "boom" }, 500); }
    if (key === "GET /api/jobs/j1") return json(jobs.length > 1 ? jobs.shift() : jobs[0]);
    if (key === "POST /api/insights/generate-range") return post();
    throw new Error(`unexpected ${key}`);
  }));
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const flush = () => act(async () => { await vi.advanceTimersByTimeAsync(0); });
const tick = (ms = 1000) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });

async function show() {
  const r = render(<Insights />);
  await flush();
  return r;
}

test("follow-ups across days, newest day first, under the day's title on the margin grid", async () => {
  const { container } = await show();
  const section = screen.getByRole("heading", { name: "Follow-ups" }).closest("section")!;
  const groups = [...section.querySelectorAll(".day-group")];
  expect(groups.map((g) => g.querySelector(".group-title")!.textContent)).toEqual(["Friday, 23 October", "Thursday, 22 October"]);
  const rows = groups.map((g) => [...g.querySelectorAll(".line")].map((r) => r.textContent));
  // days newest first; within a day, in time order
  expect(rows).toEqual([
    ["22:56:09Check the mute survives a reboot", "23:04:00Plug the pendant in before the sync"],
    ["09:30:00Call <b>Ana</b> back"],
  ]);
  const jump = within(groups[0] as HTMLElement).getByRole("link", { name: "22:56:09" });
  expect(jump.getAttribute("href")).toBe("#/day/2026-10-23?at=clip_b-0");
  expect(groups[0].querySelectorAll("a")).toHaveLength(1); // the one without a line has no link
  expect(within(groups[1] as HTMLElement).getByRole("link", { name: "09:30:00" }).getAttribute("href"))
    .toBe("#/day/2026-10-22?at=clip_a-3");
  expect(container.querySelector("b")).toBeNull(); // text, never markup
  expect(container.querySelector("[style]")).toBeNull();
});

test("people and topics, each with the days it appears on as links to that day's insights", async () => {
  await show();
  const people = screen.getByRole("heading", { name: "People" }).closest("section")!;
  const ana = within(people as HTMLElement).getByText("Ana").closest("li")!;
  const links = [...ana.querySelectorAll("a")];
  expect(links.map((a) => a.textContent)).toEqual(["23 October", "22 October"]);
  expect(links.map((a) => a.getAttribute("href"))).toEqual(["#/day/2026-10-23?tab=insights", "#/day/2026-10-22?tab=insights"]);
  const topics = screen.getByRole("heading", { name: "Topics" }).closest("section")!;
  expect(within(topics as HTMLElement).getByText("pendant firmware")).toBeTruthy();
  expect(people.parentElement).toBe(topics.parentElement); // the two columns sit side by side
});

test("Generate for the last 30 days shows the estimate first, with Confirm", async () => {
  indexes = [full({ days_without: without(12) })];
  await show();
  fireEvent.click(screen.getByRole("button", { name: "Generate for the last 30 days" }));
  expect(screen.getByText("12 days, about 480k tokens, about $2.40 with Claude Opus 5.5")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Confirm" })).toBeTruthy();
  expect(calls.filter((c) => c.key.startsWith("POST"))).toEqual([]);
  fireEvent.click(screen.getByRole("button", { name: "Generate for the last 7 days" }));
  expect(screen.getByText("7 days, about 280k tokens, about $1.40 with Claude Opus 5.5")).toBeTruthy();
});

test("on this Mac the estimate is free", async () => {
  facts = { ...ollama, facts: { ...ollama.facts!, cost: "free, runs on this Mac" } };
  indexes = [full({ days_without: without(3) })];
  await show();
  fireEvent.click(screen.getByRole("button", { name: "Generate for the last 7 days" }));
  expect(screen.getByText("3 days, about 120k tokens, free, runs on this Mac")).toBeTruthy();
});

test("nothing to generate: no Confirm", async () => {
  await show();
  fireEvent.click(screen.getByRole("button", { name: "Generate for the last 7 days" }));
  expect(screen.getByText("Nothing to generate")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Confirm" })).toBeNull();
});

test("Confirm posts the range, polls the job, then shows the result and reads the index again", async () => {
  indexes = [full({ days_without: without(12) }), full()];
  jobs = [
    job({ kind: "generate_range", key: "range" }),
    job({ kind: "generate_range", key: "range", state: "done",
      result: { done: 11, errors: [{ day: "2026-10-20", error: "rate limited" }] } }),
  ];
  await show();
  fireEvent.click(screen.getByRole("button", { name: "Generate for the last 30 days" }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
  await flush();
  expect(calls.find((c) => c.key === "POST /api/insights/generate-range")!.body).toEqual({ days: 30 });
  expect(screen.getByText("Generating 12 days…")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Confirm" })).toBeNull();
  expect((screen.getByRole("button", { name: "Generate for the last 7 days" }) as HTMLButtonElement).disabled).toBe(true);
  await tick();
  expect(screen.getByText("Generated 11 days; 1 failed: Tuesday, 20 October: rate limited")).toBeTruthy();
  expect(screen.queryByText(/Generating 12 days/)).toBeNull();
  expect(calls.filter((c) => c.key === "GET /api/insights")).toHaveLength(2);
  await tick(5000);
  expect(calls.filter((c) => c.key === "GET /api/jobs/j1")).toHaveLength(2);
});

test("a refused range says why", async () => {
  indexes = [full({ days_without: without(2) })];
  post = () => json({ error: "No key saved. Add one in Settings › Model." }, 400);
  await show();
  fireEvent.click(screen.getByRole("button", { name: "Generate for the last 7 days" }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
  await flush();
  expect(screen.getByRole("alert").textContent).toBe("No key saved. Add one in Settings › Model.");
});

test("a range job lost to an app restart says so", async () => {
  indexes = [full({ days_without: without(2) })];
  jobGone = true;
  await show();
  fireEvent.click(screen.getByRole("button", { name: "Generate for the last 7 days" }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
  await flush();
  await flush();
  expect(screen.getByRole("alert").textContent).toBe("The app restarted before this finished. Try again.");
});

test("days being generated read as such", async () => {
  indexes = [full({ generating: ["2026-10-23"] })];
  await show();
  expect(screen.getByText("Generating Friday, 23 October…")).toBeTruthy();
});

test("no insights yet, with a provider: how to get the first ones", async () => {
  indexes = [full({ follow_ups: [], people: [], topics: [], days_without: without(2) })];
  await show();
  expect(screen.getByText("No insights yet.")).toBeTruthy();
  expect(screen.getByText("Open a day's Insights tab and press Generate now, or generate the last 7 days below.")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Generate for the last 7 days" })).toBeTruthy();
  expect(screen.queryByRole("heading", { name: "Follow-ups" })).toBeNull();
});

test("no provider: the day tab's copy and a link to the Model tab, and nothing to generate with", async () => {
  facts = noProvider;
  indexes = [full({ follow_ups: [], people: [], topics: [], days_without: without(2), auto: false })];
  await show();
  expect(screen.getByText(
    "Pick a model in Settings › Model to get a summary, follow-ups, people and topics for each day.")).toBeTruthy();
  expect(screen.getByText(MODEL_PRIVACY, { exact: false })).toBeTruthy();
  expect(screen.getByRole("link", { name: "Open Settings › Model" }).getAttribute("href")).toBe("#/settings/model");
  expect(within(screen.getByRole("main")).queryByRole("button")).toBeNull(); // nothing to generate with
});

test("a failed load says so", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
  await show();
  expect(screen.getByRole("alert").textContent)
    .toBe("Insights could not be loaded (Failed to fetch). Check that the lavalier app is running.");
});

test("a range already running says so", async () => {
  indexes = [full({ days_without: without(2) })];
  post = () => json({ error: "already running" }, 409);
  await show();
  fireEvent.click(screen.getByRole("button", { name: "Generate for the last 7 days" }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
  await flush();
  expect(screen.getByRole("alert").textContent).toBe("Days are already being generated. Wait for that run to finish.");
});

test("a poll that fails says the range is still generating and keeps polling", async () => {
  indexes = [full({ days_without: without(2) })];
  jobFails = 1;
  jobs = [job({ kind: "generate_range", key: "range", state: "done", result: { done: 2, errors: [] } })];
  await show();
  fireEvent.click(screen.getByRole("button", { name: "Generate for the last 7 days" }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
  await flush();
  expect(screen.getByText("Still generating; the results will appear here when it finishes")).toBeTruthy();
  expect(screen.queryByRole("alert")).toBeNull();
  await tick(5000);
  expect(screen.getByText("Generated 2 days.")).toBeTruthy();
  expect(screen.queryByText(/Still generating/)).toBeNull();
});

test("a range poll is not capped at 30 minutes", async () => {
  indexes = [full({ days_without: without(2) })];
  await show();
  fireEvent.click(screen.getByRole("button", { name: "Generate for the last 7 days" }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
  await flush();
  await tick(31 * 60_000);
  expect(screen.getByText("Generating 2 days…")).toBeTruthy();
  expect(screen.queryByRole("alert")).toBeNull();
  expect(screen.queryByText(/30 minutes/)).toBeNull();
});

test("leaving the page stops polling the range", async () => {
  indexes = [full({ days_without: without(2) })];
  const { unmount } = await show();
  fireEvent.click(screen.getByRole("button", { name: "Generate for the last 7 days" }));
  fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
  await flush();
  await tick();
  const polled = calls.filter((c) => c.key === "GET /api/jobs/j1").length;
  expect(polled).toBe(2);
  unmount();
  await tick(10_000);
  expect(calls.filter((c) => c.key === "GET /api/jobs/j1")).toHaveLength(polled);
});
