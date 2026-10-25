import { useEffect, useRef, useState } from "preact/hooks";
import {
  api, ApiError, explainError, JobError, pause, pollJob, type DayFollowUp, type InsightsIndex, type NamedDays, type ProviderFacts, type RangeResult,
} from "../api";
import { Empty } from "../components/Empty";
import { Frame } from "../components/Frame";
import { FollowUpLine } from "../components/FollowUps";
import { dayMonth, dayTitle } from "../format";
import {
  actionError, dayInsightsHref, MODEL_PRIVACY, MODEL_TAB, NO_PROVIDER, pollError, rangeEstimate, rangeResult,
} from "../insights";
import { notifyInsightsChanged, useOnDataChange } from "../refresh";
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

/** "Generate for the last 7 / 30 days": the estimate first, then Confirm posts the range and follows its job. */
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
      <h2 class="section-title" id="xd-gen">Generate</h2>
      {index.generating.map((d) => <p key={d} class="ins-quiet xd-generating" role="status">{`Generating ${dayTitle(d)}…`}</p>)}
      <div class="xd-range-row">
        {RANGES.map((n) => (
          <button key={n} class="btn" type="button" disabled={busy}
            aria-pressed={run.phase === "confirm" ? run.n === n : undefined}
            onClick={() => setRun({ phase: "confirm", n })}>{`Generate for the last ${n} days`}</button>
        ))}
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

/** Insights across days: follow-ups newest first, people and topics with the days they appear on, and
 *  a way to generate the days still without an insight. */
export function Insights() {
  const [index, setIndex] = useState<InsightsIndex | null>(null);
  const [facts, setFacts] = useState<ProviderFacts | null>(null);
  const [error, setError] = useState<string | null>(null);
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

  // a day being generated (by its tab, or automatically): read the index again until it is done
  useEffect(() => {
    if (!index || index.generating.length === 0) return;
    const timer = window.setTimeout(reload, GENERATING_EVERY_MS);
    return () => window.clearTimeout(timer);
  }, [index]);

  let body;
  if (error) body = <p class="notice warn" role="alert">{error}</p>;
  else if (!index || !facts) body = <p class="page-lead loading">Loading insights</p>;
  else {
    const any = index.follow_ups.length + index.people.length + index.topics.length > 0;
    body = (
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
        {facts.provider && <RangeControl index={index} facts={facts} onDone={reload} />}
      </>
    );
  }

  return (
    <Frame toolbar={{ title: "Insights" }}>
      <div class="page list-page xd-page">
        <h1 class="page-title">Insights</h1>
        {body}
      </div>
    </Frame>
  );
}
