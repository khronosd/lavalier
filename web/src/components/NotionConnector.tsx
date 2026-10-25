import { useEffect, useRef, useState } from "preact/hooks";
import { api, ApiError, pollJob, type ConnectorsState, type DatabaseInfo, type ExportResult, type Settings, type SettingsPatch } from "../api";
import { againBody, EXPORT_DAYS, exportResultLine, normaliseNotionId, NOTION_SENTENCE } from "../connectors";
import { actionError, pollError } from "../insights";
import { ConnectorSwitch } from "./ConnectorSwitch";
import { ExportList } from "./ExportList";
import { Field } from "./Field";
import { KeyField } from "./KeyField";

export const NOTION_SLOW = "Notion took too long to answer. Try again in a minute.";
export const EXPORT_RUNNING = "An export is already running. Its days show below once it ends.";
const TOKEN_HELP = "Create an internal integration in Notion, share your database with it, and paste its secret here.";
const DATABASE_HELP = "The database that gets one page per day. Share it with the integration first.";

interface Props {
  settings: Settings;
  /** The connectors as the app last said, null until read. */
  state: ConnectorsState | null;
  /** Save one setting and read the connectors again. */
  saveAndRead: (patch: SettingsPatch) => Promise<boolean>;
  setSettings: (update: (s: Settings | null) => Settings | null) => void;
  errors: Record<string, string>;
  clearError: (field: string) => void;
  /** Read the connectors again. */
  refresh: () => void;
}

type Line = { ok: boolean; text: string };

/** Settings › Connectors › Notion: the switch, the token, the database, Test, the export and the last exports. */
export function NotionConnector({ settings, state, saveAndRead, setSettings, errors, clearError, refresh }: Props) {
  const [test, setTest] = useState<(Line & { missing: string[] }) | null>(null);
  const [testing, setTesting] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [result, setResult] = useState<Line | null>(null);
  const live = useRef(true);
  const poll = useRef<AbortController | null>(null);
  useEffect(() => () => { live.current = false; poll.current?.abort(); }, []);

  async function setEnabled(on: boolean) {
    setSettings((s) => (s ? { ...s, notion_enabled: on } : s));
    if (!(await saveAndRead({ notion_enabled: on }))) setSettings((s) => (s ? { ...s, notion_enabled: !on } : s));
  }

  async function runTest() {
    setTesting(true);
    setTest(null);
    try {
      const info = await api<DatabaseInfo>("POST", "/api/connectors/notion/check");
      if (!live.current) return;
      setTest({ ok: true, text: `Connected to ${info.title}`, missing: info.missing_properties });
    } catch (e) {
      if (!live.current) return;
      setTest({ ok: false, text: e instanceof ApiError && e.status === 504 ? NOTION_SLOW : actionError(e), missing: [] });
    } finally {
      if (live.current) {
        setTesting(false);
        refresh(); // the check reads the token: whether one is saved may have changed
      }
    }
  }

  /** Start an export job, follow it to its end, say what it did and read the list again. */
  async function runExport(body: { days: number } | { day: string; force?: true }) {
    poll.current?.abort();
    const ctl = new AbortController();
    poll.current = ctl;
    setExporting(true);
    setResult(null);
    try {
      const { job } = await api<{ job: string }>("POST", "/api/connectors/notion/export", body);
      if (ctl.signal.aborted) return;
      const done = await pollJob(job, { signal: ctl.signal });
      setResult({ ok: true, text: exportResultLine(done.result as ExportResult) });
    } catch (e) {
      if (ctl.signal.aborted) return;
      if (e instanceof ApiError && e.status === 409) setResult({ ok: false, text: EXPORT_RUNNING });
      else if (e instanceof ApiError && e.status !== 404) setResult({ ok: false, text: actionError(e) });
      else setResult({ ok: false, text: pollError(e) });
    } finally {
      if (!ctl.signal.aborted) {
        setExporting(false);
        refresh();
      }
    }
  }

  const running = exporting || state?.notion.exporting === true;
  return (
    <section class="con" aria-labelledby="con-notion">
      <h2 class="set-sub con-title" id="con-notion">Notion</h2>
      <ConnectorSwitch id="notion_enabled" label="Send days to Notion" sentence={NOTION_SENTENCE}
        checked={settings.notion_enabled} error={errors.notion_enabled} onChange={setEnabled} />
      <KeyField provider="notion" label="Integration token" saveLabel="Save token" noneText="No token saved"
        help={TOKEN_HELP} present={state ? state.notion.token_present : null} keychainError={null} onChanged={refresh} />
      <Field key="notion_database_id" name="notion_database_id" label="Database" blurOnly value={settings.notion_database_id}
        help={DATABASE_HELP} error={errors.notion_database_id} onEdit={() => clearError("notion_database_id")}
        onCommit={(t) => saveAndRead({ notion_database_id: normaliseNotionId(t) ?? t })} />
      <div class="ins-action con-action">
        <button class="btn" type="button" disabled={testing} onClick={runTest}>Test</button>
        {testing && <span class="ins-help" role="status">Testing…</span>}
        {test && <span class={test.ok ? "ins-help" : "ins-help con-bad"} role={test.ok ? "status" : "alert"}>{test.text}</span>}
      </div>
      {test && test.missing.length > 0 && (
        <p class="field-help con-note">{`Missing properties will be added: ${test.missing.join(", ")}`}</p>
      )}
      <div class="ins-action con-action">
        <button class="btn" type="button" disabled={running} onClick={() => runExport({ days: EXPORT_DAYS })}>
          {`Export the last ${EXPORT_DAYS} days`}
        </button>
        {running && <span class="ins-help" role="status">Exporting…</span>}
        {!running && result && (
          <span class={result.ok ? "ins-help" : "ins-help con-bad"} role={result.ok ? "status" : "alert"}>{result.text}</span>
        )}
      </div>
      {state && <ExportList rows={state.notion.last} busy={running} onAgain={(row) => runExport(againBody(row))} />}
    </section>
  );
}
