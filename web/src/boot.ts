// Start-up: the saved appearance is applied before the shell is drawn, so a person who chose dark
// never sees a light frame. If the settings cannot be had (or are slow), the window follows the system.

import { api, type Settings } from "./api";
import { applyAppearance } from "./theme";

const WAIT_MS = 2000;

export async function start(mount: () => void): Promise<void> {
  applyAppearance("system");
  try {
    const timeout = new Promise<never>((_, reject) => setTimeout(() => reject(new Error("timed out")), WAIT_MS));
    const s = await Promise.race([api<Settings>("GET", "/api/settings"), timeout]);
    applyAppearance(s.appearance);
  } catch {
    // keep following the system
  }
  mount();
}
