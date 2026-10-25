import { useEffect, useRef, useState } from "preact/hooks";
import { api, explainError, type StarredEntry } from "../api";
import { span } from "../components/Conversation";
import { Empty } from "../components/Empty";
import { Frame } from "../components/Frame";
import { CopyIcon, PendantIcon, PinIcon, StarFillIcon, WaveformIcon } from "../components/icons";
import { QuietGap, StarLine, TranscriptLine } from "../components/TranscriptLine";
import { type DayLoad, useDayView } from "../dayCache";
import { linesAround, transcriptItems } from "../day";
import { dayTitle, hms, noQuote } from "../format";
import { audioKeptLine } from "../playlist";
import { toHash } from "../router";
import { convStart, groupByDay, jumpHref } from "../search";
import { usePendant } from "../shellState";

/** How long "Copied" stays after Copy the quote. */
const COPIED_MS = 2000;

const starHref = (at_ms: number) => toHash({ name: "starred", params: {}, query: { star: String(at_ms) } });
const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

function StarRow({ entry, selected }: { entry: StarredEntry; selected: boolean }) {
  const { star } = entry;
  const start = star.conversation_id ? convStart(star.conversation_id) : null;
  return (
    <a class={selected ? "row star-row selected" : "row star-row"} href={starHref(star.at_ms)} aria-current={selected ? "true" : undefined}>
      <StarFillIcon />
      <span class="star-body">
        {star.quote
          ? <p class="row-quote reading quote">{star.quote}</p>
          : <p class="row-quote no-quote">{noQuote(star)}</p>}
        <span class="row-foot">
          <time class="row-time" dateTime={new Date(star.at_ms).toISOString()}>{hms(star.at_ms)}</time>
          {star.conversation_id && <span class="star-conv">{start ? `in the ${start} conversation` : "in a conversation"}</span>}
        </span>
      </span>
    </a>
  );
}

/** The content column: the conversation's title and the moment, Open day, the pull quote, and the lines around it. */
function Moment({ entry, day }: { entry: StarredEntry; day: DayLoad }) {
  const { star } = entry;
  const conv = day.view?.conversations.find((c) => c.conversation_id === star.conversation_id) ?? null;
  const meta = [dayTitle(entry.day), conv && span(conv), `starred at ${hms(star.at_ms)}`].filter(Boolean).join(" · ");
  const around = conv ? new Set(linesAround(conv, star.at_ms).map((l) => `${l.clip_id}-${l.seq}`)) : null;
  return (
    <>
      <div class="moment-head">
        <div>
          <h1 class="page-title">{conv ? conv.label ?? span(conv) : dayTitle(entry.day)}</h1>
          <p class="page-meta">{meta}</p>
        </div>
        <a class="btn soft" href={conv ? jumpHref(entry.day, `c-${conv.conversation_id}`) : jumpHref(entry.day)}>Open day</a>
      </div>
      {star.quote
        ? <blockquote class="pull reading">{`“${star.quote}”`}</blockquote>
        : <p class="pull no-quote">{noQuote(star)}</p>}
      {day.error && <p class="notice warn" role="alert">{day.error}</p>}
      {!day.view && !day.error && <p class="page-lead loading">Loading…</p>}
      {conv && around && (
        <>
          <p class="hd around-head">Around it</p>
          <div class="around">
            {transcriptItems(conv).map((item, i) =>
              item.kind === "line"
                ? around.has(`${item.line.clip_id}-${item.line.seq}`)
                  && <TranscriptLine key={`${item.line.clip_id}-${item.line.seq}`} line={item.line} starred={item.starred} />
                : item.kind === "star"
                  ? <StarLine key={`star-${item.at_ms}`} at_ms={item.at_ms} />
                  : <QuietGap key={`gap-${i}`} minutes={item.minutes} />)}
          </div>
        </>
      )}
    </>
  );
}

/** The inspector: when the moment was starred, how long its audio is kept, Pin and Copy the quote, the
 * conversation's other stars, and the pendant's button presses. */
function MomentFacts({ entry, day, others }: { entry: StarredEntry; day: DayLoad; others: StarredEntry[] }) {
  const { star } = entry;
  const pendant = usePendant();
  const conv = day.view?.conversations.find((c) => c.conversation_id === star.conversation_id) ?? null;
  const [busy, setBusy] = useState(false);
  const [pinError, setPinError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);

  async function pin() {
    if (!conv || !day.view) return;
    const pinned = !conv.pinned;
    setBusy(true);
    setPinError(null);
    try {
      await api<unknown>("POST", `/api/${pinned ? "pin" : "unpin"}/${encodeURIComponent(conv.conversation_id)}`);
      day.update({ ...day.view, conversations: day.view.conversations.map((c) => c.conversation_id === conv.conversation_id ? { ...c, pinned } : c) });
    } catch (e) {
      setPinError(`Could not ${pinned ? "pin" : "unpin"}: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  async function copy() {
    if (!star.quote) return;
    await navigator.clipboard?.writeText(star.quote);
    setCopied(true);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setCopied(false), COPIED_MS);
  }

  const presses = pendant?.status ? pendant.status.long_presses + pendant.status.double_presses : 0;
  return (
    <>
      <p class="insp-title"><StarFillIcon /> This moment</p>
      <div class="facts">
        <p class="fact"><PendantIcon /><span>Starred at <b>{hms(star.at_ms)}</b></span></p>
        {day.view && <p class="fact"><WaveformIcon /><span>{audioKeptLine(day.view)}</span></p>}
      </div>
      <div class="insp-actions">
        {conv && (
          <button type="button" class="btn" disabled={busy} onClick={pin}><PinIcon />{conv.pinned ? "Unpin" : "Pin"}</button>
        )}
        <button type="button" class="btn" disabled={!star.quote} onClick={copy}><CopyIcon />Copy the quote</button>
        {copied && <span class="ins-help" role="status">Copied</span>}
        {pinError && <p class="field-error" role="alert">{pinError}</p>}
      </div>
      {others.length > 0 && (
        <div class="insp-block">
          <p class="hd">Also in this conversation</p>
          {others.map((o) => (
            <a class="insp-row quote-row" key={o.star.at_ms} href={starHref(o.star.at_ms)}>
              <span class="chip-time">{hms(o.star.at_ms)}</span>
              {o.star.quote
                ? <span class="reading">{o.star.quote}</span>
                : <span class="no-quote">{noQuote(o.star)}</span>}
            </a>
          ))}
        </div>
      )}
      {presses > 0 && pendant?.status && (
        <p class="insp-foot">{`Button presses: ${pendant.status.long_presses} long, ${pendant.status.double_presses} double.`}</p>
      )}
    </>
  );
}

/** Every starred moment of every day, newest first, in the list column; the selected one's conversation,
 * quote and surroundings in the content column; its facts in the inspector. */
export function StarredPage({ star }: { star?: string }) {
  const [entries, setEntries] = useState<StarredEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api<StarredEntry[]>("GET", "/api/starred").then(
      (list) => live && setEntries(list),
      (e) => live && setError(explainError(e, "The starred moments")),
    );
    return () => { live = false; };
  }, []);

  const newestFirst = entries ? [...entries].sort((a, b) => b.star.at_ms - a.star.at_ms) : [];
  const groups = groupByDay(newestFirst);
  const ordered = groups.flatMap((g) => g.items);
  const selected = ordered.find((e) => String(e.star.at_ms) === star) ?? ordered[0] ?? null;
  const day = useDayView(selected?.day ?? null);
  const others = selected
    ? ordered.filter((e) => e !== selected && e.day === selected.day && e.star.conversation_id !== null
      && e.star.conversation_id === selected.star.conversation_id)
    : [];

  const list = groups.length > 0
    ? groups.map((g) => (
      <div class="list-group" key={g.day}>
        <h2 class="hd list-head"><span class="hd-day">{dayTitle(g.day)}</span><span class="hd-count">{g.items.length}</span></h2>
        {g.items.map((entry) => <StarRow key={entry.star.at_ms} entry={entry} selected={entry === selected} />)}
      </div>
    ))
    : <p class="hd">Starred moments</p>;

  let content;
  if (error) content = <p class="notice warn" role="alert">{error}</p>;
  else if (!entries) content = <p class="page-lead loading">Loading starred moments</p>;
  else if (entries.length === 0) {
    content = <Empty title="No starred moments yet">Press the pendant's button once to star the moment.</Empty>;
  } else if (selected) content = <Moment key={selected.star.at_ms} entry={selected} day={day} />;

  return (
    <Frame toolbar={{ title: "Starred", subtitle: entries && entries.length > 0 ? plural(entries.length, "moment", "moments") : undefined }}
      list={list} listLabel="Starred moments"
      inspector={selected && <MomentFacts key={selected.star.at_ms} entry={selected} day={day} others={others} />}
      inspectorLabel="This moment">
      <div class="page starred-page">{content}</div>
    </Frame>
  );
}
