import { useEffect, useState } from "preact/hooks";
import { api, ApiError, type DaySummary, type Settings } from "./api";
import { Shell } from "./components/Shell";
import { dayTitle, isoDay } from "./format";
import { Placeholder } from "./pages/Placeholder";
import { type Route, useRoute } from "./router";
import { applyAppearance } from "./theme";

function loadError(e: unknown): string {
  if (e instanceof ApiError && e.status === 401) {
    return "This window could not sign in to the lavalier app. Close it and open it again from the app.";
  }
  const why = e instanceof Error ? e.message : String(e);
  return `The days could not be loaded (${why}). Check that the lavalier app is running, then reload.`;
}

function Page({ route, today }: { route: Route; today: string }) {
  switch (route.name) {
    case "day":
      return <Placeholder title={dayTitle(route.params.date)} emptyTitle="This day's transcript is not shown here yet" />;
    case "starred":
      return <Placeholder title="Starred" emptyTitle="Starred moments will be listed here" />;
    case "search":
      return <Placeholder title="Search" emptyTitle="Search is not available here yet" />;
    case "insights":
      return <Placeholder title="Insights" emptyTitle="Insights are not available yet" />;
    case "settings":
      return <Placeholder title="Settings" emptyTitle="Settings are not editable here yet" />;
    default:
      return <Placeholder title={dayTitle(today)} lead="Today"
        emptyTitle="Nothing from today yet">Conversations appear here after the next sync.</Placeholder>;
  }
}

export function App() {
  const route = useRoute();
  const [days, setDays] = useState<DaySummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const today = isoDay(Date.now());

  useEffect(() => {
    // the stored appearance; until it arrives (or if it cannot), the window follows the system
    api<Settings>("GET", "/api/settings").then((s) => applyAppearance(s.appearance), () => undefined);
    api<DaySummary[]>("GET", "/api/days").then(setDays, (e) => {
      setDays([]);
      setError(loadError(e));
    });
  }, []);

  return (
    <Shell route={route} days={days} today={today}>
      {error && <div class="page page-notice"><p class="notice" role="alert">{error}</p></div>}
      <Page route={route} today={today} />
    </Shell>
  );
}
