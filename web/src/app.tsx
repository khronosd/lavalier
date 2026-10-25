import { useEffect, useState } from "preact/hooks";
import { api, type DaySummary, explainError, type InsightsIndex, type Status } from "./api";
import { Shell } from "./components/Shell";
import { isoDay } from "./format";
import { PlaybackProvider } from "./playback";
import { Journal } from "./pages/Journal";
import { Insights } from "./pages/Insights";
import { Search } from "./pages/Search";
import { Settings } from "./pages/Settings";
import { StarredPage } from "./pages/Starred";
import { DataVersion, dataVersion, useOnInsightsChange, useOnVersionChange } from "./refresh";
import { type Route, useRoute } from "./router";
import { usePendantStatus } from "./usePendantStatus";

function Page({ route, today, days }: { route: Route; today: string; days: DaySummary[] | null }) {
  switch (route.name) {
    case "starred":
      return <StarredPage star={route.query.star} />;
    case "search":
      return <Search q={route.query.q ?? ""} hit={route.query.hit} />;
    case "insights":
      return <Insights />;
    case "settings":
      return <Settings tab={route.params.tab ?? "general"} />;
    default:
      return <Journal route={route} today={today} days={days} />;
  }
}

/** The local date, recomputed when the window comes back into view (it may have been left open past midnight). */
function useToday(): string {
  const [today, setToday] = useState(() => isoDay(Date.now()));
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === "visible") setToday(isoDay(Date.now()));
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, []);
  return today;
}

/** The days still without an insight, for the sidebar: read only while a provider is set, again when
 *  the data, the provider or the days being generated change, and after a Generate in this window. */
function useInsightsTodo(status: Status | null, version: string | null): number {
  const [todo, setTodo] = useState(0);
  const provider = status?.insights?.provider ?? "";
  const key = provider ? `${version}|${provider}|${status?.insights?.generating.join(",") ?? ""}` : null;
  const [bump, setBump] = useState(0);
  useOnInsightsChange(() => setBump((n) => n + 1));
  useEffect(() => {
    if (key === null) {
      setTodo(0);
      return;
    }
    let live = true;
    api<InsightsIndex>("GET", "/api/insights").then((i) => live && setTodo(i.days_without.length), () => undefined);
    return () => { live = false; };
  }, [key, bump]);
  return todo;
}

export function App() {
  const route = useRoute();
  const today = useToday();
  const pendant = usePendantStatus();
  const version = dataVersion(pendant.status);
  const [days, setDays] = useState<DaySummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const insightsTodo = useInsightsTodo(pendant.status, version);

  /** The first load shows its failure; a refetch after new data keeps the list it has if it fails. */
  function loadDays(quiet: boolean) {
    api<DaySummary[]>("GET", "/api/days").then((list) => {
      setDays(list);
      setError(null);
    }, (e) => {
      if (quiet) return;
      setDays([]);
      setError(explainError(e, "The days"));
    });
  }

  useEffect(() => loadDays(false), []);
  useOnVersionChange(version, () => loadDays(true));

  return (
    <DataVersion.Provider value={version}>
      <PlaybackProvider>
      <Shell route={route} days={days} today={today} pendant={pendant}
        insightsTodo={insightsTodo}>
        {error && <div class="page page-notice"><p class="notice warn" role="alert">{error}</p></div>}
        <Page route={route} today={today} days={days} />
      </Shell>
      </PlaybackProvider>
    </DataVersion.Provider>
  );
}
