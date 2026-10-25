import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/preact";
import { afterEach, expect, test, vi } from "vitest";
import type { DayView, StarredEntry } from "../api";
import { forgetDays } from "../dayCache";
import { StarredPage } from "./Starred";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  forgetDays();
});

const at = (d: number, h: number, m: number, s = 0) => new Date(2026, 9, d, h, m, s).getTime();
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

// as GET /api/starred sends them: newest first across days
const entries: StarredEntry[] = [
  { day: "2026-10-23", star: { at_ms: at(23, 22, 56, 12), conversation_id: "c-20261023-225600", quote: "test test test one two three" } },
  { day: "2026-10-23", star: { at_ms: at(23, 22, 56, 7), conversation_id: "c-20261023-225600", quote: "<b>not bold</b>" } },
  { day: "2026-10-21", star: { at_ms: at(21, 8, 15, 3), conversation_id: null, quote: null } },
];
const day23: DayView = {
  day: "2026-10-23", speech_ms: 16_000, noise_clips: 0, audio_until: "2026-11-07", audio_kept_for_good: false, pending_pages: null,
  stars: [entries[1].star, entries[0].star],
  conversations: [{
    conversation_id: "c-20261023-225600", start_ms: at(23, 22, 56), end_ms: at(23, 22, 56, 16), speech_ms: 16_000,
    star_ms: [at(23, 22, 56, 7), at(23, 22, 56, 12)], pinned: false, label: null, clip_ids: ["clip_b"], audio_available: true,
    lines: [
      { at_ms: at(23, 22, 56, 9), text: "<b>not bold</b>", clip_id: "clip_b", seq: 0 },
      { at_ms: at(23, 22, 56, 13), text: "test test test one two three", clip_id: "clip_b", seq: 1 },
    ],
  }],
};
const day21: DayView = { ...day23, day: "2026-10-21", stars: [entries[2].star], conversations: [], audio_until: null };

/** A fetch answering the starred list with `list` and a day with its view (404 for one not given). */
function serve(list: StarredEntry[] | Response, days: Record<string, DayView> = {}) {
  const mock = vi.fn(async (url: string, _init?: RequestInit) => {
    if (url === "/api/starred") return list instanceof Response ? list : json(list);
    const day = /^\/api\/day\/(\d{4}-\d{2}-\d{2})$/.exec(url)?.[1];
    if (day) return days[day] ? json(days[day]) : json({ error: "no such day" }, 404);
    if (url.startsWith("/api/pin/")) return json({ pinned: true });
    throw new Error(`unexpected ${url}`);
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

test("Starred lists every star by day, newest first, the first selected; its conversation, quote and surroundings show", async () => {
  const mock = serve(entries, { "2026-10-23": day23 });
  const { container } = render(<StarredPage />);
  const list = await screen.findByRole("region", { name: "Starred moments" });
  await waitFor(() => expect(list.querySelectorAll("a.star-row")).toHaveLength(3));
  expect(mock.mock.calls[0][0]).toBe("/api/starred");
  expect([...list.querySelectorAll(".hd-day")].map((el) => el.textContent)).toEqual(["Friday, 23 October", "Wednesday, 21 October"]);
  expect([...list.querySelectorAll(".hd-count")].map((el) => el.textContent)).toEqual(["2", "1"]);

  const rows = [...list.querySelectorAll("a.star-row")];
  expect(rows.map((el) => el.querySelector("time")!.textContent)).toEqual(["22:56:12", "22:56:07", "08:15:03"]);
  expect(rows.map((a) => a.getAttribute("href")))
    .toEqual([`#/starred?star=${at(23, 22, 56, 12)}`, `#/starred?star=${at(23, 22, 56, 7)}`, `#/starred?star=${at(21, 8, 15, 3)}`]);
  expect(rows.map((a) => a.getAttribute("aria-current"))).toEqual(["true", null, null]);
  expect(rows[0].querySelector(".star-conv")!.textContent).toBe("in the 22:56 conversation");
  expect(rows[2].querySelector(".star-conv")).toBeNull();
  // quotes are text in the reading face, never markup
  expect(within(list).getByText("test test test one two three").classList.contains("reading")).toBe(true);
  expect(within(list).getByText("<b>not bold</b>")).toBeTruthy();
  expect(container.querySelector(".star-row b")).toBeNull();
  // a star with no conversation within 60 s, in the spec's words
  expect(within(list).getByText("No speech recorded nearby").classList.contains("no-quote")).toBe(true);

  // the content column: the conversation's title, the moment, the pull quote, the lines around it, Open day as the jump
  await waitFor(() => expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("22:56"));
  expect(screen.getByText("Friday, 23 October · 22:56 · starred at 22:56:12")).toBeTruthy();
  expect(container.querySelector("blockquote.pull")!.textContent).toBe("“test test test one two three”");
  expect(screen.getByRole("link", { name: "Open day" }).getAttribute("href")).toBe("#/day/2026-10-23?at=c-c-20261023-225600");
  const around = [...container.querySelectorAll(".around .line")]
    .map((el) => `${el.id}${el.classList.contains("starred") ? " ★" : ""}`);
  expect(around).toEqual(["clip_b-0 ★", "clip_b-1 ★"]);

  // the inspector: the moment's facts, the actions, the conversation's other star
  const aside = screen.getByRole("complementary", { name: "This moment" });
  expect(aside.textContent).toContain("Starred at 22:56:12");
  expect(aside.textContent).toContain("Audio is kept until 7 November.");
  expect(within(aside).getByRole("button", { name: "Pin" })).toBeTruthy();
  expect((within(aside).getByRole("button", { name: "Copy the quote" }) as HTMLButtonElement).disabled).toBe(false);
  const also = within(aside).getAllByRole("link");
  expect(also.map((a) => [a.textContent, a.getAttribute("href")])).toEqual([["22:56:07<b>not bold</b>", `#/starred?star=${at(23, 22, 56, 7)}`]]);
});

test("?star= selects that moment; one outside any conversation offers its day and nothing to pin or copy", async () => {
  serve(entries, { "2026-10-21": day21 });
  const { container } = render(<StarredPage star={String(at(21, 8, 15, 3))} />);
  expect(await screen.findByText("Wednesday, 21 October · starred at 08:15:03")).toBeTruthy();
  expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Wednesday, 21 October");
  expect([...container.querySelectorAll("a.star-row")].map((a) => a.getAttribute("aria-current"))).toEqual([null, null, "true"]);
  expect(screen.getByRole("link", { name: "Open day" }).getAttribute("href")).toBe("#/day/2026-10-21");
  expect(container.querySelector(".pull")!.textContent).toBe("No speech recorded nearby");
  expect(container.querySelector(".around")).toBeNull();
  expect(screen.queryByRole("button", { name: "Pin" })).toBeNull();
  expect((screen.getByRole("button", { name: "Copy the quote" }) as HTMLButtonElement).disabled).toBe(true);
  expect(await screen.findByText("The audio for this day is no longer kept.")).toBeTruthy();
});

test("Copy the quote puts it on the clipboard and says so; Pin keeps the conversation and becomes Unpin", async () => {
  const write = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", { value: { writeText: write }, configurable: true });
  const mock = serve(entries, { "2026-10-23": day23 });
  render(<StarredPage />);
  fireEvent.click(await screen.findByRole("button", { name: "Copy the quote" }));
  expect(write).toHaveBeenCalledWith("test test test one two three");
  expect(await screen.findByText("Copied")).toBeTruthy();
  fireEvent.click(await screen.findByRole("button", { name: "Pin" })); // offered once the day is known
  expect(await screen.findByRole("button", { name: "Unpin" })).toBeTruthy();
  const pin = mock.mock.calls.find((c) => c[0] === "/api/pin/c-20261023-225600")!;
  expect(pin[1]!.method).toBe("POST");
});

test("Starred with nothing starred says how to star a moment; the list column shows only its head", async () => {
  serve([]);
  render(<StarredPage />);
  expect(await screen.findByText("No starred moments yet")).toBeTruthy();
  expect(screen.getByText("Press the pendant's button once to star the moment.")).toBeTruthy();
  expect(screen.getByRole("region", { name: "Starred moments" }).textContent).toBe("Starred moments");
  expect(screen.queryByRole("complementary")).toBeNull();
});

test("Starred says what went wrong when the list cannot be loaded", async () => {
  serve(json({ error: "stopping" }, 503));
  render(<StarredPage />);
  const alert = await screen.findByRole("alert");
  expect(alert.textContent).toBe("The starred moments could not be loaded (stopping). Check that the lavalier app is running.");
});
