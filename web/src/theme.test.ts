import { afterEach, expect, test, vi } from "vitest";
import { applyAppearance } from "./theme";

type Listener = (e: { matches: boolean }) => void;

function fakeMedia(initial: boolean) {
  const listeners = new Set<Listener>();
  const mql = {
    matches: initial,
    addEventListener: (_: string, l: Listener) => listeners.add(l),
    removeEventListener: (_: string, l: Listener) => listeners.delete(l),
  };
  vi.stubGlobal("matchMedia", vi.fn().mockReturnValue(mql));
  return {
    listeners,
    set(dark: boolean) {
      mql.matches = dark;
      listeners.forEach((l) => l({ matches: dark }));
    },
  };
}

afterEach(() => vi.unstubAllGlobals());

test("applyAppearance sets data-theme", () => {
  applyAppearance("dark");
  expect(document.documentElement.dataset.theme).toBe("dark");
  applyAppearance("light");
  expect(document.documentElement.dataset.theme).toBe("light");
});

test("system follows prefers-color-scheme and updates on change", () => {
  const media = fakeMedia(true);
  applyAppearance("system");
  expect(document.documentElement.dataset.theme).toBe("dark");
  media.set(false);
  expect(document.documentElement.dataset.theme).toBe("light");
});

test("leaving system stops following the system setting", () => {
  const media = fakeMedia(false);
  applyAppearance("system");
  applyAppearance("dark");
  expect(media.listeners.size).toBe(0);
  media.set(false);
  expect(document.documentElement.dataset.theme).toBe("dark");
});
