// Inline 16px stroke icons in currentColor: 1.6px strokes, round caps and joins, as design E draws them.
// No icon font, nothing fetched. Sizes other than 16px come from the stylesheet of the place that uses one.

const common = {
  viewBox: "0 0 16 16", fill: "none", stroke: "currentColor", "stroke-width": 1.6,
  "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": true,
} as const;

const STAR = "M8 1.9l1.85 3.95 4.3.55-3.15 2.95.8 4.3L8 11.55l-3.8 2.1.8-4.3L1.85 6.4l4.3-.55z";
const SPARKLES = "M8 2l1.3 3.7L13 7l-3.7 1.3L8 12l-1.3-3.7L3 7l3.7-1.3zM13 11l.6 1.4 1.4.6-1.4.6L13 15l-.6-1.4-1.4-.6 1.4-.6z";

export const TodayIcon = () => (
  <svg {...common}><rect x="2" y="3" width="12" height="11" rx="2" /><path d="M2 6.5h12M5.5 1.5v3M10.5 1.5v3" /></svg>
);
export const StarIcon = () => <svg {...common}><path d={STAR} /></svg>;
/** The small filled star beside a count. */
export const StarFillIcon = () => <svg {...common} class="star-fill" fill="currentColor" stroke="none"><path d={STAR} /></svg>;
export const SearchIcon = () => (
  <svg {...common}><circle cx="7" cy="7" r="4.5" /><path d="M10.5 10.5L14 14" /></svg>
);
export const InsightsIcon = () => <svg {...common}><path d={SPARKLES} /></svg>;
export const SettingsIcon = () => (
  <svg {...common}>
    <circle cx="8" cy="8" r="2.5" />
    <path d="M8 1.5v2M8 12.5v2M1.5 8h2M12.5 8h2M3.4 3.4l1.4 1.4M11.2 11.2l1.4 1.4M3.4 12.6l1.4-1.4M11.2 4.8l1.4-1.4" />
  </svg>
);
export const SidebarIcon = () => (
  <svg {...common}><rect x="1.5" y="3" width="13" height="10" rx="2.5" /><path d="M6 3v10" /></svg>
);
export const PinIcon = () => <svg {...common}><path d="M6 2h4l-.5 4 2.5 2.5V10H4V8.5L6.5 6zM8 10v4.5" /></svg>;
export const ShareIcon = () => <svg {...common}><path d="M8 1.5v8M5 4.5l3-3 3 3M3.5 8v5.5h9V8" /></svg>;
export const ReturnIcon = () => <svg {...common}><path d="M13 3v4.5a2 2 0 0 1-2 2H3M5.5 7L3 9.5 5.5 12" /></svg>;
export const ClockIcon = () => <svg {...common}><circle cx="8" cy="8" r="5.5" /><path d="M8 4.5V8l2.5 1.5" /></svg>;
export const BluetoothIcon = () => <svg {...common}><path d="M4.5 5l7 6-3.5 3.5v-13L11.5 5l-7 6" /></svg>;
export const LinkIcon = () => (
  <svg {...common}><path d="M6.5 9.5l3-3M5 7L3.5 8.5a2.5 2.5 0 0 0 3.5 3.5L8.5 10.5M11 9l1.5-1.5a2.5 2.5 0 0 0-3.5-3.5L7.5 5.5" /></svg>
);
export const DriveIcon = () => (
  <svg {...common}><rect x="2" y="9" width="12" height="5" rx="1.5" /><path d="M3.5 9l1.5-6h6l1.5 6M11.5 11.5h.01" /></svg>
);
export const HalfCircleIcon = () => (
  <svg {...common}><circle cx="8" cy="8" r="5.5" /><path d="M8 2.5v11a5.5 5.5 0 0 0 0-11z" fill="currentColor" stroke="none" /></svg>
);
export const CheckIcon = () => <svg {...common}><path d="M3.5 8.5l3 3 6-7" /></svg>;
export const RefreshIcon = () => <svg {...common}><path d="M13.5 8a5.5 5.5 0 1 1-1.6-3.9M13.5 2.5v2.5H11" /></svg>;
export const ChevronLeftIcon = () => <svg {...common}><path d="M10 3L5 8l5 5" /></svg>;
export const ChevronRightIcon = () => <svg {...common}><path d="M6 3l5 5-5 5" /></svg>;
export const ChevronUpIcon = () => <svg {...common}><path d="M3 10l5-5 5 5" /></svg>;
export const ChevronDownIcon = () => <svg {...common}><path d="M3 6l5 5 5-5" /></svg>;
export const EllipsisIcon = () => (
  <svg {...common}><circle cx="3.5" cy="8" r="1" fill="currentColor" /><circle cx="8" cy="8" r="1" fill="currentColor" /><circle cx="12.5" cy="8" r="1" fill="currentColor" /></svg>
);
export const WaveformIcon = () => <svg {...common}><path d="M2 6v4M5 3.5v9M8 1.5v13M11 4v8M14 6.5v3" /></svg>;
export const PlayIcon = () => <svg {...common}><path d="M5 2.8v10.4l8.5-5.2z" fill="currentColor" stroke="none" /></svg>;
export const PauseIcon = () => <svg {...common} stroke-width={2.2}><path d="M5.5 3.5v9M10.5 3.5v9" /></svg>;
export const CloseIcon = () => <svg {...common}><path d="M4 4l8 8M12 4l-8 8" /></svg>;

/** A battery whose fill is the charge, 0 to 100. */
export const BatteryIcon = ({ soc }: { soc: number }) => {
  const fill = Math.round((Math.max(0, Math.min(100, soc)) / 100) * 78) / 10;
  return (
    <svg {...common} class="battery">
      <rect x="1" y="4.5" width="12" height="7" rx="2" />
      <path d="M14.5 7v2" />
      {fill > 0 && <rect x="2.3" y="5.8" width={fill} height="4.4" rx="1" fill="currentColor" stroke="none" />}
    </svg>
  );
};
export const PendantIcon = () => (
  <svg {...common}><rect x="4.5" y="1.5" width="7" height="13" rx="3.5" /><circle cx="8" cy="5" r="1.4" fill="currentColor" stroke="none" /></svg>
);
export const CopyIcon = () => (
  <svg {...common}><rect x="5" y="5" width="9" height="9" rx="2" /><path d="M11 5V3.5A1.5 1.5 0 0 0 9.5 2h-6A1.5 1.5 0 0 0 2 3.5v6A1.5 1.5 0 0 0 3.5 11H5" /></svg>
);
