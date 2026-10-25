import type { ComponentChildren } from "preact";
import type { Settings } from "../api";
import { secondsToMinutes } from "../settings";
import { toHash } from "../router";
import {
  BluetoothIcon, ChevronRightIcon, DriveIcon, HalfCircleIcon, InsightsIcon, LinkIcon, SettingsIcon,
} from "./icons";
import { PROVIDER_CHOICES } from "./ProviderPicker";

export const TABS = [
  { id: "general", label: "General" },
  { id: "pendant", label: "Pendant" },
  { id: "retention", label: "Storage" },
  { id: "model", label: "Model" },
  { id: "connectors", label: "Connectors" },
  { id: "appearance", label: "Appearance" },
] as const;

const ICONS: Record<(typeof TABS)[number]["id"], () => ComponentChildren> = {
  general: SettingsIcon, pendant: BluetoothIcon, retention: DriveIcon, model: InsightsIcon, connectors: LinkIcon,
  appearance: HalfCircleIcon,
};

const APPEARANCE: Record<string, string> = { system: "System", light: "Light", dark: "Dark" };

/** A section's second line: the setting that says most about it, once the settings are known. */
function subline(id: (typeof TABS)[number]["id"], s: Settings | null): string {
  if (!s) return "";
  switch (id) {
    case "general": return `Every ${secondsToMinutes(s.poll_interval_s)} min`;
    case "pendant": return s.pendant_address || "No address";
    case "retention": return `${s.retention_days} ${s.retention_days === 1 ? "day" : "days"} of audio`;
    case "model": return PROVIDER_CHOICES.find((p) => p.id === s.insights_provider)?.label ?? s.insights_provider;
    case "connectors": return [s.notion_enabled && "Notion", s.calendar_enabled && "Calendar"].filter(Boolean).join(", ") || "Off";
    case "appearance": return APPEARANCE[s.appearance] ?? s.appearance;
  }
}

/** The sections as rows in the list column: a coloured tile, the name, the setting that says most about it. */
export function SettingsTabs({ tab, settings }: { tab: string; settings: Settings | null }) {
  return (
    <>
      <p class="hd">Sections</p>
      {TABS.map((t) => {
        const Icon = ICONS[t.id];
        const sub = subline(t.id, settings);
        return (
          <a key={t.id} class={t.id === tab ? "row set-row selected" : "row set-row"}
            href={toHash({ name: "settings", params: { tab: t.id }, query: {} })} aria-current={t.id === tab ? "page" : undefined}>
            <span class={`tile tile-${t.id}`} aria-hidden="true"><Icon /></span>
            <span class="row-text">
              <span class="row-title">{t.label}</span>
              {sub && <span class="row-sub">{sub}</span>}
            </span>
            <span class="row-chevron" aria-hidden="true"><ChevronRightIcon /></span>
          </a>
        );
      })}
    </>
  );
}
