import { cleanup, render, screen } from "@testing-library/preact";
import { afterEach, expect, test, vi } from "vitest";
import type { Hit } from "../api";
import { Search } from "./Search";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
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

test("an empty query asks for one and fetches nothing", () => {
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  render(<Search q="" />);
  expect(screen.getByText("Type to search every day")).toBeTruthy();
  expect(fetchMock).not.toHaveBeenCalled();
});

test("results are grouped by day, newest first, with highlighted words and a jump to the moment", async () => {
  const fetchMock = vi.fn().mockResolvedValue(json(hits));
  vi.stubGlobal("fetch", fetchMock);
  const { container } = render(<Search q="one two three" />);

  const headings = await screen.findAllByRole("heading", { level: 2 });
  expect(headings.map((el) => el.textContent)).toEqual(["Friday, 23 October", "Wednesday, 21 October"]);
  expect(fetchMock.mock.calls[0][0]).toBe("/api/search?q=one%20two%20three&limit=100");

  const rows = [...container.querySelectorAll("a.hit")];
  expect(rows.map((a) => a.getAttribute("href"))).toEqual([
    "#/day/2026-10-23?at=clip_b-0", "#/day/2026-10-23?at=clip_b-1", "#/day/2026-10-21?at=clip_old-2"]);
  expect(rows.map((a) => a.querySelector("time")!.textContent)).toEqual(["22:56:09", "22:56:13", "09:01:05"]);
  expect([...rows[0].querySelectorAll("mark")].map((m) => m.textContent)).toEqual(["one", "two", "three"]);
  expect(rows[0].querySelector(".hit-conv")!.textContent).toBe("in the 22:56 conversation");
  expect(rows[2].querySelector(".hit-conv")).toBeNull();
  expect(container.querySelector("script")).toBeNull();
  expect(rows[2].textContent).toContain("<script>alert(1)</script>");
});

test("no matches says so, naming the query", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json([])));
  render(<Search q="nothing here" />);
  expect(await screen.findByText("No matches for “nothing here”")).toBeTruthy();
});

test("a failed search says what happened", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ error: "stopping" }, 503)));
  render(<Search q="x" />);
  expect((await screen.findByRole("alert")).textContent)
    .toBe("Search results could not be loaded (stopping). Check that the lavalier app is running, then reload.");
});
