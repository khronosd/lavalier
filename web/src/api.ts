// The loopback API client. The window is opened with ?token=<token> once; the token is kept in
// memory only and every /api/ request carries it as a bearer header. Types mirror the Python
// JSON exactly (journal.to_json, search.Hit, app.snapshot, settings.read_settings).

let token: string | null = null;

export class ApiError extends Error {
  constructor(public readonly status: number, message: string, public readonly field?: string) {
    super(message);
    this.name = "ApiError";
  }
}

/** Read ?token= from the URL, keep it, and strip it from the address (other params stay). */
export function initToken(): string | null {
  const params = new URLSearchParams(window.location.search);
  const found = params.get("token");
  if (found !== null) {
    token = found;
    params.delete("token");
    const search = params.toString();
    const url = window.location.pathname + (search ? `?${search}` : "") + window.location.hash;
    window.history.replaceState(window.history.state, "", url);
  }
  return token;
}

function headers(json: boolean): Headers {
  const h = new Headers();
  if (token !== null) h.set("Authorization", `Bearer ${token}`);
  if (json) h.set("Content-Type", "application/json");
  return h;
}

async function failure(res: Response): Promise<ApiError> {
  let message = `HTTP ${res.status}`;
  let field: string | undefined;
  try {
    const body = await res.json();
    if (body && typeof body.error === "string") message = body.error;
    if (body && typeof body.field === "string") field = body.field;
  } catch {
    // not JSON: keep the status
  }
  return new ApiError(res.status, message, field);
}

export async function api<T>(method: string, path: string, body?: unknown): Promise<T> {
  const hasBody = body !== undefined;
  const res = await fetch(path, {
    method,
    headers: headers(hasBody),
    body: hasBody ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw await failure(res);
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T; // an empty 2xx body is undefined
}

/** What a failed request means to the person reading the window, and what to do about it. */
export function explainError(e: unknown, what: string): string {
  if (e instanceof ApiError && e.status === 401) {
    return "This window could not sign in to the lavalier app. Reopen the window from the app.";
  }
  const why = e instanceof Error ? e.message : String(e);
  return `${what} could not be loaded (${why}). Check that the lavalier app is running, then reload.`;
}

/** The clip's audio as an object URL; the caller revokes it with URL.revokeObjectURL. */
export async function fetchAudioBlobUrl(clipId: string): Promise<string> {
  const res = await fetch(`/api/audio/${encodeURIComponent(clipId)}.m4a`, { method: "GET", headers: headers(false) });
  if (!res.ok) throw await failure(res);
  return URL.createObjectURL(await res.blob());
}

// --- the JSON the server sends ---

/** An ISO date, "2026-10-24". */
export type IsoDate = string;

export interface DaySummary {
  day: IsoDate;
  speech_ms: number;
  conversations: number;
  stars: number;
  noise_clips: number;
}

export interface Line {
  at_ms: number;
  text: string;
  clip_id: string;
  seq: number;
}

export interface StarView {
  at_ms: number;
  conversation_id: string | null;
  quote: string | null;
}

export interface ConversationView {
  conversation_id: string;
  start_ms: number;
  end_ms: number;
  speech_ms: number;
  star_ms: number[];
  pinned: boolean;
  label: string | null;
  clip_ids: string[];
  lines: Line[];
  audio_available: boolean;
}

export interface DayView {
  day: IsoDate;
  speech_ms: number;
  conversations: ConversationView[];
  stars: StarView[];
  noise_clips: number;
  audio_until: IsoDate | null;
  audio_kept_for_good: boolean;
  pending_pages: number | null;
}

/** One entry of GET /api/starred. */
export interface StarredEntry {
  day: IsoDate;
  star: StarView;
}

export interface Hit {
  day: IsoDate;
  conversation_id: string | null;
  clip_id: string;
  seq: number;
  at_ms: number;
  snippet: string;
}

export interface DeviceStatus {
  read_at_ms: number;
  has_all_fields: boolean;
  recording_state: "NOT_RECORDING" | "LISTENING" | "RECORDING" | string;
  oldest_page: number;
  newest_page: number;
  soc: number;
  current_ma: number;
  usb_state: string;
  firmware_ver: string;
  storage_instance: number;
  pages_waiting: number;
  source: string;
  charger_signal: string;
  age_s: number;
}

export interface SyncRun {
  id: number;
  started_ms: number;
  ended_ms: number | null;
  outcome: string;
  reason: string;
  pages: number;
  messages: number;
  capture_id: number | null;
  muted_by: string | null;
  unmute: string;
  error: string | null;
}

/** SyncReport.to_json_dict(): what one sync did. */
export interface SyncReportJson {
  outcome: "not-in-range" | "locked" | "refused" | "skipped" | "dry-run" | "drained" | "error" | string;
  reason: string;
  pages: number;
  messages: number;
  capture: string | null;
  capture_complete: boolean;
  muted_by: string | null;
  unmute: string;
  status: Omit<DeviceStatus, "pages_waiting" | "source" | "charger_signal" | "age_s"> | null;
  charger_signal: string;
  error: string | null;
  orphans: number;
}

/** POST /api/sync. */
export interface SyncActionResult {
  sync: SyncReportJson;
  /** "scheduled" when processing what came in has started, null when nothing came in. */
  process: string | null;
}

/** POST /api/mute and /api/unmute. */
export interface ToggleResult {
  ok: boolean;
  state: string | null;
  error: string | null;
}

/** The part of the snapshot the pipeline computes; status-live returns it after its read. */
export type StatusSummary = Omit<Status, "busy" | "next_poll_ms" | "app">;

/** POST /api/status-live: a read-only status read, then the summary whether or not the read worked. */
export interface LiveResult {
  ok: boolean;
  error: string | null;
  summary: StatusSummary;
}

/** GET /api/status: the app's snapshot(). */
export interface Status {
  days_with_clips: IsoDate[];
  pending_transcripts: number;
  failed_clips: number;
  audio_bytes: number;
  capture_bytes: number;
  next_deletion: IsoDate | null;
  last_import: string | null;
  pinned: string[];
  long_presses: number;
  double_presses: number;
  /** The last processing report, as a JSON string. */
  last_process: string | null;
  device: DeviceStatus | null;
  last_sync: SyncRun | null;
  unmute_pending_since_ms: number | null;
  muted_by_recorder_since_ms: number | null;
  muted_by_owner_since_ms: number | null;
  busy: boolean;
  next_poll_ms: number;
  app: { version: string; pid: number; started_ms: number };
}

export type Appearance = "system" | "light" | "dark";

/** GET /api/settings: settings.read_settings. PUT takes a partial of the editable fields. */
export interface Settings {
  pendant_address: string;
  retention_days: number;
  poll_interval_s: number;
  drain_pages_threshold: number;
  drain_after_hours: number;
  require_firmware: string;
  whisper_language: string;
  appearance: Appearance;
  window_size: string;
  readonly: { state_root: string; whisper_model: string; bundle_id: string };
}

export type SettingsPatch = Partial<Omit<Settings, "readonly">>;
