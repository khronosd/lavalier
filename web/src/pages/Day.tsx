import type { ComponentChildren } from "preact";
import { useEffect, useRef, useState } from "preact/hooks";
import { api, type ConversationView, type DayView, explainError } from "../api";
import { AudioTab } from "../components/AudioTab";
import { Conversation } from "../components/Conversation";
import { ConversationRow } from "../components/ConversationRow";
import { DayHeader } from "../components/DayHeader";
import { Empty } from "../components/Empty";
import { Frame } from "../components/Frame";
import { InsightsIcon } from "../components/icons";
import { InsightsTab } from "../components/InsightsTab";
import { Starred } from "../components/Starred";
import { Tabs, tabOf } from "../components/Tabs";
import { TimelineBand } from "../components/TimelineBand";
import { partOfDay, pendingSentence, summaryLine } from "../day";
import { useOnDataChange } from "../refresh";
import { navigate, type Route, toHash } from "../router";
import { namedConversation, selectedConversation } from "../selection";
import { useJumpTo } from "../useJumpTo";

interface Props {
  date: string;
  isToday: boolean;
  /** The today or day route being shown; tabs, rows and Play keep to it. */
  route: Route;
  nav?: ComponentChildren;
}

type Load = { date: string; view: DayView | null; error: string | null };

/** The list column: a row per conversation under the part of the day it started in; a row links to the
 * same route with ?conv= naming it (and no ?at=, which is a one-time jump). */
function ConversationList({ view, selected, route }: { view: DayView; selected: string | null; route: Route }) {
  const groups: { name: string; convs: ConversationView[] }[] = [];
  for (const c of view.conversations) {
    const name = partOfDay(c.start_ms);
    const last = groups[groups.length - 1];
    if (last && last.name === name) last.convs.push(c);
    else groups.push({ name, convs: [c] });
  }
  const { at: _at, ...rest } = route.query;
  return (
    <>
      {groups.map((g) => (
        <div class="list-group" key={g.name}>
          <p class="hd">{g.name}</p>
          {g.convs.map((c) => (
            <ConversationRow key={c.conversation_id} conv={c} selected={c.conversation_id === selected}
              href={toHash({ ...route, query: { ...rest, conv: c.conversation_id } })} />
          ))}
        </div>
      ))}
    </>
  );
}

/** A day: the band with its name and count, the conversations as rows, the selected one's transcript (or
 * the Audio tab), and the inspector with the day's starred moments and its insight. */
export function Day({ date, isToday, route, nav }: Props) {
  const [load, setLoad] = useState<Load>({ date, view: null, error: null });

  useEffect(() => {
    let live = true;
    setLoad({ date, view: null, error: null });
    api<DayView>("GET", `/api/day/${date}`).then(
      (view) => live && setLoad({ date, view, error: null }),
      (e) => live && setLoad({ date, view: null, error: explainError(e, "This day") }),
    );
    return () => { live = false; };
  }, [date]);

  /** Fetch the day again in place: the page stays as it is (no loading state, same scroll) until the new
   * view arrives, and stays as it is if the fetch fails. */
  const lastRefresh = useRef(0);
  function refreshQuietly() {
    const n = ++lastRefresh.current; // latest wins: an older reply landing late must not undo a pin
    api<DayView>("GET", `/api/day/${date}`).then(
      (view) => n === lastRefresh.current && setLoad((cur) => (cur.date === date ? { date, view, error: null } : cur)),
      () => undefined,
    );
  }

  // a sync or a processing run may have added lines to this day
  useOnDataChange(refreshQuietly);

  async function pin(id: string, pinned: boolean) {
    await api<unknown>("POST", `/api/${pinned ? "pin" : "unpin"}/${encodeURIComponent(id)}`);
    setLoad((cur) => cur.view && cur.date === date
      ? { ...cur, view: { ...cur.view, conversations: cur.view.conversations.map((c) =>
          c.conversation_id === id ? { ...c, pinned } : c) } }
      : cur);
    refreshQuietly(); // a pin can change how long the day's audio is kept
  }

  const view = load.date === date ? load.view : null;
  const error = load.date === date ? load.error : null;

  // the selected conversation: the one the route names, remembered once ?at= is dropped, else the first
  const named = view ? namedConversation(view, route) : null;
  const [remembered, setRemembered] = useState<string | null>(null);
  useEffect(() => { if (named) setRemembered(named); }, [named]);
  const selected = view ? selectedConversation(view, named, remembered) : null;
  const conv = view && selected ? view.conversations.find((c) => c.conversation_id === selected) ?? null : null;
  useJumpTo(route.query.at, view !== null);

  const list = view && view.conversations.length > 0
    ? <ConversationList view={view} selected={selected} route={route} />
    : <p class="hd">Conversations</p>;
  const inspector = view && (
    <>
      <p class="insp-title"><InsightsIcon /> Insights</p>
      <Starred stars={view.stars} conversations={view.conversations} route={route} />
      <InsightsTab key={view.day} day={view.day} view={view} />
    </>
  );

  let content: ComponentChildren;
  if (error) content = <p class="notice warn" role="alert">{error}</p>;
  else if (!view) content = <p class="day-summary loading">Loading this day</p>;
  else if (view.conversations.length === 0) {
    content = isToday
      ? <Empty title="Nothing recorded yet today">{pendingSentence(view.pending_pages)}</Empty>
      : <Empty title="No conversations on this day" />;
  } else if (tabOf(route) === "audio") content = <AudioTab view={view} conv={route.query.conv} />;
  else if (conv) {
    content = (
      <Conversation key={conv.conversation_id} conv={conv} onPin={(p) => pin(conv.conversation_id, p)}
        onPlay={() => navigate({ ...route, query: { tab: "audio", conv: conv.conversation_id } })} />
    );
  }

  return (
    <Frame toolbar={{ children: <Tabs route={route} /> }}
      band={(
        <>
          <DayHeader date={date} summary={view ? summaryLine(view) : null} nav={nav} />
          {view && <TimelineBand view={view} selected={selected} route={route} />}
        </>
      )}
      list={list} listLabel="Conversations" inspector={inspector} inspectorLabel="Insights"
      focusInspector={route.query.tab === "insights" ? toHash(route) : undefined}>
      <div class="page day-page" aria-busy={!view && !error ? "true" : undefined}>
        <div class="day-body">{content}</div>
      </div>
    </Frame>
  );
}
