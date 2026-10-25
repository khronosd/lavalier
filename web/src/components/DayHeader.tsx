import type { ComponentChildren } from "preact";
import { dayTitle } from "../format";

interface Props {
  date: string;
  /** The day's one-line count (day.ts summaryLine); none while the day loads. */
  summary?: string | null;
  /** DayNav, at the right. */
  nav?: ComponentChildren;
}

/** The band's header row: the day's name, its date beside it, the count line, and the day navigation. */
export function DayHeader({ date, summary, nav }: Props) {
  const [name, rest] = dayTitle(date).split(", ");
  return (
    <header class="day-band-head">
      <h1 class="day-title">
        <span class="day-name">{name}</span>
        <span class="sr">, </span>
        <span class="day-date">{rest}</span>
      </h1>
      {summary && <p class="day-summary">{summary}</p>}
      {nav}
    </header>
  );
}
