import type { Line } from "../api";
import { hms } from "../format";
import { StarFillIcon } from "./icons";

/** One stretch of speech: its start time in the margin, the words in the reading face. A starred line
 * is tinted, with the star before its time. */
export function TranscriptLine({ line, starred }: { line: Line; starred?: boolean }) {
  return (
    <div class={starred ? "line starred" : "line"} id={`${line.clip_id}-${line.seq}`}>
      <span class="time-cell">
        {starred && <StarFillIcon />}
        <time class="time" dateTime={new Date(line.at_ms).toISOString()}>{hms(line.at_ms)}</time>
      </span>
      <p class="reading">{line.text}</p>
    </div>
  );
}

/** A star at its exact time inside a conversation, when no line follows it. */
export function StarLine({ at_ms }: { at_ms: number }) {
  return (
    <div class="line star-line">
      <time class="time" dateTime={new Date(at_ms).toISOString()}>{hms(at_ms)}</time>
      <p><span aria-hidden="true">★ </span>Starred</p>
    </div>
  );
}

/** "6 minutes quiet" between two lines far apart. */
export function QuietGap({ minutes }: { minutes: number }) {
  return <p class="quiet">{`${minutes} minutes quiet`}</p>;
}
