import { type Route, toHash } from "../router";

export const DAY_TABS = [
  { id: "transcript", label: "Transcript" },
  { id: "insights", label: "Insights" },
  { id: "audio", label: "Audio" },
] as const;

export type DayTab = (typeof DAY_TABS)[number]["id"];

/** The tab a day route asks for; anything unknown is the transcript. */
export function tabOf(route: Route): DayTab {
  const found = DAY_TABS.find((t) => t.id === route.query.tab);
  return found ? found.id : "transcript";
}

/** Transcript, Insights, Audio as a segmented control; each is a link to the same day with ?tab=. */
export function Tabs({ route }: { route: Route }) {
  const active = tabOf(route);
  return (
    <nav class="segmented" aria-label="Day views">
      {DAY_TABS.map((t) => (
        <a key={t.id} class="segment" href={toHash({ ...route, query: { tab: t.id } })}
          aria-current={t.id === active ? "page" : undefined}>{t.label}</a>
      ))}
    </nav>
  );
}
