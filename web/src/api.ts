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

export const UNAUTHORISED = "The window was opened without its key. Close it and run lavalier window again.";

/** What a failed request means to the person reading the window, and what to do about it. */
export function explainError(e: unknown, what: string): string {
  // the key lives in memory only: reloading the page would drop it, so never suggest that
  if (e instanceof ApiError && e.status === 401) return UNAUTHORISED;
  const why = e instanceof Error ? e.message : String(e);
  return `${what} could not be loaded (${why}). Check that the lavalier app is running.`;
}

/** The clip's audio as an object URL; the caller revokes it with URL.revokeObjectURL. */
export async function fetchAudioBlobUrl(clipId: string): Promise<string> {
  const res = await fetch(`/api/audio/${encodeURIComponent(clipId)}.m4a`, { method: "GET", headers: headers(false) });
  if (!res.ok) throw await failure(res);
  return URL.createObjectURL(await res.blob());
}

/** A failed job: its error text as the message. */
export class JobError extends Error {
  constructor(public readonly job: Job) {
    super(job.error ?? "The job failed.");
    this.name = "JobError";
  }
}

export const POLL_CAP_MS = 30 * 60_000;

function abortError(): DOMException {
  return new DOMException("The polling was cancelled.", "AbortError");
}

/** Wait `ms`, or reject at once when `signal` aborts. */
export function pause(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(abortError());
    const timer = setTimeout(() => { signal?.removeEventListener("abort", stop); resolve(); }, ms);
    function stop() { clearTimeout(timer); reject(abortError()); }
    signal?.addEventListener("abort", stop, { once: true });
  });
}

/** Ask GET /api/jobs/<id> now and then every `every` ms until the job is done (resolves with it) or
 *  failed (rejects with a JobError carrying its error text). Aborting `signal` stops it with an
 *  AbortError; past `cap` (30 minutes by default; 0 for none) it gives up. */
export async function pollJob(id: string, { every = 1000, signal, cap = POLL_CAP_MS }:
  { every?: number; signal?: AbortSignal; /** ms; 0 asks until the job ends */ cap?: number } = {}): Promise<Job> {
  const started = Date.now();
  for (;;) {
    if (signal?.aborted) throw abortError();
    const job = await api<Job>("GET", `/api/jobs/${encodeURIComponent(id)}`);
    if (signal?.aborted) throw abortError();
    if (job.state === "done") return job;
    if (job.state === "error") throw new JobError(job);
    if (cap > 0 && Date.now() - started + every > cap) throw new Error("The job did not finish within 30 minutes.");
    await pause(every, signal);
  }
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
  /** The insights settings and the days a `day:` job is generating (app.snapshot). */
  insights?: StatusInsights;
}

export interface StatusInsights {
  days_done: number;
  days_error: number;
  provider: string;
  model: string;
  auto: boolean;
  generating: IsoDate[];
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
  /** "" (none), "ollama", "anthropic", "openai" or "google". */
  insights_provider: string;
  /** "" for the provider's default. */
  insights_model: string;
  /** OpenAI only: "" for OpenAI itself, else an OpenAI-compatible endpoint. */
  insights_base_url: string;
  insights_auto: boolean;
  readonly: { state_root: string; whisper_model: string; bundle_id: string };
}

export type SettingsPatch = Partial<Omit<Settings, "readonly">>;

// --- insights (Task 8's routes) ---

/** A moment worth coming back to; `line_id` ("<clip_id>-<seq>") when it falls on a transcript line. */
export interface FollowUp {
  text: string;
  at_ms: number | null;
  line_id: string | null;
}

export interface Insight {
  summary: string;
  follow_ups: FollowUp[];
  people: string[];
  topics: string[];
}

/** A day's stored insight row: `insight` when done, `error` when the run failed. */
export interface InsightRecord {
  day: IsoDate;
  state: "done" | "error";
  provider: string;
  model: string;
  prompt_version: number;
  generated_ms: number;
  input_chars: number;
  insight: Insight | null;
  error: string | null;
  /** the day's text was cut from the front to fit */
  truncated: boolean;
}

/** GET /api/insights/<day>. `reason` is why Generate and Ask are refused (null when usable); `job` the
 *  running generate job's id. */
export interface InsightDayState {
  state: "none" | "generating" | "done" | "error";
  record: InsightRecord | null;
  reason: string | null;
  job: string | null;
}

/** GET /api/jobs/<id>. A generate job's result is GenerateResult, an ask job's AskResult. */
export interface Job {
  id: string;
  kind: "generate" | "generate_range" | "ask" | "auto" | string;
  key: string;
  state: "running" | "done" | "error";
  result: unknown;
  error: string | null;
  started_ms: number;
  finished_ms: number | null;
}

/** `stored` is false for a failed regenerate: the day keeps its earlier done row. */
export interface GenerateResult {
  record: InsightRecord;
  stored: boolean;
}

export interface AskResult {
  answer: string;
}

export interface ModelInfo {
  id: string;
  label: string;
  recommended: boolean;
  cost_per_day: string | null;
}

/** GET /api/insights/providers: registry.provider_facts. `provider` is "" when none is chosen. */
export interface ProviderFacts {
  provider: "" | "ollama" | "anthropic" | "openai" | "google" | string;
  model: string;
  auto: boolean;
  base_url: string;
  key_present: boolean | null;
  keychain_error: string | null;
  facts: { sends: string; to: string; cost: string } | null;
  models: ModelInfo[];
  sentence: string;
  display: string;
  check: unknown;
}

/** POST /api/insights/check: the provider answered or not, and the models it lists (Ollama's pulled ones). */
export interface ProviderCheck {
  ok: boolean;
  detail: string;
  models: ModelInfo[];
}

/** A follow-up across days (app.insights_index). */
export interface DayFollowUp extends FollowUp {
  day: IsoDate;
}

/** A person or a topic with the days it appears on, newest first. */
export interface NamedDays {
  name: string;
  days: IsoDate[];
}

/** A complete day with speech and no done insight; `chars` estimates what it would send. */
export interface DayWithout {
  day: IsoDate;
  chars: number;
  error: string | null;
}

/** GET /api/insights: app.insights_index. `days_without` is newest first. */
export interface InsightsIndex {
  follow_ups: DayFollowUp[];
  people: NamedDays[];
  topics: NamedDays[];
  days_without: DayWithout[];
  generating: IsoDate[];
  due: IsoDate[];
  auto: boolean;
}

/** A generate_range job's result. */
export interface RangeResult {
  done: number;
  errors: { day: IsoDate; error: string | null }[];
  /** Why the range stopped early (a refused key, an unreachable provider), and how many days it left unsent. */
  stopped?: string | null;
  not_sent?: number;
}
