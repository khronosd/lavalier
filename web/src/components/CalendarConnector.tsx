import { useEffect, useRef, useState } from "preact/hooks";
import { api, ApiError, type CalendarInfo, type ConnectorsState, type Settings, type SettingsPatch } from "../api";
import { ALL_CALENDARS, authLine, CALENDAR_SENTENCE, calendarIds, toggleCalendar } from "../connectors";
import { actionError } from "../insights";
import { ConnectorSwitch } from "./ConnectorSwitch";

export const ACCESS_SLOW = "The access prompt was not answered in time. Press Allow access to ask again.";
const COLOUR = /^#[0-9a-f]{6}$/i;

interface Props {
  settings: Settings;
  state: ConnectorsState | null;
  saveAndRead: (patch: SettingsPatch) => Promise<boolean>;
  setSettings: (update: (s: Settings | null) => Settings | null) => void;
  errors: Record<string, string>;
  refresh: () => void;
}

/** One calendar as a checkbox, with its colour as a dot when it has one. */
function CalendarCheck({ cal, n, checked, onChange }: { cal: CalendarInfo; n: number; checked: boolean; onChange: (on: boolean) => void }) {
  const id = `cal-${n}`;
  const colour = cal.colour && COLOUR.test(cal.colour) ? cal.colour : null;
  return (
    <label class="radio cal-check" for={id}>
      <input type="checkbox" id={id} checked={checked} onChange={(e) => onChange(e.currentTarget.checked)} />
      {/* the colour is the one value set on the element, as a custom property the stylesheet reads */}
      {colour && <span class="cal-dot" aria-hidden="true" style={{ "--dot": colour }} />}
      {cal.title || "Untitled calendar"}
    </label>
  );
}

/** Settings › Connectors › Calendar: the switch, calendar access, and the calendars to read. */
export function CalendarConnector({ settings, state, saveAndRead, setSettings, errors, refresh }: Props) {
  const [asking, setAsking] = useState(false);
  const [askError, setAskError] = useState<string | null>(null);
  const live = useRef(true);
  useEffect(() => () => { live.current = false; }, []);

  async function setEnabled(on: boolean) {
    setSettings((s) => (s ? { ...s, calendar_enabled: on } : s));
    if (!(await saveAndRead({ calendar_enabled: on }))) setSettings((s) => (s ? { ...s, calendar_enabled: !on } : s));
  }

  async function allow() {
    setAsking(true);
    setAskError(null);
    try {
      await api<{ authorization: string }>("POST", "/api/connectors/calendar/access");
    } catch (e) {
      if (live.current) setAskError(e instanceof ApiError && e.status === 504 ? ACCESS_SLOW : actionError(e));
    } finally {
      if (live.current) {
        setAsking(false);
        refresh();
      }
    }
  }

  async function pick(id: string, on: boolean) {
    const before = settings.calendar_ids;
    const next = toggleCalendar(before, id, on);
    setSettings((s) => (s ? { ...s, calendar_ids: next } : s));
    if (!(await saveAndRead({ calendar_ids: next }))) setSettings((s) => (s ? { ...s, calendar_ids: before } : s));
  }

  const auth = state ? state.calendar.authorization : undefined;
  const chosen = new Set(calendarIds(settings.calendar_ids));
  const calendars = state && auth === "allowed" ? state.calendar.calendars : [];
  return (
    <section class="con" aria-labelledby="con-calendar">
      <h2 class="set-sub con-title" id="con-calendar">Calendar</h2>
      <ConnectorSwitch id="calendar_enabled" label="Label conversations from Calendar" sentence={CALENDAR_SENTENCE}
        checked={settings.calendar_enabled} error={errors.calendar_enabled} onChange={setEnabled} />
      <div class="ins-action con-action">
        <span class="set-fact-label">Access</span>
        <span class="con-auth">{auth === undefined ? "Reading…" : authLine(auth)}</span>
        {auth === "not-asked" && (
          <button class="btn" type="button" disabled={asking} onClick={allow}>Allow access</button>
        )}
      </div>
      {askError && <p class="field-error" role="alert">{askError}</p>}
      {auth === "allowed" && (
        <fieldset class="radios cal-list">
          <legend>Calendars</legend>
          {calendars.length === 0 && <p class="field-help">This Mac has no calendars to read.</p>}
          {calendars.map((c, n) => (
            <CalendarCheck key={c.identifier} cal={c} n={n} checked={chosen.has(c.identifier)}
              onChange={(on) => pick(c.identifier, on)} />
          ))}
          {calendars.length > 0 && chosen.size === 0 && <p class="field-help con-note">{ALL_CALENDARS}</p>}
        </fieldset>
      )}
      {errors.calendar_ids && <p class="field-error" role="alert">{errors.calendar_ids}</p>}
    </section>
  );
}
