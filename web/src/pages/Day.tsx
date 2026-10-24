import type { ComponentChildren } from "preact";
import { useEffect, useState } from "preact/hooks";
import { api, type DayView, explainError } from "../api";
import { AudioTab } from "../components/AudioTab";
import { Conversation } from "../components/Conversation";
import { DayHeader } from "../components/DayHeader";
import { Empty } from "../components/Empty";
import { Starred } from "../components/Starred";
import { Tabs, tabOf } from "../components/Tabs";
import { pendingSentence, summarySentence } from "../day";
import { navigate, type Route } from "../router";
import { useJumpTo } from "../useJumpTo";

interface Props {
  date: string;
  isToday: boolean;
  /** The today or day route being shown; tabs and Play keep to it. */
  route: Route;
  nav?: ComponentChildren;
}

type Load = { date: string; view: DayView | null; error: string | null };

function TabPanel({ route, view, onPin }: {
  route: Route; view: DayView; onPin: (id: string, pinned: boolean) => Promise<void>;
}) {
  switch (tabOf(route)) {
    case "insights":
      return <Empty title="Insights are not available yet" />;
    case "audio":
      return <AudioTab view={view} conv={route.query.conv} />;
    default:
      return (
        <>
          <Starred stars={view.stars} conversations={view.conversations} route={route} />
          {view.conversations.map((c) => (
            <Conversation key={c.conversation_id} conv={c} onPin={(p) => onPin(c.conversation_id, p)}
              onPlay={() => navigate({ ...route, query: { tab: "audio", conv: c.conversation_id } })} />
          ))}
        </>
      );
  }
}

/** A day: its title and summary, the tabs, and the transcript with starred moments and pins. */
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

  async function pin(id: string, pinned: boolean) {
    await api<unknown>("POST", `/api/${pinned ? "pin" : "unpin"}/${encodeURIComponent(id)}`);
    setLoad((cur) => cur.view && cur.date === date
      ? { ...cur, view: { ...cur.view, conversations: cur.view.conversations.map((c) =>
          c.conversation_id === id ? { ...c, pinned } : c) } }
      : cur);
    // a pin can change how long the day's audio is kept; refresh the summary quietly
    api<DayView>("GET", `/api/day/${date}`).then(
      (view) => setLoad((cur) => (cur.date === date ? { date, view, error: null } : cur)),
      () => undefined,
    );
  }

  const view = load.date === date ? load.view : null;
  const error = load.date === date ? load.error : null;
  useJumpTo(route.query.at, view !== null);

  if (error) {
    return (
      <div class="page day-page">
        <DayHeader date={date} nav={nav} />
        <p class="notice warn" role="alert">{error}</p>
      </div>
    );
  }
  if (!view) {
    return (
      <div class="page day-page" aria-busy="true">
        <DayHeader date={date} nav={nav} />
        <p class="day-summary loading">Loading this day</p>
      </div>
    );
  }
  if (view.conversations.length === 0) {
    return (
      <div class="page day-page">
        <DayHeader date={date} nav={nav} />
        {isToday
          ? <Empty title="Nothing recorded yet today">{pendingSentence(view.pending_pages)}</Empty>
          : <Empty title="No conversations on this day" />}
      </div>
    );
  }
  return (
    <div class="page day-page">
      <DayHeader date={date} summary={summarySentence(view)} nav={nav} />
      <Tabs route={route} />
      <div class="day-body">
        <TabPanel route={route} view={view} onPin={pin} />
      </div>
    </div>
  );
}
