import { useEffect, useState } from "preact/hooks";
import { api, type DaySummary, explainError } from "./api";
import { PendantCard } from "./components/PendantCard";
import { Shell } from "./components/Shell";
import { isoDay } from "./format";
import { Journal } from "./pages/Journal";
import { Insights } from "./pages/Insights";
import { Search } from "./pages/Search";
import { Settings } from "./pages/Settings";
import { StarredPage } from "./pages/Starred";
import { DataVersion, dataVersion, useOnVersionChange } from "./refresh";
import { type Route, useRoute } from "./router";
import { usePendantStatus } from "./usePendantStatus";

function Page({ route, today, days }: { route: Route; today: string; days: DaySummary[] | null }) {
  switch (route.name) {
    case "starred":
      return <StarredPage />;
    case "search":
      return <Search q={route.query.q ?? ""} />;
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

export function App() {
  const route = useRoute();
  const today = useToday();
  const pendant = usePendantStatus();
  const version = dataVersion(pendant.status);
  const [days, setDays] = useState<DaySummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

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
      <Shell route={route} days={days} today={today} pendant={<PendantCard pendant={pendant} />}>
        {error && <div class="page page-notice"><p class="notice warn" role="alert">{error}</p></div>}
        <Page route={route} today={today} days={days} />
      </Shell>
    </DataVersion.Provider>
  );
}
