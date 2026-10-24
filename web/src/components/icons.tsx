// Inline 16px stroke icons, drawn in currentColor. No icon font, nothing fetched.

const common = { viewBox: "0 0 16 16", fill: "none", stroke: "currentColor", "stroke-width": 1.5, "aria-hidden": true };

export const TodayIcon = () => (
  <svg {...common}><circle cx="8" cy="8" r="6" /><path d="M8 4.5V8l2.5 1.5" /></svg>
);
export const JournalIcon = () => (
  <svg {...common}><rect x="2.5" y="3" width="11" height="10" rx="1.5" /><path d="M2.5 6.5h11M5.5 2v2M10.5 2v2" /></svg>
);
export const StarIcon = () => (
  <svg {...common}><path d="M8 2.5l1.7 3.6 3.9.5-2.9 2.7.8 3.9L8 11.3l-3.5 1.9.8-3.9L2.4 6.6l3.9-.5z" /></svg>
);
export const SearchIcon = () => (
  <svg {...common}><circle cx="7" cy="7" r="4.5" /><path d="M10.5 10.5 14 14" /></svg>
);
export const InsightsIcon = () => (
  <svg {...common}><path d="M3 12l3-4 3 2 4-6" /><path d="M2.5 13.5h11" /></svg>
);
export const SettingsIcon = () => (
  <svg {...common}>
    <circle cx="8" cy="8" r="2.3" />
    <path d="M8 1.8v2M8 12.2v2M1.8 8h2M12.2 8h2M3.6 3.6l1.4 1.4M11 11l1.4 1.4M3.6 12.4 5 11M11 5l1.4-1.4" />
  </svg>
);
