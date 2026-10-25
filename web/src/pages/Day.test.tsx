import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/preact";
import { afterEach, expect, test, vi } from "vitest";
import type { ConversationView, DaySummary, DayView } from "../api";
import { neighbours } from "../components/DayNav";
import { DataVersion } from "../refresh";
import { parseHash } from "../router";
import { Journal } from "./Journal";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.location.hash = "";
});

const at = (h: number, m: number, s = 0) => new Date(2026, 9, 23, h, m, s).getTime();

const long: ConversationView = {
  conversation_id: "conv_long", start_ms: at(17, 33), end_ms: at(20, 40), speech_ms: at(20, 34) - at(17, 33),
  star_ms: [], pinned: false, label: null, clip_ids: ["clip_a"], audio_available: true,
  lines: [{ at_ms: at(17, 33, 14), text: "First words of the evening.", clip_id: "clip_a", seq: 0 }],
};
const test2256: ConversationView = {
  conversation_id: "conv_test", start_ms: at(22, 56, 0), end_ms: at(22, 56, 16), speech_ms: 16_000,
  star_ms: [at(22, 56, 7), at(22, 56, 12)], pinned: false, label: null, clip_ids: ["clip_b"], audio_available: true,
  lines: [
    { at_ms: at(22, 56, 9), text: "test test test one two three", clip_id: "clip_b", seq: 0 },
    { at_ms: at(22, 56, 13), text: "test test test one two three", clip_id: "clip_b", seq: 1 },
  ],
};
const day23: DayView = {
  day: "2026-10-23", speech_ms: at(20, 34) - at(17, 33) + 16_000, conversations: [long, test2256],
  stars: [
    { at_ms: at(22, 56, 7), conversation_id: "conv_test", quote: "test test test one two three" },
    { at_ms: at(22, 56, 12), conversation_id: "conv_test", quote: "test test test one two three" },
  ],
  noise_clips: 75, audio_until: "2026-11-07", audio_kept_for_good: false, pending_pages: null,
};
const days: DaySummary[] = [
  { day: "2026-10-24", speech_ms: 0, conversations: 0, stars: 0, noise_clips: 0 },
  { day: "2026-10-23", speech_ms: day23.speech_ms, conversations: 2, stars: 2, noise_clips: 75 },
];
const SUMMARY = "2 conversations · 3 h 1 min of speech · 2 starred moments · audio kept until 7 November";

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

type Reply = () => Response | Promise<Response>;
const NO_PROVIDER = { provider: "", model: "", display: "", sentence: "" };
const NO_INSIGHT = { state: "none", record: null, reason: "No model chosen.", job: null };

/** A fetch answering by route with a fresh Response per call: the day from `day` (one reply, or a queue
 * whose last reply repeats), the insight routes with nothing to show, anything else from `more`. */
function serve(day: Reply | Reply[], more: Record<string, Reply> = {}) {
  const queue = Array.isArray(day) ? [...day] : [day];
  const mock = vi.fn(async (url: string, _init?: RequestInit) => {
    if (url in more) return more[url]();
    if (url.startsWith("/api/day/")) return (queue.length > 1 ? queue.shift()! : queue[0])();
    if (url === "/api/insights/providers") return json(NO_PROVIDER);
    if (url.startsWith("/api/insights/")) return json(NO_INSIGHT);
    throw new Error(`unexpected ${url}`);
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

const show = (hash: string, today = "2026-10-24") =>
  render(<Journal route={parseHash(hash)} today={today} days={days} />);

test("a day shows its band, a row per conversation, the first one's transcript, and the starred moments in the inspector", async () => {
  serve(() => json(day23));
  const { container } = show("#/day/2026-10-23");
  expect(await screen.findByText(SUMMARY)).toBeTruthy();
  expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Friday, 23 October");

  // the list column: rows under the part of the day they started in, the first one selected
  const list = screen.getByRole("region", { name: "Conversations" });
  expect(within(list).getAllByText(/^(Morning|Afternoon|Evening)$/).map((el) => el.textContent)).toEqual(["Afternoon", "Evening"]);
  const rows = within(list).getAllByRole("link");
  expect(rows.map((a) => a.getAttribute("href"))).toEqual(["#/day/2026-10-23?conv=conv_long", "#/day/2026-10-23?conv=conv_test"]);
  expect(rows.map((a) => a.getAttribute("aria-current"))).toEqual(["true", null]);
  expect(rows[0].querySelector(".row-title")!.textContent).toBe("17:33 to 20:40");
  expect(rows[0].querySelector(".row-snippet")!.textContent).toBe("First words of the evening.");
  expect(rows[0].querySelector(".row-len")!.textContent).toBe("3 h 1 min");
  expect(rows[0].querySelector(".wave")).toBeTruthy();
  expect(rows[0].querySelector(".row-stars")).toBeNull();
  expect(rows[1].querySelector(".row-stars")!.getAttribute("aria-label")).toBe("2 starred");

  // the content column shows the selected conversation only
  expect(screen.getByRole("heading", { name: "17:33 to 20:40" })).toBeTruthy();
  expect(container.querySelector("#c-conv_long .conv-dur")!.textContent).toBe("3 h 1 min speech");
  expect(container.querySelector("#c-conv_test")).toBeNull();
  expect(screen.getByRole("link", { current: "page" }).textContent).toBe("Transcript");

  // the inspector lists the starred moments, linked to their conversation as a route with ?at=, never a bare anchor
  const inspector = screen.getByRole("complementary", { name: "Insights" });
  const links = within(inspector).getAllByRole("link", { name: "in the 22:56 conversation" });
  expect(links.map((a) => a.getAttribute("href"))).toEqual(["#/day/2026-10-23?at=c-conv_test", "#/day/2026-10-23?at=c-conv_test"]);

  // previous is disabled at the oldest day; next goes to today's page
  expect(screen.getByText("Previous").closest("[aria-disabled]")!.getAttribute("aria-disabled")).toBe("true");
  expect(screen.getByRole("link", { name: /^Next day/ }).getAttribute("href")).toBe("#/today");
});

test("?conv= selects a row, and its conversation shows its lines with the starred ones marked", async () => {
  serve(() => json(day23));
  const { container } = show("#/day/2026-10-23?conv=conv_test");
  await waitFor(() => expect(container.querySelector("#c-conv_test")).toBeTruthy());
  expect(container.querySelector("#c-conv_long")).toBeNull();
  expect(screen.getByRole("heading", { name: "22:56" })).toBeTruthy();
  const section = container.querySelector("#c-conv_test")!;
  // the lines in time order; each star marks the line at or just after it
  const rows = [...section.querySelectorAll(".line")]
    .map((el) => `${el.id} ${el.querySelector("time")!.textContent}${el.classList.contains("starred") ? " ★" : ""}`);
  expect(rows).toEqual(["clip_b-0 22:56:09 ★", "clip_b-1 22:56:13 ★"]);
  expect(section.querySelector(".conv-stars")!.textContent).toBe("★★");
  // the heading shows the wall-clock range and, beside it, the speech total (not the span's length)
  expect(section.querySelector(".conv-dur")!.textContent).toBe("16 s speech ★★");
  expect(screen.getByRole("link", { name: /^22:56/ }).getAttribute("aria-current")).toBe("true");
});

test("a star after the last line keeps its own row at its exact time", async () => {
  const late = { ...test2256, star_ms: [at(22, 56, 15)] };
  serve(() => json({ ...day23, conversations: [long, late] }));
  const { container } = show("#/day/2026-10-23?conv=conv_test");
  await waitFor(() => expect(container.querySelector("#c-conv_test")).toBeTruthy());
  const rows = [...container.querySelectorAll("#c-conv_test .line")].map((el) => `${el.id || "star"} ${el.querySelector("time")!.textContent}`);
  expect(rows).toEqual(["clip_b-0 22:56:09", "clip_b-1 22:56:13", "star 22:56:15"]);
});

test("lines more than five minutes apart get a quiet gap between them", async () => {
  const spaced: ConversationView = {
    ...long,
    lines: [
      { at_ms: at(17, 33, 14), text: "First words of the evening.", clip_id: "clip_a", seq: 0 },
      { at_ms: at(17, 39, 20), text: "Six minutes later.", clip_id: "clip_a", seq: 1 },
      { at_ms: at(17, 40, 0), text: "Soon after.", clip_id: "clip_a", seq: 2 },
    ],
  };
  serve(() => json({ ...day23, conversations: [spaced, test2256] }));
  show("#/day/2026-10-23");
  expect(await screen.findByText("6 minutes quiet")).toBeTruthy();
  expect(screen.getAllByText(/quiet$/)).toHaveLength(1);
});

test("Today in the day navigation keeps the open tab, and Starred on Today stays on Today", async () => {
  serve(() => json(day23));
  show("#/day/2026-10-23?tab=audio");
  expect((await screen.findByRole("link", { name: "Today" })).getAttribute("href")).toBe("#/today?tab=audio");
  cleanup();

  serve(() => json({ ...day23, day: "2026-10-24" }));
  show("#/today");
  const links = await screen.findAllByRole("link", { name: "in the 22:56 conversation" });
  expect(links[0].getAttribute("href")).toBe("#/today?at=c-conv_test");
});

test("?at= selects the line's conversation, scrolls to the line, flashes it, drops at, and the selection stays", async () => {
  const scrolled: { id: string; arg: unknown }[] = [];
  const original = Element.prototype.scrollIntoView;
  Element.prototype.scrollIntoView = function (this: Element, arg?: unknown) { scrolled.push({ id: this.id, arg }); };
  try {
    window.location.hash = "#/day/2026-10-23?tab=transcript&at=clip_b-1";
    serve(() => json(day23));
    const { container, rerender } = show(window.location.hash);
    await waitFor(() => expect(container.querySelector("#clip_b-1")!.classList.contains("flash")).toBe(true));
    expect(scrolled).toEqual([{ id: "clip_b-1", arg: { block: "center" } }]);
    expect(window.location.hash).toBe("#/day/2026-10-23?tab=transcript");
    expect(container.querySelectorAll(".flash")).toHaveLength(1);
    // the route no longer names the conversation; the page remembers it
    rerender(<Journal route={parseHash(window.location.hash)} today="2026-10-24" days={days} />);
    expect(container.querySelector("#c-conv_test")).toBeTruthy();
    expect(container.querySelector("#c-conv_long")).toBeNull();
    expect(screen.getByRole("link", { name: /^22:56/ }).getAttribute("aria-current")).toBe("true");
    await waitFor(() => expect(container.querySelector(".flash")).toBeNull(), { timeout: 2500 });
  } finally {
    Element.prototype.scrollIntoView = original;
  }
});

test("?at= naming a conversation scrolls to its block; an unknown target only drops at", async () => {
  const scrolled: string[] = [];
  const original = Element.prototype.scrollIntoView;
  Element.prototype.scrollIntoView = function (this: Element) { scrolled.push(this.id); };
  try {
    window.location.hash = "#/day/2026-10-23?at=c-conv_test";
    serve(() => json(day23));
    const { container } = show(window.location.hash);
    await waitFor(() => expect(container.querySelector("#c-conv_test")!.classList.contains("flash")).toBe(true));
    expect(scrolled).toEqual(["c-conv_test"]);
    cleanup();

    window.location.hash = "#/day/2026-10-23?at=clip_gone-9";
    serve(() => json(day23));
    show(window.location.hash);
    await waitFor(() => expect(window.location.hash).toBe("#/day/2026-10-23"));
    expect(scrolled).toEqual(["c-conv_test"]);
  } finally {
    Element.prototype.scrollIntoView = original;
  }
});

test("Pin updates the conversation in place; a refusal is shown beside it", async () => {
  const pinned = { ...day23, conversations: [long, { ...test2256, pinned: true }] };
  const mock = serve([() => json(day23), () => json(pinned)], {
    "/api/pin/conv_test": () => json({ pinned: true }),
    "/api/unpin/conv_test": () => json({ error: "not found" }, 404),
  });
  show("#/day/2026-10-23?conv=conv_test");

  fireEvent.click(await screen.findByRole("button", { name: "Pin" }));
  expect(await screen.findByRole("button", { name: "Unpin" })).toBeTruthy();
  expect(screen.getByText("pinned")).toBeTruthy();
  const pin = mock.mock.calls.find((c) => c[0] === "/api/pin/conv_test")!;
  expect(pin[1]!.method).toBe("POST");

  await waitFor(() => expect(mock.mock.calls.filter((c) => c[0].startsWith("/api/day/"))).toHaveLength(2));
  fireEvent.click(screen.getByRole("button", { name: "Unpin" }));
  expect((await screen.findByRole("alert")).textContent).toBe("Could not unpin: not found");
  expect(mock.mock.calls.some((c) => c[0] === "/api/unpin/conv_test")).toBe(true);
  expect(screen.getByRole("button", { name: "Unpin" })).toBeTruthy();
});

test("Play opens the Audio tab with the selected conversation", async () => {
  serve(() => json(day23));
  show("#/day/2026-10-23");
  fireEvent.click(await screen.findByRole("button", { name: "Play" }));
  expect(window.location.hash).toBe("#/day/2026-10-23?tab=audio&conv=conv_long");
});

test("the Audio tab lists the day's conversations with Play day", async () => {
  serve(() => json(day23));
  show("#/day/2026-10-23?tab=audio");
  expect(await screen.findByRole("button", { name: "Play day" })).toBeTruthy();
  expect(screen.getByText("Audio is kept until 7 November.")).toBeTruthy();
  expect(screen.getAllByRole("button", { name: "Play" })).toHaveLength(2);
});

test("?tab=insights keeps the segments' links, moves focus onto the inspector, and leaves the transcript in place", async () => {
  serve(() => json(day23));
  show("#/day/2026-10-23?tab=insights");
  expect(await screen.findByText(
    "Pick a model in Settings › Model to get a summary, follow-ups, people and topics for each day.")).toBeTruthy();
  expect(screen.getByRole("link", { name: "Audio" }).getAttribute("href")).toBe("#/day/2026-10-23?tab=audio");
  expect(screen.getByRole("link", { current: "page" }).textContent).toBe("Transcript");
  expect(screen.queryByRole("link", { name: "Insights" })).toBeNull();
  expect(document.activeElement).toBe(screen.getByRole("complementary", { name: "Insights" }));
  expect(screen.getByRole("heading", { name: "17:33 to 20:40" })).toBeTruthy();
});

test("Today with nothing recorded says so, with the pages still on the pendant; the list column shows only its head", async () => {
  const empty: DayView = { ...day23, day: "2026-10-24", speech_ms: 0, conversations: [], stars: [], noise_clips: 0,
    audio_until: null, pending_pages: 787 };
  const mock = serve(() => json(empty));
  show("#/today");
  expect(await screen.findByText("Nothing recorded yet today")).toBeTruthy();
  expect(screen.getByText("787 pages are waiting on the pendant and will be added at the next sync.")).toBeTruthy();
  expect(mock.mock.calls[0][0]).toBe("/api/day/2026-10-24");
  expect(screen.getByText("Today").getAttribute("aria-disabled")).toBe("true");
  const list = screen.getByRole("region", { name: "Conversations" });
  expect(list.textContent).toBe("Conversations");
  expect(within(list).queryAllByRole("link")).toHaveLength(0);
});

test("a failed load says what happened in a warning notice", async () => {
  serve(() => json({ error: "unauthorized" }, 401));
  show("#/day/2026-10-23");
  const alert = await screen.findByRole("alert");
  expect(alert.textContent).toBe("The window was opened without its key. Close it and run lavalier window again.");
  expect(alert.classList.contains("warn")).toBe(true);
});

test("neighbours are the nearest older and newer days with clips", () => {
  const list = ["2026-10-24", "2026-10-21", "2026-10-20"].map((day) => ({ ...days[0], day }));
  expect(neighbours("2026-10-21", list)).toEqual({ previous: "2026-10-20", next: "2026-10-24" });
  expect(neighbours("2026-10-22", list)).toEqual({ previous: "2026-10-21", next: "2026-10-24" });
  expect(neighbours("2026-10-24", list)).toEqual({ previous: "2026-10-21", next: undefined });
  expect(neighbours("2026-10-20", list)).toEqual({ previous: undefined, next: "2026-10-21" });
});

test("a star with no speech nearby says so in the Starred section, and one in a conversation without a quote does not", async () => {
  const lonely: DayView = {
    ...day23,
    stars: [
      { at_ms: at(22, 50, 0), conversation_id: null, quote: null },
      { at_ms: at(22, 56, 12), conversation_id: "conv_test", quote: null },
    ],
  };
  serve(() => json(lonely));
  const { container } = show("#/day/2026-10-23");
  await screen.findByText("No speech recorded nearby");
  const notes = [...container.querySelectorAll(".starred .no-quote")].map((el) => el.textContent);
  expect(notes).toEqual(["No speech recorded nearby", "Nothing was said at this moment"]);
});

test("of two refetches in flight the latest wins: an older reply landing last never reverts a pin", async () => {
  const deferred: Array<(r: Response) => void> = [];
  const later = () => new Promise<Response>((resolve) => { deferred.push(resolve); });
  serve([() => json(day23), later, later], { "/api/pin/conv_test": () => json({ pinned: true }) });
  const page = (v: string) => (
    <DataVersion.Provider value={v}>
      <Journal route={parseHash("#/day/2026-10-23?conv=conv_test")} today="2026-10-24" days={days} />
    </DataVersion.Provider>
  );
  const { rerender } = render(page("v1"));
  const pin = await screen.findByRole("button", { name: "Pin" });
  rerender(page("v2")); // A: the refetch a new version asked for
  await waitFor(() => expect(deferred).toHaveLength(1));
  fireEvent.click(pin);
  await waitFor(() => expect(deferred).toHaveLength(2)); // B: the refetch after the pin

  deferred[1](json({ ...day23, conversations: [long, { ...test2256, pinned: true }] })); // B, the latest
  expect(await screen.findByRole("button", { name: "Unpin" })).toBeTruthy();
  deferred[0](json(day23)); // A, older, lands last
  await new Promise((r) => setTimeout(r, 0));
  await new Promise((r) => setTimeout(r, 0));
  expect(screen.getByRole("button", { name: "Unpin" })).toBeTruthy();
});
