// Text for times and durations. Fixed English tables, never the locale, so output is stable.

const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
  "October", "November", "December"];

const pad = (n: number) => String(n).padStart(2, "0");

/** Local wall-clock time of an epoch ms, "22:56:07". */
export function hms(ms: number): string {
  const d = new Date(ms);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

/** Local wall-clock time of an epoch ms, "22:56". */
export function hm(ms: number): string {
  const d = new Date(ms);
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** A length of time: "16 s" under a minute, "16 min", "3 h 1 min", "2 h". */
export function duration(ms: number): string {
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s} s`;
  const min = Math.round(s / 60);
  if (min < 60) return `${min} min`;
  const h = Math.floor(min / 60);
  const rest = min % 60;
  return rest ? `${h} h ${rest} min` : `${h} h`;
}

/** "2026-10-24" -> "Friday, 24 October". */
export function dayTitle(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  const weekday = new Date(Date.UTC(y, m - 1, d)).getUTCDay();
  return `${WEEKDAYS[weekday]}, ${d} ${MONTHS[m - 1]}`;
}

/** How old a reading is: "just now", "as of 2 min ago", "as of 2 h ago". */
export function age(seconds: number): string {
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `as of ${Math.floor(seconds / 60)} min ago`;
  return `as of ${Math.floor(seconds / 3600)} h ago`;
}

/** The local date of an epoch ms as ISO, "2026-10-24" (the server's days are local days). */
export function isoDay(ms: number): string {
  const d = new Date(ms);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}
