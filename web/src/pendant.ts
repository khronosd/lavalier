// The pendant card's words and rules. The card is read-only on device state: what it says comes
// from the latest status read only, never from what an action was meant to do.

import { ApiError, type DeviceStatus, type Status, type SyncActionResult, type SyncRun, type ToggleResult } from "./api";
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

export interface RefreshGate {
  /** The page is not hidden (minimised, another Space). */
  visible: boolean;
  /** The window is in front: WKWebView stays "visible" behind other windows. */
  focused: boolean;
  /** The app or this card is already using the pendant. */
  busy: boolean;
}

/** The 60-second live read: only while the window is in front, nothing else is using the pendant, and
 * the last sync found it in range (an absent pendant is left alone until something changes). */
export function shouldRefresh(status: Status | null, { visible, focused, busy }: RefreshGate): boolean {
  if (!visible || !focused || busy) return false;
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
  if (e instanceof ApiError && e.status === 504) return "The pendant took too long to answer";
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

/** Sync now, Mute and Unmute, as the pill and the card name them. */
export type PendantAction = "sync" | "mute" | "unmute";

const BUSY_WORDS: Record<PendantAction, string> = { sync: "Syncing…", mute: "Muting…", unmute: "Unmuting…" };

/** The pill's state word: what is in flight first, "Not set" without an address, else the lamp's word. */
export function pillWord(lamp: LampState, noAddress: boolean, busyWith: PendantAction | null): string {
  if (busyWith) return BUSY_WORDS[busyWith];
  if (noAddress) return "Not set";
  return stateText(lamp);
}

/** "787 pages", "1 page", "12k pages" above 9,999; "" with none. */
export function pagesShort(pages: number): string {
  if (pages <= 0) return "";
  if (pages > 9999) return `${Math.round(pages / 1000)}k pages`;
  return pages === 1 ? "1 page" : `${pages} pages`;
}

/** The pill's accessible name: "Pendant: listening, battery 94 percent, 787 pages waiting". */
export function pillLabel(status: Status | null, noAddress: boolean, busyWith: PendantAction | null): string {
  const lamp = noAddress ? "unknown" : lampState(status);
  const word = pillWord(lamp, noAddress, busyWith);
  const parts = [word.charAt(0).toLowerCase() + word.slice(1)];
  const device = lamp === "unknown" ? null : status?.device;
  if (device) {
    parts.push(`battery ${device.soc} percent`);
    const pages = pagesShort(device.pages_waiting);
    if (pages) parts.push(`${pages} waiting`);
  }
  return `Pendant: ${parts.join(", ")}`;
}

/** What the last sync did and when: "Drained 212 pages at 09:31", "Nothing to drain at 09:31", "Pendant not in
 *  range at 09:31", or its error; "No sync yet" with none. The words are syncResultLine's. */
export function syncRunLine(run: SyncRun | null): string {
  if (!run) return "No sync yet";
  const when = hm(run.started_ms);
  switch (run.outcome) {
    case "drained":
      return run.pages > 0 ? `Drained ${run.pages} ${run.pages === 1 ? "page" : "pages"} at ${when}` : `Nothing to drain at ${when}`;
    case "skipped":
      return `Nothing to drain at ${when}`;
    case "not-in-range":
      return `Pendant not in range at ${when}`;
    case "locked":
      return `Another process was using the pendant at ${when}`;
    default:
      return `${run.error || run.reason || `Sync ended: ${run.outcome}`} at ${when}`;
  }
}
