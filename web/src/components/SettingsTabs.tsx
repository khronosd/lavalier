import { toHash } from "../router";

export const TABS = [
  { id: "general", label: "General" },
  { id: "pendant", label: "Pendant" },
  { id: "retention", label: "Retention" },
  { id: "connectors", label: "Connectors" },
  { id: "model", label: "Model" },
  { id: "appearance", label: "Appearance" },
] as const;

export function SettingsTabs({ tab }: { tab: string }) {
  return (
    <nav class="set-nav" aria-label="Settings">
      {TABS.map((t) => (
        <a key={t.id} class="set-tab" href={toHash({ name: "settings", params: { tab: t.id }, query: {} })}
          aria-current={t.id === tab ? "page" : undefined}>{t.label}</a>
      ))}
    </nav>
  );
}
