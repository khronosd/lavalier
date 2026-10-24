import { cleanup, render, screen } from "@testing-library/preact";
import { afterEach, expect, test, vi } from "vitest";
import type { StarredEntry } from "../api";
import { StarredPage } from "./Starred";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
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

test("Starred lists every star by day, newest first, each with its quote and a jump to the moment", async () => {
  const fetchMock = vi.fn().mockResolvedValue(json(entries));
  vi.stubGlobal("fetch", fetchMock);
  const { container } = render(<StarredPage />);

  const headings = await screen.findAllByRole("heading", { level: 2 });
  expect(headings.map((el) => el.textContent)).toEqual(["Friday, 23 October", "Wednesday, 21 October"]);
  expect(fetchMock.mock.calls[0][0]).toBe("/api/starred");
  expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Starred");

  const rows = [...container.querySelectorAll(".star-row")].map((el) => el.querySelector("time")!.textContent);
  expect(rows).toEqual(["22:56:12", "22:56:07", "08:15:03"]);

  // quotes are text in the reading face, never markup
  expect(screen.getByText("test test test one two three").classList.contains("reading")).toBe(true);
  expect(screen.getByText("<b>not bold</b>")).toBeTruthy();
  expect(container.querySelector(".star-row b")).toBeNull();

  // a star with no conversation within 60 s, in the spec's words
  const muted = screen.getByText("No speech recorded nearby");
  expect(muted.classList.contains("no-quote")).toBe(true);

  const links = screen.getAllByRole("link", { name: "in the 22:56 conversation" });
  expect(links.map((a) => a.getAttribute("href"))).toEqual([
    "#/day/2026-10-23?at=c-c-20261023-225600", "#/day/2026-10-23?at=c-c-20261023-225600"]);
  expect(screen.getByRole("link", { name: "Open Wednesday, 21 October" }).getAttribute("href")).toBe("#/day/2026-10-21");
});

test("Starred with nothing starred says how to star a moment", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json([])));
  render(<StarredPage />);
  expect(await screen.findByText("No starred moments yet")).toBeTruthy();
});

test("Starred says what went wrong when the list cannot be loaded", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ error: "stopping" }, 503)));
  render(<StarredPage />);
  const alert = await screen.findByRole("alert");
  expect(alert.textContent).toBe("The starred moments could not be loaded (stopping). Check that the lavalier app is running.");
});
