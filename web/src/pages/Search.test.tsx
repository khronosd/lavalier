import { cleanup, render, screen, waitFor, within } from "@testing-library/preact";
import { afterEach, expect, test, vi } from "vitest";
import type { DayView, Hit } from "../api";
import { forgetDays } from "../dayCache";
import { forgetSearches } from "../search";
import { Search } from "./Search";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  forgetSearches();
  forgetDays();
});

const at = (d: number, h: number, m: number, s = 0) => new Date(2026, 9, d, h, m, s).getTime();
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const hits: Hit[] = [
  { day: "2026-10-21", conversation_id: null, clip_id: "clip_old", seq: 2, at_ms: at(21, 9, 1, 5),
    snippet: "said <mark>three</mark> <script>alert(1)</script>" },
  { day: "2026-10-23", conversation_id: "c-20261023-225600", clip_id: "clip_b", seq: 1, at_ms: at(23, 22, 56, 13),
    snippet: "test test test <mark>one</mark> <mark>two</mark> <mark>three</mark>" },
  { day: "2026-10-23", conversation_id: "c-20261023-225600", clip_id: "clip_b", seq: 0, at_ms: at(23, 22, 56, 9),
    snippet: "test test test <mark>one</mark> <mark>two</mark> <mark>three</mark>" },
];
const day23: DayView = {
  day: "2026-10-23", speech_ms: 16_000, stars: [], noise_clips: 0, audio_until: "2026-11-07", audio_kept_for_good: false,
  pending_pages: null,
  conversations: [{
    conversation_id: "c-20261023-225600", start_ms: at(23, 22, 56), end_ms: at(23, 22, 56, 16), speech_ms: 16_000, star_ms: [],
    pinned: false, label: null, clip_ids: ["clip_b"], audio_available: true,
    lines: [
      { at_ms: at(23, 22, 56, 9), text: "test test test one two three", clip_id: "clip_b", seq: 0 },
      { at_ms: at(23, 22, 56, 13), text: "One more: two and three again", clip_id: "clip_b", seq: 1 },
    ],
  }],
};
const day21: DayView = { ...day23, day: "2026-10-21", conversations: [], audio_until: null };

/** A fetch answering the search with `found` and a day with its view, or 404 for a day not given. */
function serve(found: Hit[] | Response, days: Record<string, DayView | Response> = {}) {
  const mock = vi.fn(async (url: string, _init?: RequestInit) => {
    if (url.startsWith("/api/search?")) return found instanceof Response ? found : json(found);
    const day = /^\/api\/day\/(\d{4}-\d{2}-\d{2})$/.exec(url)?.[1];
    if (day) {
      const reply = days[day];
      return reply === undefined ? json({ error: "no such day" }, 404) : reply instanceof Response ? reply : json(reply);
    }
    if (url.startsWith("/api/pin/")) return json({ pinned: true });
    throw new Error(`unexpected ${url}`);
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

test("an empty query asks for one and fetches nothing; the list column shows only its head", () => {
  const mock = serve([]);
  render(<Search q="" />);
  expect(screen.getByText("Type to search every day")).toBeTruthy();
  expect(mock).not.toHaveBeenCalled();
  expect(screen.getByRole("region", { name: "Matches" }).textContent).toBe("Matches");
  expect(screen.queryByRole("complementary")).toBeNull();
});

test("hits group by day in the list column, newest first; the first is selected and its conversation shows the words marked", async () => {
  const mock = serve(hits, { "2026-10-23": day23 });
  const { container } = render(<Search q="one two three" />);
  const list = await screen.findByRole("region", { name: "Matches" });
  await waitFor(() => expect(list.querySelectorAll("a.hit")).toHaveLength(3));
  expect(mock.mock.calls[0][0]).toBe("/api/search?q=one%20two%20three&limit=100");
  expect([...list.querySelectorAll(".hd-day")].map((el) => el.textContent)).toEqual(["Friday, 23 October", "Wednesday, 21 October"]);
  expect([...list.querySelectorAll(".hd-count")].map((el) => el.textContent)).toEqual(["2", "1"]);

  const rows = [...list.querySelectorAll("a.hit")];
  expect(rows.map((a) => a.getAttribute("href"))).toEqual([
    "#/search?q=one+two+three&hit=clip_b-0", "#/search?q=one+two+three&hit=clip_b-1", "#/search?q=one+two+three&hit=clip_old-2"]);
  expect(rows.map((a) => a.getAttribute("aria-current"))).toEqual(["true", null, null]);
  expect(rows.map((a) => a.querySelector("time")!.textContent)).toEqual(["22:56:09", "22:56:13", "09:01:05"]);
  expect([...rows[0].querySelectorAll("mark")].map((m) => m.textContent)).toEqual(["one", "two", "three"]);
  expect(rows[0].querySelector(".hit-conv")!.textContent).toBe("in the 22:56 conversation");
  expect(rows[2].querySelector(".hit-conv")).toBeNull();
  expect(container.querySelector("script")).toBeNull();
  expect(rows[2].textContent).toContain("<script>alert(1)</script>");

  // the content column: the hit's day fetched once, its conversation with every occurrence marked, the hit line tinted
  await waitFor(() => expect(screen.getByRole("heading", { name: "22:56" })).toBeTruthy());
  expect(mock.mock.calls.filter((c) => c[0] === "/api/day/2026-10-23")).toHaveLength(1);
  const line = container.querySelector("#clip_b-0")!;
  expect(line.classList.contains("hit-line")).toBe(true);
  expect([...line.querySelectorAll("mark")].map((m) => m.textContent)).toEqual(["one", "two", "three"]);
  const other = container.querySelector("#clip_b-1")!;
  expect(other.classList.contains("hit-line")).toBe(false);
  expect([...other.querySelectorAll("mark")].map((m) => m.textContent)).toEqual(["One", "two", "three"]);

  // over it: the day, this match's place among all of them, and Open day as the jump
  expect(screen.getByText("Friday, 23 October", { selector: ".hit-day" })).toBeTruthy();
  expect(screen.getByText("1 of 3")).toBeTruthy();
  expect(screen.getByLabelText("Previous match").getAttribute("aria-disabled")).toBe("true");
  expect(screen.getByRole("link", { name: "Next match" }).getAttribute("href")).toBe("#/search?q=one+two+three&hit=clip_b-1");
  expect(screen.getByRole("link", { name: "Open day" }).getAttribute("href")).toBe("#/day/2026-10-23?at=clip_b-0");

  // the inspector: the counts, where it comes up
  const aside = screen.getByRole("complementary", { name: "About this search" });
  expect(aside.textContent).toContain("3 matches");
  expect(aside.textContent).toContain("in 2 days, every day searched");
  const where = within(aside).getAllByRole("link");
  expect(where.map((a) => [a.textContent, a.getAttribute("href")])).toEqual([
    ["Friday, 23 October2", "#/search?q=one+two+three&hit=clip_b-0"],
    ["Wednesday, 21 October1", "#/search?q=one+two+three&hit=clip_old-2"],
  ]);
});

test("?hit= selects that hit; a hit outside any conversation says so and still offers the day", async () => {
  serve(hits, { "2026-10-23": day23, "2026-10-21": day21 });
  const { container } = render(<Search q="one two three" hit="clip_old-2" />);
  expect(await screen.findByText("3 of 3")).toBeTruthy();
  expect([...container.querySelectorAll("a.hit")].map((a) => a.getAttribute("aria-current"))).toEqual([null, null, "true"]);
  expect(await screen.findByText("This line is not in a conversation")).toBeTruthy();
  expect(screen.getByRole("link", { name: "Open day" }).getAttribute("href")).toBe("#/day/2026-10-21?at=clip_old-2");
  expect(screen.getByRole("link", { name: "Previous match" }).getAttribute("href")).toBe("#/search?q=one+two+three&hit=clip_b-1");
  expect(screen.getByLabelText("Next match").getAttribute("aria-disabled")).toBe("true");
});

test("a hit's day that cannot be loaded shows the notice in the content column; the rows stay", async () => {
  serve(hits, { "2026-10-23": json({ error: "boom" }, 500) });
  const { container } = render(<Search q="one two three" />);
  const alert = await screen.findByRole("alert");
  expect(alert.textContent).toBe("This day could not be loaded (boom). Check that the lavalier app is running.");
  expect(container.querySelectorAll("a.hit")).toHaveLength(3);
});

test("recent searches: the last ones, newest first, without the current one, and the start of a query gives way to it", async () => {
  serve([]);
  const { rerender } = render(<Search q="ret" />);
  expect(await screen.findByText("No matches for “ret”")).toBeTruthy();
  rerender(<Search q="retention" />);
  expect(await screen.findByText("No matches for “retention”")).toBeTruthy();
  rerender(<Search q="vendor" />);
  expect(await screen.findByText("No matches for “vendor”")).toBeTruthy();
  const aside = screen.getByRole("complementary", { name: "About this search" });
  expect(within(aside).getAllByRole("link").map((a) => [a.textContent, a.getAttribute("href")]))
    .toEqual([["retention", "#/search?q=retention"]]);
});

test("no matches says so, naming the query; the list column shows only its head", async () => {
  serve([]);
  render(<Search q="nothing here" />);
  expect(await screen.findByText("No matches for “nothing here”")).toBeTruthy();
  expect(screen.getByRole("region", { name: "Matches" }).textContent).toBe("Matches");
});

test("a failed search says what happened", async () => {
  serve(json({ error: "stopping" }, 503));
  render(<Search q="x" />);
  expect((await screen.findByRole("alert")).textContent)
    .toBe("Search results could not be loaded (stopping). Check that the lavalier app is running.");
});
