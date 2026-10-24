import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/preact";
import { afterEach, expect, test, vi } from "vitest";
import type { ConversationView, DaySummary, DayView } from "../api";
import { neighbours } from "../components/DayNav";
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

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

test("a day shows its summary, the starred moments, conversations, and stars in place", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(day23)));
  const { container } = render(<Journal route={parseHash("#/day/2026-10-23")} today="2026-10-24" days={days} />);

  expect(await screen.findByText(
    "3 h 1 min of speech in 2 conversations. 75 noise clips were dropped. The audio is kept until 7 November.")).toBeTruthy();
  expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Friday, 23 October");
  expect(screen.getByRole("heading", { name: "17:33 to 20:40" })).toBeTruthy();
  expect(screen.getByRole("heading", { name: "22:56" })).toBeTruthy();
  expect(screen.getByRole("link", { current: true }).textContent).toBe("Transcript");

  // starred moments link to their conversation's anchor
  const links = screen.getAllByRole("link", { name: "in the 22:56 conversation" });
  expect(links.map((a) => a.getAttribute("href"))).toEqual(["#c-conv_test", "#c-conv_test"]);
  expect(container.querySelector("#c-conv_test")).toBeTruthy();

  // the line ids and the star lines in time order inside the 22:56 conversation
  const section = container.querySelector("#c-conv_test")!;
  const rows = [...section.querySelectorAll(".line")].map((el) => `${el.id || "star"} ${el.querySelector("time")!.textContent}`);
  expect(rows).toEqual(["star 22:56:07", "clip_b-0 22:56:09", "star 22:56:12", "clip_b-1 22:56:13"]);
  expect(section.querySelector(".conv-stars")!.textContent).toBe("★★");
  // the heading shows the wall-clock range and, beside it, the speech total (not the span's length)
  expect(section.querySelector(".conv-dur")!.textContent).toBe("16 s speech");
  expect(container.querySelector("#c-conv_long .conv-dur")!.textContent).toBe("3 h 1 min speech");

  // previous is disabled at the oldest day; next goes to today's page
  expect(screen.getByText("Previous").getAttribute("aria-disabled")).toBe("true");
  expect(screen.getByRole("link", { name: /^Next day/ }).getAttribute("href")).toBe("#/today");
});

test("Pin updates the conversation in place; a refusal is shown beside it", async () => {
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(json(day23))
    .mockResolvedValueOnce(json({ pinned: true }))
    .mockResolvedValueOnce(json({ ...day23, conversations: [long, { ...test2256, pinned: true }] }))
    .mockResolvedValueOnce(json({ error: "not found" }, 404));
  vi.stubGlobal("fetch", fetchMock);
  render(<Journal route={parseHash("#/day/2026-10-23")} today="2026-10-24" days={days} />);

  const pins = await screen.findAllByRole("button", { name: "Pin" });
  fireEvent.click(pins[1]);
  expect(await screen.findByRole("button", { name: "Unpin" })).toBeTruthy();
  expect(screen.getByText("pinned")).toBeTruthy();
  expect(fetchMock.mock.calls[1][0]).toBe("/api/pin/conv_test");
  expect(fetchMock.mock.calls[1][1].method).toBe("POST");

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
  fireEvent.click(screen.getByRole("button", { name: "Unpin" }));
  expect((await screen.findByRole("alert")).textContent).toBe("Could not unpin: not found");
  expect(fetchMock.mock.calls[3][0]).toBe("/api/unpin/conv_test");
  expect(screen.getByRole("button", { name: "Unpin" })).toBeTruthy();
});

test("Play opens the Audio tab with that conversation", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(day23)));
  render(<Journal route={parseHash("#/day/2026-10-23")} today="2026-10-24" days={days} />);
  fireEvent.click((await screen.findAllByRole("button", { name: "Play" }))[0]);
  expect(window.location.hash).toBe("#/day/2026-10-23?tab=audio&conv=conv_long");
});

test("the Insights tab keeps its placeholder and the tabs keep ?tab=", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(day23)));
  render(<Journal route={parseHash("#/day/2026-10-23?tab=insights")} today="2026-10-24" days={days} />);
  expect(await screen.findByText("Insights are not available yet")).toBeTruthy();
  expect(screen.getByRole("link", { name: "Audio" }).getAttribute("href")).toBe("#/day/2026-10-23?tab=audio");
  expect(screen.queryByRole("heading", { name: "22:56" })).toBeNull();
});

test("Today with nothing recorded says so, with the pages still on the pendant", async () => {
  const empty: DayView = { ...day23, day: "2026-10-24", speech_ms: 0, conversations: [], stars: [], noise_clips: 0,
    audio_until: null, pending_pages: 787 };
  const fetchMock = vi.fn().mockResolvedValue(json(empty));
  vi.stubGlobal("fetch", fetchMock);
  render(<Journal route={parseHash("#/today")} today="2026-10-24" days={days} />);
  expect(await screen.findByText("Nothing recorded yet today")).toBeTruthy();
  expect(screen.getByText("787 pages are waiting on the pendant and will be added at the next sync.")).toBeTruthy();
  expect(fetchMock.mock.calls[0][0]).toBe("/api/day/2026-10-24");
  expect(screen.getByText("Today").getAttribute("aria-disabled")).toBe("true");
});

test("a failed load says what happened in a warning notice", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ error: "unauthorized" }, 401)));
  render(<Journal route={parseHash("#/day/2026-10-23")} today="2026-10-24" days={days} />);
  const alert = await screen.findByRole("alert");
  expect(alert.textContent).toBe("This window could not sign in to the lavalier app. Reopen the window from the app.");
  expect(alert.classList.contains("warn")).toBe(true);
});

test("neighbours are the nearest older and newer days with clips", () => {
  const list = ["2026-10-24", "2026-10-21", "2026-10-20"].map((day) => ({ ...days[0], day }));
  expect(neighbours("2026-10-21", list)).toEqual({ previous: "2026-10-20", next: "2026-10-24" });
  expect(neighbours("2026-10-22", list)).toEqual({ previous: "2026-10-21", next: "2026-10-24" });
  expect(neighbours("2026-10-24", list)).toEqual({ previous: "2026-10-21", next: undefined });
  expect(neighbours("2026-10-20", list)).toEqual({ previous: undefined, next: "2026-10-21" });
});
