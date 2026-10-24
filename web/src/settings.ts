// The Settings rules the window can check before asking the app. They mirror src/lavalier/settings.py
// (_check_value); the app still has the last word and its message is shown when it disagrees.

import type { SettingsPatch } from "./api";

export interface FieldProblem {
  field: string;
  message: string;
}

const WINDOW_SIZE = /^\d{3,4}x\d{3,4}$/;
const APPEARANCES = ["system", "light", "dark"];

/** Whole minutes or part of one, typed by a person, as the seconds the app stores; NaN when not a number. */
export function minutesToSeconds(text: string): number {
  const t = text.trim();
  if (t === "") return Number.NaN;
  const n = Number(t);
  return Number.isFinite(n) ? Math.round(n * 60) : Number.NaN;
}

/** 300 -> "5", 90 -> "1.5". */
export function secondsToMinutes(seconds: number): string {
  return String(Math.round((seconds / 60) * 100) / 100);
}

const isWhole = (n: unknown): n is number => typeof n === "number" && Number.isInteger(n);

/** The first rule a patch breaks, or null. Mirrors the server: retention >= 0, poll >= 60 s, window size, appearance. */
export function validateLocally(patch: SettingsPatch): FieldProblem | null {
  const bad = (field: string, message: string): FieldProblem => ({ field, message });
  if ("retention_days" in patch) {
    const v = patch.retention_days;
    if (!isWhole(v) || v < 0) return bad("retention_days", "Days must be a whole number, 0 or more.");
  }
  if ("poll_interval_s" in patch) {
    const v = patch.poll_interval_s;
    if (typeof v !== "number" || Number.isNaN(v)) return bad("poll_interval_s", "The poll interval must be a number of minutes.");
    if (v < 60) return bad("poll_interval_s", "The poll interval must be at least 1 minute.");
  }
  for (const [field, label] of [["drain_pages_threshold", "Pages"], ["drain_after_hours", "Hours"]] as const) {
    if (field in patch && !isWhole(patch[field])) return bad(field, `${label} must be a whole number.`);
  }
  if ("window_size" in patch && !WINDOW_SIZE.test(String(patch.window_size))) {
    return bad("window_size", "The window size must look like 1120x720.");
  }
  if ("appearance" in patch && !APPEARANCES.includes(String(patch.appearance))) {
    return bad("appearance", "Appearance must be System, Light or Dark.");
  }
  return null;
}
