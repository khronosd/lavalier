import { useEffect, useRef, useState } from "preact/hooks";
import { api, ApiError, explainError, type Appearance, type Settings as SettingsData, type SettingsPatch, type Status } from "../api";
import { Empty } from "../components/Empty";
import { Field } from "../components/Field";
import { ProviderPicker } from "../components/ProviderPicker";
import { SettingsTabs } from "../components/SettingsTabs";
import { Toast } from "../components/Toast";
import { MODEL_PRIVACY } from "../insights";
import { lastReadLine } from "../pendant";
import { minutesToSeconds, secondsToMinutes, validateLocally } from "../settings";
import { applyAppearance } from "../theme";

const TOAST_MS = 2000;

const APPEARANCES: { id: Appearance; label: string }[] = [
  { id: "system", label: "System" }, { id: "light", label: "Light" }, { id: "dark", label: "Dark" },
];

const CONNECTORS_LEAD =
  "Where the day's text can go, and what the app may read to label it. Everything is off until you turn it on. " +
  "Audio never leaves this Mac.";

function Heading({ title, lead }: { title: string; lead?: string }) {
  return (
    <>
      <h1 class="set-title">{title}</h1>
      {lead && <p class="set-lead">{lead}</p>}
    </>
  );
}

/** The saved settings, saved one field at a time. */
function useSettings() {
  const [settings, setSettings] = useState<SettingsData | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [toast, setToast] = useState({ n: 0, on: false });
  const toastTimer = useRef<number | undefined>(undefined);

  useEffect(() => {
    let live = true;
    api<SettingsData>("GET", "/api/settings").then(
      (s) => live && setSettings(s),
      (e) => live && setLoadError(explainError(e, "The settings")),
    );
    api<Status>("GET", "/api/status").then((s) => live && setStatus(s), () => undefined);
    return () => { live = false; window.clearTimeout(toastTimer.current); };
  }, []);

  const setError = (field: string, message: string | null) =>
    setErrors((prev) => {
      const next = { ...prev };
      if (message === null) delete next[field];
      else next[field] = message;
      return next;
    });

  /** Save one field; resolves true when the app took it. */
  async function save(patch: SettingsPatch): Promise<boolean> {
    const field = Object.keys(patch)[0];
    const problem = validateLocally(patch);
    if (problem) {
      setError(problem.field, problem.message);
      return false;
    }
    try {
      const next = await api<SettingsData>("PUT", "/api/settings", patch);
      setSettings((prev) => (next ? next : prev ? { ...prev, ...patch } : prev));
      setError(field, null);
      window.clearTimeout(toastTimer.current);
      setToast((t) => ({ n: t.n + 1, on: true }));
      toastTimer.current = window.setTimeout(() => setToast((t) => ({ ...t, on: false })), TOAST_MS);
      return true;
    } catch (e) {
      if (e instanceof ApiError && e.status === 400) setError(e.field ?? field, e.message);
      else setError(field, `Could not save: ${e instanceof Error ? e.message : String(e)}`);
      return false;
    }
  }

  const clearError = (field: string) => setErrors((prev) => (field in prev ? Object.fromEntries(Object.entries(prev).filter(([k]) => k !== field)) : prev));

  return { settings, setSettings, status, loadError, errors, toast, save, clearError };
}

export function Settings({ tab }: { tab: string }) {
  const { settings, setSettings, status, loadError, errors, toast, save, clearError } = useSettings();
  // the live preview belongs to the field: it is ignored once the tab or the saved value has changed
  const [preview, setPreview] = useState<{ key: string; text: string } | null>(null);
  const previewKey = `${tab}:${settings?.retention_days}`;
  const days = preview && preview.key === previewKey ? preview.text : null;
  const setDays = (text: string | null) => setPreview(text === null ? null : { key: previewKey, text });

  let body;
  if (loadError) body = <p class="notice warn" role="alert">{loadError}</p>;
  else if (!settings) body = <p class="page-lead loading">Loading settings</p>;
  else {
    const n = days ?? String(settings.retention_days);
    switch (tab) {
      case "pendant":
        body = (
          <>
            <Heading title="Pendant" />
            <Field key="pendant_address" name="pendant_address" onEdit={() => clearError("pendant_address")} label="Pendant address" value={settings.pendant_address}
              help="The address this Mac knows the pendant by. Leave it as it is unless the app cannot find the pendant."
              error={errors.pendant_address} onCommit={(t) => save({ pendant_address: t })} />
            <Field key="require_firmware" name="require_firmware" onEdit={() => clearError("require_firmware")} label="Required firmware" value={settings.require_firmware}
              help="The app only talks to a pendant on this firmware version. Leave blank to accept any."
              error={errors.require_firmware} onCommit={(t) => save({ require_firmware: t })} />
            <Field key="drain_pages_threshold" name="drain_pages_threshold" onEdit={() => clearError("drain_pages_threshold")} label="Drain when this many pages are waiting" number
              value={String(settings.drain_pages_threshold)} help="Pages are about a second and a half of speech each."
              error={errors.drain_pages_threshold}
              onCommit={(t) => save({ drain_pages_threshold: t.trim() === "" ? Number.NaN : Number(t) })} />
            <Field key="drain_after_hours" name="drain_after_hours" onEdit={() => clearError("drain_after_hours")} label="Drain at least every (hours)" number
              value={String(settings.drain_after_hours)} error={errors.drain_after_hours}
              onCommit={(t) => save({ drain_after_hours: t.trim() === "" ? Number.NaN : Number(t) })} />
            <p class="set-fact"><span class="set-fact-label">Last read</span>{lastReadLine(status)}</p>
          </>
        );
        break;
      case "retention":
        body = (
          <>
            <Heading title="Retention" />
            <Field key="retention_days" name="retention_days" onEdit={() => clearError("retention_days")} label="Keep audio for (days)" number value={String(settings.retention_days)}
              help={`Audio is deleted ${n === "" ? "…" : n} days after it was recorded; starred and pinned conversations are kept. Text is kept for good.`}
              error={errors.retention_days} onInput={setDays} onGone={() => setPreview(null)}
              onCommit={async (t) => {
                const ok = await save({ retention_days: t.trim() === "" ? Number.NaN : Number(t) });
                if (ok) setDays(null);
                return ok;
              }} />
            <h2 class="set-sub">Transcription</h2>
            <Field key="whisper_language" name="whisper_language" onEdit={() => clearError("whisper_language")} label="Language (two letters)" value={settings.whisper_language}
              help="The language the speech is transcribed as, such as en or de."
              error={errors.whisper_language} onCommit={(t) => save({ whisper_language: t })} />
            <p class="set-fact"><span class="set-fact-label">Model</span>{settings.readonly.whisper_model}</p>
          </>
        );
        break;
      case "connectors":
        body = (
          <>
            <Heading title="Connectors" lead={CONNECTORS_LEAD} />
            <Empty title="Connectors arrive in a later release." />
          </>
        );
        break;
      case "model":
        body = (
          <>
            <Heading title="Model" lead={MODEL_PRIVACY} />
            <ProviderPicker settings={settings} setSettings={setSettings} save={save} errors={errors}
              clearError={clearError} />
          </>
        );
        break;
      case "appearance":
        body = (
          <>
            <Heading title="Appearance" />
            <fieldset class="radios">
              <legend>Colors</legend>
              {APPEARANCES.map((a) => (
                <label key={a.id} class="radio" for={`a-${a.id}`}>
                  <input type="radio" id={`a-${a.id}`} name="appearance" checked={settings.appearance === a.id}
                    onChange={async () => {
                      const before = settings.appearance;
                      applyAppearance(a.id);
                      setSettings({ ...settings, appearance: a.id });
                      if (!(await save({ appearance: a.id }))) {
                        applyAppearance(before);
                        setSettings((s) => (s ? { ...s, appearance: before } : s));
                      }
                    }} />
                  {a.label}
                </label>
              ))}
            </fieldset>
            {errors.appearance && <p class="field-error" role="alert">{errors.appearance}</p>}
          </>
        );
        break;
      default:
        body = (
          <>
            <Heading title="General" />
            <p class="set-fact"><span class="set-fact-label">State folder</span><span class="path">{settings.readonly.state_root}</span></p>
            <Field key="poll_interval_s" name="poll_interval_s" onEdit={() => clearError("poll_interval_s")} label="Check the pendant every (minutes)" number
              value={secondsToMinutes(settings.poll_interval_s)} help="At least 1 minute."
              error={errors.poll_interval_s} onCommit={(t) => save({ poll_interval_s: minutesToSeconds(t) })} />
            {status && <p class="set-fact"><span class="set-fact-label">App</span>
              {`Version ${status.app.version}, process ${status.app.pid}`}</p>}
          </>
        );
    }
  }

  return (
    <div class="set-layout">
      <SettingsTabs tab={tab} />
      <div class="set-main">
        <div class="set-body">{body}</div>
        <Toast text={toast.n > 0 ? "Saved" : ""} on={toast.on} />
      </div>
    </div>
  );
}
