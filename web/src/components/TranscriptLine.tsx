import type { Line } from "../api";
import { hms } from "../format";
import { markWords } from "../search";
import { StarFillIcon } from "./icons";

interface Props {
  line: Line;
  /** The line is starred: tinted, with the star before its time. */
  starred?: boolean;
  /** A search's words, each occurrence marked. */
  words?: string;
  /** The line a search hit points at: tinted. */
  hit?: boolean;
}

/** One stretch of speech: its start time in the margin, the words in the reading face. */
export function TranscriptLine({ line, starred, words, hit }: Props) {
  const cls = ["line", starred ? "starred" : "", hit ? "hit-line" : ""].filter(Boolean).join(" ");
  return (
    <div class={cls} id={`${line.clip_id}-${line.seq}`}>
      <span class="time-cell">
        {starred && <StarFillIcon />}
        <time class="time" dateTime={new Date(line.at_ms).toISOString()}>{hms(line.at_ms)}</time>
      </span>
      <p class="reading">{words ? markWords(line.text, words) : line.text}</p>
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
