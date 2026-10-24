import type { ComponentChildren } from "preact";
import { dayTitle } from "../format";

interface Props {
  date: string;
  summary?: string | null;
  /** DayNav, drawn to the right of the title. */
  nav?: ComponentChildren;
}

export function DayHeader({ date, summary, nav }: Props) {
  return (
    <header class="day-header">
      <div class="day-header-row">
        <h1 class="day-title">{dayTitle(date)}</h1>
        {nav}
      </div>
      {summary && <p class="day-summary">{summary}</p>}
    </header>
  );
}
