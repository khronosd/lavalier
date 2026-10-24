// The pendant card's words and rules. The card is read-only on device state: what it says comes
// from the latest status read only, never from what an action was meant to do.

import { ApiError, type DeviceStatus, type Status, type SyncActionResult, type ToggleResult } from "./api";
import { age, hm } from "./format";

export type LampState = "listening" | "recording" | "muted" | "unknown";

/** Seconds of speech one page holds. */
const SECONDS_PER_PAGE = 1.5;

/** The lamp mirrors the pendant's LED, from the latest full read only. */
export function lampState(status: Status | null): LampState {
  const d = status?.device;
  if (!d || !d.has_all_fields) return "unknown"; // a partial read decodes as NOT_RECORDING and proves nothing
  switch (d.recording_state) {
    case "LISTENING":
      return "listening";
    case "RECORDING":
      return "recording";
    case "NOT_RECORDING":
      return "muted";
    default:
      return "unknown";
  }
}

const STATE_TEXT: Record<LampState, string> = {
  listening: "Listening", recording: "Recording", muted: "Muted", unknown: "No reading yet",
};

export function stateText(lamp: LampState): string {
  return STATE_TEXT[lamp];
}

/** Sync, Mute and Unmute wait while the app is busy with the pendant or a request is in flight. */
export function buttonsDisabled(status: Status | null, inflight: boolean): boolean {
  return status === null || status.busy || inflight;
}

/** The 60-second live read: only while the window is seen, nothing else is using the pendant, and
 * the last sync found it in range (an absent pendant is left alone until something changes). */
export function shouldRefresh(status: Status | null, visible: boolean, busy: boolean): boolean {
  if (!visible || busy) return false;
  return status?.last_sync?.outcome !== "not-in-range";
}

/** "787 pages waiting, about 20 minutes of speech"; "1 page waiting"; "" with none. */
export function pagesSentence(pages: number): string {
  if (pages <= 0) return "";
  const head = pages === 1 ? "1 page waiting" : `${pages} pages waiting`;
  const minutes = Math.round((pages * SECONDS_PER_PAGE) / 60);
  if (minutes < 1) return head;
  return `${head}, about ${minutes} ${minutes === 1 ? "minute" : "minutes"} of speech`;
}

const CHARGER_WORDS: Record<string, string> = {
  current: "charging", "usb-cdc": "on the charger", "quiet-polls": "near the Mac",
};

/** "Battery 94%, charging"; the charger words are left out when there is no signal. */
export function batteryLine(device: DeviceStatus): string {
  const words = CHARGER_WORDS[device.charger_signal];
  return words ? `Battery ${device.soc}%, ${words}` : `Battery ${device.soc}%`;
}

/** What a sync did, in one line. */
export function syncResultLine(result: SyncActionResult): string {
  const s = result.sync;
  switch (s.outcome) {
    case "drained":
      if (s.pages > 0) return `Drained ${s.pages} ${s.pages === 1 ? "page" : "pages"}`;
      return "Nothing to drain";
    case "skipped":
      return "Nothing to drain";
    case "not-in-range":
      return "Pendant not in range";
    case "locked":
      return "Another process is using the pendant";
    default:
      return s.error || s.reason || `Sync ended: ${s.outcome}`;
  }
}

const TOGGLE_STATE: Record<string, string> = {
  NOT_RECORDING: "Muted", LISTENING: "Listening", RECORDING: "Recording",
};

/** What a mute or unmute did, in one line: the state read back, or the error. */
export function toggleResultLine(result: ToggleResult): string {
  if (!result.ok) return result.error ?? `Not confirmed: ${result.state ?? "no reading"}`;
  return TOGGLE_STATE[result.state ?? ""] ?? result.state ?? "Done";
}

/** A request the app refused or could not answer. */
export function requestErrorLine(e: unknown): string {
  if (e instanceof ApiError && e.status === 409) return "The pendant is busy, try again in a moment";
  if (e instanceof ApiError && e.status === 503) return "The app is stopping";
  return e instanceof Error ? e.message : String(e);
}

/** The app's words when config.toml has no pendant_address. */
export function isNoAddress(text: string | null | undefined): boolean {
  return !!text && text.includes("set pendant_address");
}

/** "Unmute pending since 09:05, hold the button or press Unmute", or "" with none pending. */
export function pendingUnmuteLine(status: Status | null): string {
  const since = status?.unmute_pending_since_ms;
  if (!since) return "";
  return `Unmute pending since ${hm(since)}, hold the button or press Unmute`;
}

/** "Listening as of 2 min ago, battery 94%": the last full read in one line, for Settings. */
export function lastReadLine(status: Status | null): string {
  const d = status?.device;
  if (!d || !d.has_all_fields) return "No reading yet";
  return `${stateText(lampState(status))} ${age(d.age_s)}, battery ${d.soc}%`;
}
