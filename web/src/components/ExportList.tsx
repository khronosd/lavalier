import type { ExportRow } from "../api";
import { canExportAgain, exportRowState } from "../connectors";
import { dayTitle } from "../format";

interface Props {
  rows: ExportRow[];
  /** An export is running: Export again waits for it. */
  busy: boolean;
  onAgain: (row: ExportRow) => void;
}

/** The last exports to Notion, newest first: the day, when it went or why not, and Export again on a day
 *  stopped by a hand edit or failed. */
export function ExportList({ rows, busy, onAgain }: Props) {
  const sorted = [...rows].sort((a, b) => (a.day < b.day ? 1 : a.day > b.day ? -1 : 0));
  return (
    <div class="exp">
      <h3 class="con-sub">Last exports</h3>
      {sorted.length === 0
        ? <p class="field-help">Nothing has been exported yet. Export the last 7 days to start.</p>
        : (
          <ul class="exp-list">
            {sorted.map((row) => (
              <li key={row.day} class={`exp-row exp-${row.state}`}>
                <span class="exp-day">{dayTitle(row.day)}</span>
                <span class="exp-state">{exportRowState(row)}</span>
                {canExportAgain(row) && (
                  <button class="btn" type="button" disabled={busy} onClick={() => onAgain(row)}>Export again</button>
                )}
              </li>
            ))}
          </ul>
        )}
    </div>
  );
}
