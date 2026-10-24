import { render, screen } from "@testing-library/preact";
import { expect, test } from "vitest";
import type { DaySummary } from "../api";
import { parseHash } from "../router";
import { Shell } from "./Shell";

const days: DaySummary[] = [
  { day: "2026-10-24", speech_ms: 60_000, conversations: 1, stars: 0, noise_clips: 0 },
  { day: "2026-10-23", speech_ms: 3 * 3_600_000 + 16 * 60_000, conversations: 41, stars: 2, noise_clips: 3 },
];

test("the sidebar lists the five sections, the days under Journal, and Settings", () => {
  render(<Shell route={parseHash("#/day/2026-10-23")} days={days} today="2026-10-24"><p>page</p></Shell>);
  for (const name of ["Today", "Journal", "Starred", "Search", "Insights", "Settings"]) {
    expect(screen.getByRole("link", { name: new RegExp(`^${name}`) })).toBeTruthy();
  }
  const current = screen.getByRole("link", { current: "page" });
  expect(current.getAttribute("href")).toBe("#/day/2026-10-23");
  // the Journal section is marked as holding the open page; there is one "Journal" label, no heading
  expect(screen.getByRole("link", { current: true }).textContent).toMatch(/^Journal/);
  expect(screen.getAllByText("Journal")).toHaveLength(1);
  const listed = screen.getAllByRole("link").filter((a) => a.classList.contains("day")).map((a) => a.getAttribute("href"));
  expect(listed).toEqual(["#/day/2026-10-24", "#/day/2026-10-23"]);
  expect(current.textContent).toBe("Friday 233 h 16 min★2");
  expect(screen.getByRole("link", { name: /^Saturday 24/ }).textContent).toContain("today");
  expect(screen.getByText("page")).toBeTruthy();
});

test("an empty journal says so", () => {
  render(<Shell route={parseHash("#/today")} days={[]} today="2026-10-24"><p>page</p></Shell>);
  expect(screen.getByText("No days yet")).toBeTruthy();
  expect(screen.getByRole("link", { current: "page" }).getAttribute("href")).toBe("#/today");
});
