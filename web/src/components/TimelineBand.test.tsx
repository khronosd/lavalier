import { cleanup, render, screen } from "@testing-library/preact";
import { afterEach, expect, test } from "vitest";
import type { ConversationView, DayView } from "../api";
import { parseHash } from "../router";
import { TimelineBand } from "./TimelineBand";

const at = (h: number, m = 0) => new Date(2026, 9, 23, h, m).getTime();
const conv = (id: string, start: number, end: number, over: Partial<ConversationView> = {}): ConversationView => ({
  conversation_id: id, start_ms: start, end_ms: end, speech_ms: Math.round((end - start) / 2), star_ms: [], pinned: false,
  label: null, clip_ids: [], lines: [], audio_available: true, ...over,
});
const view: DayView = {
  day: "2026-10-23", speech_ms: 0, noise_clips: 0, audio_until: null, audio_kept_for_good: false, pending_pages: null,
  conversations: [
    conv("c-1", at(8, 5), at(8, 22), { label: "Coffee with Dana" }),
    conv("c-2", at(9, 12), at(9, 41), { star_ms: [at(9, 14)] }),
    conv("c-3", at(9, 45), at(9, 50)),
  ],
  stars: [{ at_ms: at(9, 14), conversation_id: "c-2", quote: null }],
};

afterEach(cleanup);

test("the band draws hour lines and labels, a block per conversation linking to it, its label, and star dots", () => {
  const { container } = render(
    <TimelineBand view={view} selected="c-2" route={parseHash("#/day/2026-10-23?tab=audio&conv=c-1")} />,
  );
  expect(screen.getByRole("navigation", { name: "Timeline of the day" })).toBeTruthy();
  const links = screen.getAllByRole("link");
  expect(links.map((a) => a.getAttribute("aria-label")))
    .toEqual(["Coffee with Dana, 08:05 to 08:22", "09:12 to 09:41", "09:45 to 09:50"]);
  // a block jumps to its conversation; the open tab carries over, ?conv= gives way to ?at=
  expect(links.map((a) => a.getAttribute("href"))).toEqual([
    "#/day/2026-10-23?tab=audio&at=c-c-1", "#/day/2026-10-23?tab=audio&at=c-c-2", "#/day/2026-10-23?tab=audio&at=c-c-3",
  ]);
  expect(links.map((a) => a.classList.contains("selected"))).toEqual([false, true, false]);
  expect(links.map((a) => a.getAttribute("title"))).toEqual(["Coffee with Dana", "09:12 to 09:41", "09:45 to 09:50"]);
  // the third label sits too close to the second and is dropped (its text stays in the block's title)
  const labels = [...container.querySelectorAll(".tl-label")];
  expect(labels.map((l) => l.textContent)).toEqual(["Coffee with Dana", "09:12 to 09:41", "09:45 to 09:50"]);
  expect(labels.map((l) => l.classList.contains("dropped"))).toEqual([false, false, true]);
  expect(labels[1].classList.contains("selected")).toBe(true);
  expect(container.querySelectorAll(".tl-star")).toHaveLength(1);
  expect([...container.querySelectorAll(".tl-hour-label")].map((l) => l.textContent))
    .toEqual(["8:00", "9:00", "10:00", "11:00", "12:00", "13:00", "14:00"]);
  // the geometry travels as custom properties the stylesheet reads, never as colours or sizes in the markup
  expect(links[0].getAttribute("style")).toMatch(/^--left: [\d.]+%; --width: [\d.]+%; --h: \d+px;$/);
});

test("an empty day draws the axis from 8:00 to 20:00 with no blocks", () => {
  const { container } = render(
    <TimelineBand view={{ ...view, conversations: [], stars: [] }} selected={null} route={parseHash("#/day/2026-10-23")} />,
  );
  expect(screen.queryAllByRole("link")).toHaveLength(0);
  const hours = [...container.querySelectorAll(".tl-hour-label")].map((l) => l.textContent);
  expect(hours[0]).toBe("8:00");
  expect(hours[hours.length - 1]).toBe("20:00");
  expect(container.querySelector(".tl-axis")).toBeTruthy();
});
