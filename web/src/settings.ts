// The Settings rules the window can check before asking the app. They mirror src/lavalier/settings.py
// (_check_value); the app still has the last word and its message is shown when it disagrees.

import type { SettingsPatch } from "./api";

export interface FieldProblem {
  field: string;
  message: string;
}

const WINDOW_SIZE = /^\d{3,4}x\d{3,4}$/;
const APPEARANCES = ["system", "light", "dark"];
const LANGUAGE = /^[a-z]{2,3}$/;
const MAX_RETENTION_DAYS = 36500;
export const PROVIDERS = ["", "ollama", "anthropic", "openai", "google"];

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

/** The first rule a patch breaks, or null. Mirrors the server: retention 0 to 36500 days, poll >= 60 s,
 * at least 1 page, hours >= 0, a 2 or 3 letter language code, window size, appearance; a known insights
 * provider, a base URL that is empty or http(s) (not a bare scheme), any model name, auto on or off. */
export function validateLocally(patch: SettingsPatch): FieldProblem | null {
  const bad = (field: string, message: string): FieldProblem => ({ field, message });
  if ("retention_days" in patch) {
    const v = patch.retention_days;
    if (!isWhole(v) || v < 0 || v > MAX_RETENTION_DAYS) {
      return bad("retention_days", `Days must be a whole number from 0 to ${MAX_RETENTION_DAYS}.`);
    }
  }
  if ("poll_interval_s" in patch) {
    const v = patch.poll_interval_s;
    if (typeof v !== "number" || Number.isNaN(v)) return bad("poll_interval_s", "The poll interval must be a number of minutes.");
    if (v < 60) return bad("poll_interval_s", "The poll interval must be at least 1 minute.");
  }
  for (const [field, label, min] of [["drain_pages_threshold", "Pages", 1], ["drain_after_hours", "Hours", 0]] as const) {
    if (!(field in patch)) continue;
    const v = patch[field];
    if (!isWhole(v) || v < min) return bad(field, `${label} must be a whole number, ${min} or more.`);
  }
  if ("whisper_language" in patch && !LANGUAGE.test(String(patch.whisper_language))) {
    return bad("whisper_language", "The language must be a 2 or 3 letter code, like en.");
  }
  if ("window_size" in patch && !WINDOW_SIZE.test(String(patch.window_size))) {
    return bad("window_size", "The window size must look like 1120x720.");
  }
  if ("appearance" in patch && !APPEARANCES.includes(String(patch.appearance))) {
    return bad("appearance", "Appearance must be System, Light or Dark.");
  }
  if ("insights_provider" in patch && !PROVIDERS.includes(String(patch.insights_provider))) {
    return bad("insights_provider", "Choose one of the providers listed.");
  }
  if ("insights_base_url" in patch) {
    const v = patch.insights_base_url;
    const ok = typeof v === "string" &&
      (v === "" || (/^https?:\/\//.test(v) && v !== "http://" && v !== "https://"));
    if (!ok) return bad("insights_base_url", "The base URL must be empty or start with http:// or https://.");
  }
  if ("insights_model" in patch && typeof patch.insights_model !== "string") {
    return bad("insights_model", "The model must be a name.");
  }
  if ("insights_auto" in patch && typeof patch.insights_auto !== "boolean") {
    return bad("insights_auto", "Automatic generation is either on or off.");
  }
  return null;
}
