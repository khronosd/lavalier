// Light, dark, or following the system. Sets data-theme on <html>; tokens.css does the rest.

import type { Appearance } from "./api";

const QUERY = "(prefers-color-scheme: dark)";
let stopFollowing: (() => void) | null = null;

function set(theme: "light" | "dark"): void {
  document.documentElement.dataset.theme = theme;
}

export function applyAppearance(mode: Appearance): void {
  stopFollowing?.();
  stopFollowing = null;
  if (mode !== "system") {
    set(mode);
    return;
  }
  const media = window.matchMedia(QUERY);
  const onChange = (e: { matches: boolean }) => set(e.matches ? "dark" : "light");
  onChange(media);
  media.addEventListener("change", onChange);
  stopFollowing = () => media.removeEventListener("change", onChange);
}
