import { useEffect, useRef, useState } from "preact/hooks";
import {
  api, ApiError, type DaySummary, explainError, JobError, pause, pollJob, type DayFollowUp, type InsightsIndex, type NamedDays,
  type ProviderFacts, type RangeResult,
} from "../api";
import { Empty } from "../components/Empty";
import { FollowUpLine } from "../components/FollowUps";
import { Frame } from "../components/Frame";
import { InsightsIcon } from "../components/icons";
import { InsightsTab } from "../components/InsightsTab";
import { QuestionBox } from "../components/QuestionBox";
import { AUTO_LABEL } from "../components/ProviderPicker";
import { useDayView } from "../dayCache";
import { dayMonth, dayTitle } from "../format";
import {
  actionError, dayInsightsHref, type DayRow, dayRows, daysLine, MODEL_PRIVACY, MODEL_TAB, NO_PROVIDER, pollError,
  rangeEstimate, rangeResult,
} from "../insights";
import { notifyInsightsChanged, useOnDataChange } from "../refresh";
import { toHash } from "../router";
import { groupByDay } from "../search";

const RANGES = [7, 30] as const;
/** While a day is generating, the index is read again this often to see it finish. */
const GENERATING_EVERY_MS = 5000;
const RANGE_RUNNING = "Days are already being generated. Wait for that run to finish.";
export const STILL_GENERATING = "Still generating; the results will appear here when it finishes";
/** After a failed poll, the range job is asked about again this much later. */
const RETRY_MS = 5000;

type Run =
  | { phase: "idle" }
  | { phase: "confirm"; n: number }
  | { phase: "running"; days: number; still?: boolean }
  | { phase: "result" | "error"; text: string };

/** A day's follow-ups in time order; one without a time comes first, as the server orders them. */
const inTimeOrder = (items: DayFollowUp[]) => [...items].sort((a, b) => (a.at_ms ?? 0) - (b.at_ms ?? 0));
const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

function FollowUpsAcross({ index }: { index: InsightsIndex }) {
  if (index.follow_ups.length === 0) return null;
  return (
    <section class="ins-block xd-follow-ups" aria-labelledby="xd-fu">
      <h2 class="section-title" id="xd-fu">Follow-ups</h2>
      {groupByDay(index.follow_ups).map((g) => (
        <div class="day-group" key={g.day}>
          <h3 class="group-title">{dayTitle(g.day)}</h3>
          {inTimeOrder(g.items).map((fu, i) => <FollowUpLine key={i} day={g.day} fu={fu} />)}
        </div>
      ))}
    </section>
  );
}

function Names({ id, title, names }: { id: string; title: string; names: NamedDays[] }) {
  return (
    <section class="xd-names" aria-labelledby={id}>
      <h2 class="section-title" id={id}>{title}</h2>
      {names.length === 0
        ? <p class="ins-quiet">None yet</p>
        : (
          <ul class="xd-list">
            {names.map((n) => (
              <li key={n.name}>
                <span class="xd-name">{n.name}</span>
                <span class="xd-days">
                  {n.days.map((d) => <a key={d} class="xd-day" href={dayInsightsHref(d)}>{dayMonth(d)}</a>)}
                </span>
              </li>
            ))}
          </ul>
        )}
    </section>
  );
}

/** Catch up: "Generate for the last 7 / 30 days", each with how many days wait; the estimate first, then
 * Confirm posts the range and follows its job. */
function RangeControl({ index, facts, onDone }: { index: InsightsIndex; facts: ProviderFacts; onDone: () => void }) {
  const [run, setRun] = useState<Run>({ phase: "idle" });
  const running = useRef<AbortController | null>(null);
  useEffect(() => () => running.current?.abort(), []);

  async function confirm(n: number, days: number) {
    const ctl = new AbortController();
    running.current = ctl;
    setRun({ phase: "running", days });
    let job: string;
    try {
      ({ job } = await api<{ job: string }>("POST", "/api/insights/generate-range", { days: n }));
    } catch (e) {
      if (ctl.signal.aborted) return;
      setRun({ phase: "error", text: e instanceof ApiError && e.status === 409 ? RANGE_RUNNING : actionError(e) });
      return;
    }
    // a range can run for hours on this Mac: no cap, and a failed poll is asked again after a pause
    for (;;) {
      try {
        const done = await pollJob(job, { signal: ctl.signal, cap: 0 });
        setRun({ phase: "result", text: rangeResult(done.result as RangeResult) });
        break;
      } catch (e) {
        if (ctl.signal.aborted) return;
        if (e instanceof JobError || (e instanceof ApiError && (e.status === 404 || e.status === 401))) {
          setRun({ phase: "error", text: pollError(e) });
          break;
        }
        setRun({ phase: "running", days, still: true });
        try {
          await pause(RETRY_MS, ctl.signal);
        } catch {
          return; // left the page
        }
      }
    }
    notifyInsightsChanged();
    onDone();
  }

  const busy = run.phase === "running";
  const estimate = run.phase === "confirm" ? rangeEstimate(index.days_without, run.n, facts) : null;
  return (
    <section class="ins-block xd-range" aria-labelledby="xd-gen">
      <h2 class="hd" id="xd-gen">Catch up</h2>
      {index.generating.map((d) => <p key={d} class="ins-quiet xd-generating" role="status">{`Generating ${dayTitle(d)}…`}</p>)}
      <div class="xd-range-row">
        {RANGES.map((n) => {
          const waiting = Math.min(n, index.days_without.length);
          return (
            <div class="catch" key={n}>
              <button class="btn" type="button" disabled={busy}
                aria-pressed={run.phase === "confirm" ? run.n === n : undefined}
                onClick={() => setRun({ phase: "confirm", n })}>{`Generate for the last ${n} days`}</button>
              {waiting > 0 && <span class="btn-sub">{`${plural(waiting, "day", "days")} waiting`}</span>}
            </div>
          );
        })}
      </div>
      {run.phase === "confirm" && estimate && (
        <div class="ins-action xd-confirm">
          {estimate.days > 0 && (
            <button class="btn" type="button" onClick={() => confirm(run.n, estimate.days)}>Confirm</button>
          )}
          <span class="ins-help">{estimate.text}</span>
        </div>
      )}
      {run.phase === "running" && (
        <p class="ins-quiet xd-status" role="status">
          {run.still ? STILL_GENERATING : `Generating ${run.days} ${run.days === 1 ? "day" : "days"}…`}
        </p>
      )}
      {run.phase === "result" && <p class="ins-quiet xd-status" role="status">{run.text}</p>}
      {run.phase === "error" && <p class="ins-error xd-status" role="alert">{run.text}</p>}
    </section>
  );
}

/** A day in the list column: its state as a dot, its name, the state's words, the follow-up count when done,
 * and Generate beside a day without an insight. */
function DayRowView({ row, selected, canGenerate, onGenerate }: {
  row: DayRow; selected: boolean; canGenerate: boolean; onGenerate: () => void;
}) {
  return (
    <div class="row-wrap">
      <a class={`row ins-row ${row.state}${selected ? " selected" : ""}`} aria-current={selected ? "true" : undefined}
        href={toHash({ name: "insights", params: {}, query: { day: row.day } })}>
        <span class={`dot ${row.state}`} aria-hidden="true" />
        <span class="row-text">
          <span class="row-title">{dayTitle(row.day)}</span>
          <span class="row-sub">{row.line}</span>
        </span>
        {row.state === "done" && row.followUps > 0 && <span class="row-count">{row.followUps}</span>}
      </a>
      {canGenerate && <button type="button" class="row-generate" onClick={onGenerate}>Generate</button>}
    </div>
  );
}

/** The content column for one day: its title, Open day, and the day's insight as the day view carries it. */
function DayInsight({ day }: { day: string }) {
  const load = useDayView(day);
  return (
    <>
      <div class="moment-head">
        <div><h1 class="page-title">{dayTitle(day)}</h1></div>
        <a class="btn soft" href={dayInsightsHref(day)}>Open day</a>
      </div>
      {load.error && <p class="notice warn" role="alert">{load.error}</p>}
      {!load.view && !load.error && <p class="page-lead loading">Loading…</p>}
      {load.view && <div class="ins-page"><InsightsTab key={day} day={day} view={load.view} /></div>}
    </>
  );
}

function ModelCard({ facts }: { facts: ProviderFacts }) {
  const label = facts.models.find((m) => m.id === facts.model)?.label ?? facts.model;
  return (
    <div class="model-card">
      <span class="tile" aria-hidden="true"><InsightsIcon /></span>
      <div class="model-text">
        <span class="model-title">{label ? `${facts.display} · ${label}` : facts.display}</span>
        <span class="model-sub">{facts.sentence}</span>
      </div>
    </div>
  );
}

function AutoSwitch({ on, error, onChange }: { on: boolean; error: string | null; onChange: (on: boolean) => void }) {
  return (
    <div class="group">
      <div class="g-row">
        <label class="switch-row" for="ins-auto">
          <input type="checkbox" role="switch" id="ins-auto" class="switch" checked={on}
            onChange={(e) => onChange(e.currentTarget.checked)} />
          {AUTO_LABEL}
        </label>
      </div>
      <div class="g-row"><span>Complete at</span><span class="g-value">04:00 the next morning</span></div>
      {error && <p class="field-error" role="alert">{error}</p>}
    </div>
  );
}

interface Props {
  /** The days with clips, for the list column; none while they load. */
  days?: DaySummary[] | null;
  today?: string;
  /** ?day=: the day whose insight the content column shows; none shows the overview across days. */
  day?: string;
}

/** Insights: the days with their insight state in the list column (All days first); the overview across days
 * (follow-ups newest first, people and topics with the days they appear on) or one day's insight in the
 * content column; the model, the automatic switch and the catch-up buttons in the inspector. */
export function Insights({ days = null, today = "", day }: Props) {
  const [index, setIndex] = useState<InsightsIndex | null>(null);
  const [facts, setFacts] = useState<ProviderFacts | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [autoError, setAutoError] = useState<string | null>(null);
  const [rowError, setRowError] = useState<string | null>(null);
  const live = useRef(true);
  const lastFetch = useRef(0);
  useEffect(() => () => { live.current = false; }, []);

  /** The index again; a failure keeps what is shown. Latest wins. */
  function reload() {
    const n = ++lastFetch.current;
    api<InsightsIndex>("GET", "/api/insights").then(
      (next) => { if (live.current && n === lastFetch.current) setIndex(next); },
      () => undefined,
    );
  }

  function readFacts() {
    api<ProviderFacts>("GET", "/api/insights/providers").then((f) => { if (live.current) setFacts(f); }, () => undefined);
  }

  useEffect(() => {
    const n = ++lastFetch.current;
    Promise.all([
      api<InsightsIndex>("GET", "/api/insights"),
      api<ProviderFacts>("GET", "/api/insights/providers"),
    ]).then(
      ([i, f]) => { if (live.current && n === lastFetch.current) { setIndex(i); setFacts(f); } },
      (e) => { if (live.current) setError(explainError(e, "Insights")); },
    );
  }, []);
  useOnDataChange(reload);

  // a day being generated (by its tab, by a row, or automatically): read the index again until it is done
  useEffect(() => {
    if (!index || index.generating.length === 0) return;
    const timer = window.setTimeout(reload, GENERATING_EVERY_MS);
    return () => window.clearTimeout(timer);
  }, [index]);

  /** Saved at once; put back if the app refuses. */
  async function setAuto(on: boolean) {
    setFacts((f) => f && { ...f, auto: on });
    setAutoError(null);
    try {
      await api<unknown>("PUT", "/api/settings", { insights_auto: on });
      readFacts();
    } catch (e) {
      if (!live.current) return;
      setFacts((f) => f && { ...f, auto: !on });
      setAutoError(actionError(e));
    }
  }

  /** Generate one day from its row; a run already under way is followed like any other. */
  async function generate(d: string) {
    setRowError(null);
    try {
      await api<{ job: string }>("POST", `/api/insights/generate/${d}`);
    } catch (e) {
      if (!(e instanceof ApiError && e.status === 409) && live.current) setRowError(actionError(e));
    }
    notifyInsightsChanged();
    reload();
  }

  const rows = index && days ? dayRows(index, days, today) : [];
  const selected = day && rows.some((r) => r.day === day) ? day : null;
  const provider = !!facts?.provider;

  const list = (
    <>
      <a class={selected ? "row ins-row all" : "row ins-row all selected"} href="#/insights" aria-current={selected ? undefined : "true"}>
        <span class="row-icon" aria-hidden="true"><InsightsIcon /></span>
        <span class="row-text">
          <span class="row-title">All days</span>
          <span class="row-sub">Follow-ups, people and topics across days</span>
        </span>
      </a>
      {rows.length > 0 && <p class="hd">Days</p>}
      {rowError && <p class="field-error list-error" role="alert">{rowError}</p>}
      {rows.map((r) => (
        <DayRowView key={r.day} row={r} selected={r.day === selected} canGenerate={provider && r.state === "none"}
          onGenerate={() => generate(r.day)} />
      ))}
    </>
  );

  let content;
  if (error) content = <p class="notice warn" role="alert">{error}</p>;
  else if (!index || !facts) content = <p class="page-lead loading">Loading insights</p>;
  else if (selected) content = <DayInsight key={selected} day={selected} />;
  else {
    const any = index.follow_ups.length + index.people.length + index.topics.length > 0;
    content = (
      <>
        {!facts.provider && (
          <Empty title={NO_PROVIDER}>{MODEL_PRIVACY} <a class="ins-link" href={MODEL_TAB}>Open Settings › Model</a></Empty>
        )}
        {facts.provider && !any && (
          <Empty title="No insights yet.">
            Open a day's Insights tab and press Generate now, or generate the last 7 days below.
          </Empty>
        )}
        {any && (
          <div class="insights">
            <FollowUpsAcross index={index} />
            <div class="ins-block xd-columns">
              <Names id="xd-people" title="People" names={index.people} />
              <Names id="xd-topics" title="Topics" names={index.topics} />
            </div>
          </div>
        )}
        {facts.provider && <div class="insights xd-ask"><QuestionBox /></div>}
      </>
    );
  }

  const inspector = facts && index && !error ? (
    <>
      <p class="insp-title"><InsightsIcon /> Model</p>
      {facts.provider
        ? <ModelCard facts={facts} />
        : (
          <div class="insp-block">
            <p class="hd">Choose a model</p>
            <p class="insp-sub">{NO_PROVIDER}</p>
            <a class="ins-link" href={MODEL_TAB}>Open Settings › Model</a>
          </div>
        )}
      {facts.provider && <AutoSwitch on={facts.auto} error={autoError} onChange={setAuto} />}
      {facts.provider && <RangeControl index={index} facts={facts} onDone={reload} />}
      <p class="insp-foot">{MODEL_PRIVACY}</p>
    </>
  ) : null;

  return (
    <Frame toolbar={{ title: "Insights", subtitle: index && days ? daysLine(rows, index) : undefined }}
      list={list} listLabel="Days" inspector={inspector} inspectorLabel="Model">
      <div class="page list-page xd-page">{content}</div>
    </Frame>
  );
}
