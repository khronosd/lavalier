import type { Line } from "../api";
import { hms } from "../format";

/** One stretch of speech: its start time in the margin, the words in the reading face. */
export function TranscriptLine({ line }: { line: Line }) {
  return (
    <div class="line" id={`${line.clip_id}-${line.seq}`}>
      <time class="time" dateTime={new Date(line.at_ms).toISOString()}>{hms(line.at_ms)}</time>
      <p class="reading">{line.text}</p>
    </div>
  );
}

/** A star at its exact time inside a conversation. */
export function StarLine({ at_ms }: { at_ms: number }) {
  return (
    <div class="line star-line">
      <time class="time" dateTime={new Date(at_ms).toISOString()}>{hms(at_ms)}</time>
      <p><span aria-hidden="true">★ </span>Starred</p>
    </div>
  );
}
