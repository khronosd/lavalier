import { cleanup, fireEvent, render, screen, within } from "@testing-library/preact";
import { afterEach, expect, test, vi } from "vitest";
import type { DaySummary } from "../api";
import { status } from "../pendant.fixtures";
import { parseHash } from "../router";
import type { PendantStatus } from "../usePendantStatus";
import { Frame } from "./Frame";
import { Shell } from "./Shell";

const days: DaySummary[] = [
  { day: "2026-10-24", speech_ms: 60_000, conversations: 1, stars: 0, noise_clips: 0 },
  { day: "2026-10-23", speech_ms: 3 * 3_600_000 + 16 * 60_000, conversations: 41, stars: 2, noise_clips: 3 },
  { day: "2026-09-30", speech_ms: 5 * 60_000, conversations: 1, stars: 0, noise_clips: 0 },
];

const pendant: PendantStatus = {
  status: status(), inflight: false, result: null, liveError: null, noAddress: false, unreachable: false,
  busyWith: null, run: async () => undefined,
};

/** matchMedia as a window of the given width would answer it; jsdom has none. */
function windowWidth(px: number) {
  vi.stubGlobal("matchMedia", vi.fn((query: string) => {
    const max = /max-width:\s*(\d+)px/.exec(query);
    return { matches: max ? px <= Number(max[1]) : false, addEventListener: () => undefined, removeEventListener: () => undefined };
  }));
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test("the sidebar lists the four sections, the days under their month, and Settings at the bottom", () => {
  render(<Shell route={parseHash("#/day/2026-10-23")} days={days} today="2026-10-24"><p>page</p></Shell>);
  const nav = screen.getByRole("navigation", { name: "Sidebar" });
  expect(within(nav).getAllByRole("link").map((a) => a.getAttribute("href"))).toEqual([
    "#/today", "#/starred", "#/search", "#/insights", "#/day/2026-10-24", "#/day/2026-10-23", "#/day/2026-09-30",
    "#/settings/general",
  ]);
  expect(within(nav).getAllByText(/^(October|September)$/).map((el) => el.textContent)).toEqual(["October", "September"]);
  expect(screen.queryByText("Journal")).toBeNull();
  const current = screen.getByRole("link", { current: "page" });
  expect(current.getAttribute("href")).toBe("#/day/2026-10-23");
  expect(current.textContent!.startsWith("Friday 23")).toBe(true);
  const stars = current.querySelector(".nav-count .stars")!;
  expect(stars.getAttribute("aria-label")).toBe("2 starred");
  expect(stars.textContent).toBe("2");
  expect(current.querySelector(".nav-len")!.textContent).toBe("3 h 16 min");
  expect(screen.getByRole("link", { name: /^Saturday 24/ }).querySelector(".nav-len")!.textContent).toBe("today");
  expect(screen.getByRole("link", { name: /^Saturday 24/ }).querySelector(".stars")).toBeNull();
  expect(screen.getByText("page")).toBeTruthy();
});

test("a day from another year names it in the month head", () => {
  const old: DaySummary[] = [{ day: "2025-12-31", speech_ms: 60_000, conversations: 1, stars: 0, noise_clips: 0 }];
  render(<Shell route={parseHash("#/today")} days={old} today="2026-10-24"><p>page</p></Shell>);
  expect(screen.getByText("December 2025")).toBeTruthy();
});

test("an empty journal says so", () => {
  render(<Shell route={parseHash("#/today")} days={[]} today="2026-10-24"><p>page</p></Shell>);
  expect(screen.getByText("No days yet")).toBeTruthy();
  expect(screen.getByRole("link", { current: "page" }).getAttribute("href")).toBe("#/today");
});

test("the Insights link shows how many days are to do, muted like the day counts", () => {
  render(<Shell route={parseHash("#/today")} days={days} today="2026-10-24" insightsTodo={3}><p>page</p></Shell>);
  const link = screen.getByRole("link", { name: /^Insights/ });
  expect(link.querySelector(".nav-count")!.textContent).toBe("3 to do");
  cleanup();
  render(<Shell route={parseHash("#/today")} days={days} today="2026-10-24" insightsTodo={0}><p>page</p></Shell>);
  expect(screen.getByRole("link", { name: /^Insights/ }).querySelector(".nav-count")).toBeNull();
});

test("a page's frame: the toolbar with its title group, controls, actions, the search field and the pendant pill, then the panes", () => {
  render(
    <Shell route={parseHash("#/starred")} days={days} today="2026-10-24" pendant={pendant}>
      <Frame toolbar={{ title: "Starred", subtitle: "11 moments", children: <span>controls</span>, actions: <button type="button">Act</button> }}
        list={<p>rows</p>} listLabel="Starred moments" inspector={<p>about</p>} inspectorLabel="This moment">
        <p>content</p>
      </Frame>
    </Shell>,
  );
  const toolbar = screen.getByRole("toolbar");
  expect(within(toolbar).getByText("Starred")).toBeTruthy();
  expect(within(toolbar).getByText("11 moments")).toBeTruthy();
  expect(within(toolbar).getByText("controls")).toBeTruthy();
  expect(within(toolbar).getByRole("button", { name: "Act" })).toBeTruthy();
  expect(within(toolbar).getByRole("searchbox", { name: "Search every day" })).toBeTruthy();
  expect(within(toolbar).getByRole("button", { name: /^Pendant: listening/ })).toBeTruthy();
  expect(within(toolbar).queryByRole("button", { name: /inspector/ })).toBeNull(); // wide enough: no toggle
  expect(within(screen.getByRole("region", { name: "Starred moments" })).getByText("rows")).toBeTruthy();
  expect(within(screen.getByRole("main")).getByText("content")).toBeTruthy();
  expect(within(screen.getByRole("complementary", { name: "This moment" })).getByText("about")).toBeTruthy();
  // landmarks in reading order: sidebar, toolbar, list, content, inspector
  const order = [...document.querySelectorAll("nav, [role=toolbar], section, main, aside")].map((el) => el.tagName.toLowerCase());
  expect(order).toEqual(["nav", "div", "section", "main", "aside"]);
});

test("without a pendant the toolbar draws no pill; a page without a list or an inspector has neither pane", () => {
  render(
    <Shell route={parseHash("#/starred")} days={days} today="2026-10-24">
      <Frame toolbar={{ title: "Starred" }}><p>content</p></Frame>
    </Shell>,
  );
  expect(screen.queryByRole("button", { name: /^Pendant/ })).toBeNull();
  expect(screen.queryByRole("region")).toBeNull();
  expect(screen.queryByRole("complementary")).toBeNull();
  expect(screen.getByRole("main").textContent).toBe("content");
});

test("the Search page puts the field in the title group and nowhere else", () => {
  render(
    <Shell route={parseHash("#/search?q=retention")} days={days} today="2026-10-24">
      <Frame toolbar={{ search: "title" }}><p>content</p></Frame>
    </Shell>,
  );
  const boxes = screen.getAllByRole("searchbox", { name: "Search every day" });
  expect(boxes).toHaveLength(1);
  expect((boxes[0] as HTMLInputElement).value).toBe("retention");
  expect(boxes[0].closest(".search-box")!.classList.contains("wide")).toBe(true);
});

test("the toolbar's toggle hides the sidebar and brings it back", () => {
  render(
    <Shell route={parseHash("#/starred")} days={days} today="2026-10-24">
      <Frame toolbar={{ title: "Starred" }}><p>content</p></Frame>
    </Shell>,
  );
  const shell = document.querySelector(".shell")!;
  expect(shell.classList.contains("sidebar-hidden")).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "Hide sidebar" }));
  expect(shell.classList.contains("sidebar-hidden")).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Show sidebar" }));
  expect(shell.classList.contains("sidebar-hidden")).toBe(false);
});

test("focusInspector opens the inspector and moves focus onto it", () => {
  render(
    <Shell route={parseHash("#/day/2026-10-23")} days={days} today="2026-10-24">
      <Frame toolbar={{ title: "Day" }} inspector={<p>insight</p>} inspectorLabel="Insights" focusInspector="#/day/2026-10-23?tab=insights">
        <p>content</p>
      </Frame>
    </Shell>,
  );
  const aside = screen.getByRole("complementary", { name: "Insights" });
  expect(document.activeElement).toBe(aside);
});

test("below 1216 px the inspector folds into a popover behind a toolbar button", () => {
  windowWidth(1100);
  render(
    <Shell route={parseHash("#/day/2026-10-23")} days={days} today="2026-10-24">
      <Frame toolbar={{ title: "Day" }} inspector={<p>insight</p>} inspectorLabel="Insights"><p>content</p></Frame>
    </Shell>,
  );
  expect(screen.queryByRole("complementary")).toBeNull();
  expect(document.querySelector(".shell")!.classList.contains("sidebar-hidden")).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: "Show inspector" }));
  const aside = screen.getByRole("complementary", { name: "Insights" });
  expect(aside.closest(".popover")).toBeTruthy();
  expect(aside.textContent).toBe("insight");
  fireEvent.click(screen.getByRole("button", { name: "Hide inspector" }));
  expect(screen.queryByRole("complementary")).toBeNull();
});

test("below 1000 px the sidebar waits behind its toggle and opens as an overlay with a scrim", () => {
  windowWidth(900);
  render(
    <Shell route={parseHash("#/starred")} days={days} today="2026-10-24">
      <Frame toolbar={{ title: "Starred" }}><p>content</p></Frame>
    </Shell>,
  );
  const shell = document.querySelector(".shell")!;
  expect(shell.classList.contains("narrow")).toBe(true);
  expect(shell.classList.contains("sidebar-overlay")).toBe(false);
  expect(document.querySelector(".scrim")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Show sidebar" }));
  expect(shell.classList.contains("sidebar-overlay")).toBe(true);
  fireEvent.click(document.querySelector(".shell > .scrim")!);
  expect(shell.classList.contains("sidebar-overlay")).toBe(false);
});
