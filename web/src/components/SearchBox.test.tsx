import { cleanup, fireEvent, render, screen } from "@testing-library/preact";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { parseHash } from "../router";
import { SearchBox } from "./SearchBox";

beforeEach(() => { window.location.hash = "#/today"; });
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  window.location.hash = "";
});

test("Enter searches at once", () => {
  render(<SearchBox route={parseHash("#/today")} />);
  const box = screen.getByRole("searchbox", { name: "Search every day" });
  fireEvent.input(box, { target: { value: "one two" } });
  fireEvent.keyDown(box, { key: "Enter" });
  expect(window.location.hash).toBe("#/search?q=one+two");
});

test("a pause of 300 ms after typing searches", () => {
  vi.useFakeTimers();
  render(<SearchBox route={parseHash("#/today")} />);
  const box = screen.getByRole("searchbox", { name: "Search every day" });
  fireEvent.input(box, { target: { value: "thr" } });
  vi.advanceTimersByTime(200);
  fireEvent.input(box, { target: { value: "three" } });
  vi.advanceTimersByTime(299);
  expect(window.location.hash).toBe("#/today");
  vi.advanceTimersByTime(1);
  expect(window.location.hash).toBe("#/search?q=three");
});

test("the field shows the query of the search page, and Clear empties it", () => {
  window.location.hash = "#/search?q=three";
  render(<SearchBox route={parseHash("#/search?q=three")} />);
  const box = screen.getByRole("searchbox", { name: "Search every day" }) as HTMLInputElement;
  expect(box.value).toBe("three");
  fireEvent.click(screen.getByRole("button", { name: "Clear search" }));
  expect(box.value).toBe("");
  expect(window.location.hash).toBe("#/search");
});

test("no Clear control while the field is empty", () => {
  render(<SearchBox route={parseHash("#/today")} />);
  expect(screen.queryByRole("button", { name: "Clear search" })).toBeNull();
});
