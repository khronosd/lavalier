import { useEffect, useRef, useState } from "preact/hooks";
import {
  api, ApiError, explainError, pollJob, type DayView, type GenerateResult, type InsightDayState, type InsightRecord,
  type ProviderFacts,
} from "../api";
import {
  actionError, generatedLine, generateSentence, MODEL_PRIVACY, MODEL_TAB, NO_PROVIDER, NO_SPEECH, noProvider,
  pollError, tabState,
} from "../insights";
import { notifyInsightsChanged } from "../refresh";
import { Empty } from "./Empty";
import { FollowUps } from "./FollowUps";
import { QuestionBox } from "./QuestionBox";

export { MODEL_PRIVACY };

const ModelTabLink = () => <a class="ins-link" href={MODEL_TAB}>Open Settings › Model</a>;

function Action({ label, sentence, busy, onClick }: {
  label: string; sentence: string; busy: boolean; onClick: () => void;
}) {
  return (
    <div class="ins-action">
      <button class="btn" type="button" disabled={busy} onClick={onClick}>{label}</button>
      <span class="ins-help">{sentence}</span>
    </div>
  );
}

function Names({ title, names }: { title: string; names: string[] }) {
  if (names.length === 0) return null;
  return (
    <section class="ins-block">
      <h2 class="section-title">{title}</h2>
      <p class="ins-names">{names.join(", ")}</p>
    </section>
  );
}

function Done({ day, record }: { day: string; record: InsightRecord }) {
  const insight = record.insight!;
  return (
    <>
      <section class="ins-block">
        <h2 class="section-title">Summary</h2>
        <p class="reading ins-summary">{insight.summary}</p>
      </section>
      {insight.follow_ups.length > 0 && <FollowUps day={day} items={insight.follow_ups} />}
      <Names title="People" names={insight.people} />
      <Names title="Topics" names={insight.topics} />
    </>
  );
}

/** The day's Insights tab: the summary, follow-ups that jump to their line, people and topics, Generate,
 *  and the question box. Fetches the day's insight state on mount and after each job, the provider once. */
export function InsightsTab({ day, view }: { day: string; view: DayView }) {
  const [state, setState] = useState<InsightDayState | null>(null);
  const [facts, setFacts] = useState<ProviderFacts | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const mounted = useRef(true);
  const lastFetch = useRef(0);
  useEffect(() => () => { mounted.current = false; }, []);

  /** The day's state from the server; latest wins. On failure the tab keeps what it shows, minus a
   *  generating state it can no longer follow. */
  async function refresh(): Promise<void> {
    const n = ++lastFetch.current;
    try {
      const next = await api<InsightDayState>("GET", `/api/insights/${day}`);
      if (mounted.current && n === lastFetch.current) setState(next);
    } catch (e) {
      if (!mounted.current || n !== lastFetch.current) return;
      setRunError(explainError(e, "Insights"));
      setState((cur) => cur && cur.state === "generating" ? { ...cur, state: cur.record?.state ?? "none", job: null } : cur);
    }
  }

  useEffect(() => {
    setState(null);
    setLoadError(null);
    setRunError(null);
    const n = ++lastFetch.current;
    Promise.all([
      api<InsightDayState>("GET", `/api/insights/${day}`),
      api<ProviderFacts>("GET", "/api/insights/providers"),
    ]).then(
      ([s, f]) => { if (mounted.current && n === lastFetch.current) { setState(s); setFacts(f); } },
      (e) => { if (mounted.current && n === lastFetch.current) setLoadError(explainError(e, "Insights")); },
    );
  }, [day]);

  // a generate job, the window's own or one already running: follow it, then read the day again
  const jobId = state?.state === "generating" ? state.job : null;
  useEffect(() => {
    if (!jobId) return;
    const ctl = new AbortController();
    pollJob(jobId, { signal: ctl.signal }).then(
      (job) => {
        const r = job.result as GenerateResult | null;
        // a failed regenerate is not stored: the day keeps its earlier insight, and the error shows above it
        setRunError(r && !r.stored && r.record.state === "error" ? r.record.error : null);
      },
      (e) => { if (!ctl.signal.aborted) setRunError(pollError(e)); },
    ).then(() => {
      if (ctl.signal.aborted) return;
      notifyInsightsChanged();
      return refresh();
    });
    return () => ctl.abort();
  }, [jobId]);

  async function generate() {
    setStarting(true);
    setRunError(null);
    try {
      const { job } = await api<{ job: string }>("POST", `/api/insights/generate/${day}`);
      if (mounted.current) setState((cur) => cur && { ...cur, state: "generating", job });
    } catch (e) {
      if (!mounted.current) return;
      if (e instanceof ApiError && e.status === 409) await refresh(); // already generating: follow that run
      else setRunError(actionError(e));
    } finally {
      if (mounted.current) setStarting(false);
    }
  }

  if (loadError) return <p class="notice warn" role="alert">{loadError}</p>;
  if (!state || !facts) return <p class="ins-quiet ins-loading" aria-busy="true">Loading insights</p>;

  const shown = tabState(state, facts, view);
  if (shown === "no-provider") {
    return <Empty title={NO_PROVIDER}>{MODEL_PRIVACY} <ModelTabLink /></Empty>;
  }
  if (shown === "no-speech") return <Empty title={NO_SPEECH} />;

  const sentence = generateSentence(facts);
  const unset = noProvider(state, facts); // only a done insight is shown this way
  const alert = runError && <p class="ins-error" role="alert">{runError}</p>;
  return (
    <div class="insights">
      {shown === "unusable" && <p class="ins-reason">{state.reason} <ModelTabLink /></p>}
      {shown === "none" && (
        <section class="ins-block">
          {alert}
          <Action label="Generate now" sentence={sentence} busy={starting} onClick={generate} />
        </section>
      )}
      {shown === "generating" && (
        <section class="ins-block">
          <p class="ins-quiet" role="status">{`Generating with ${facts.model}…`}</p>
        </section>
      )}
      {shown === "error" && (
        <section class="ins-block">
          <p class="ins-error" role="alert">{runError ?? state.record?.error}</p>
          <Action label="Generate again" sentence={sentence} busy={starting} onClick={generate} />
        </section>
      )}
      {shown === "done" && state.record && (
        <>
          {alert && <div class="ins-block">{alert}</div>}
          <Done day={day} record={state.record} />
          <section class="ins-block ins-foot">
            <p class="ins-meta">{generatedLine(state.record)}</p>
            {unset
              ? <p class="ins-reason">{NO_PROVIDER} <ModelTabLink /></p>
              : state.reason
                ? <p class="ins-reason">{state.reason} <ModelTabLink /></p>
                : <Action label="Regenerate" sentence={sentence} busy={starting} onClick={generate} />}
          </section>
        </>
      )}
      {shown !== "unusable" && !state.reason && !unset && <QuestionBox day={day} />}
    </div>
  );
}
