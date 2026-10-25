import { useState } from "preact/hooks";
import type { ConversationView } from "../api";
import { transcriptItems } from "../day";
import { duration, hm } from "../format";
import { PinIcon, PlayIcon } from "./icons";
import { QuietGap, StarLine, TranscriptLine } from "./TranscriptLine";

interface Props {
  conv: ConversationView;
  /** Pin or unpin; rejects with the reason when the app refuses. */
  onPin: (pinned: boolean) => Promise<void>;
  onPlay: () => void;
}

/** "17:33 to 20:40", or "22:56" when it starts and ends in the same minute. */
export function span(conv: ConversationView): string {
  const start = hm(conv.start_ms);
  const end = hm(conv.end_ms);
  return start === end ? start : `${start} to ${end}`;
}

/** One conversation: its title (the calendar event it overlaps when labelled, else its time range), under it
 *  the range, the speech total and the stars ("09:12 to 09:41 · 16 min speech ★★"), Play and Pin, then its
 *  lines with the starred ones marked and quiet gaps between lines far apart. */
export function Conversation({ conv, onPin, onPlay }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const stars = conv.star_ms.length;

  async function toggle() {
    const pin = !conv.pinned;
    setBusy(true);
    setError(null);
    try {
      await onPin(pin);
    } catch (e) {
      setError(`Could not ${pin ? "pin" : "unpin"}: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section class="conv" id={`c-${conv.conversation_id}`} tabIndex={-1} aria-labelledby={`h-${conv.conversation_id}`}>
      <header class="conv-head">
        <div class="conv-heading">
          <h2 class="conv-title" id={`h-${conv.conversation_id}`}>{conv.label ?? span(conv)}</h2>
          <p class="conv-meta">
            <span class="conv-dur">
              {conv.label && `${span(conv)} · `}
              {`${duration(conv.speech_ms)} speech`}
              {stars > 0 && " "}
              {stars > 0 && <span class="conv-stars" aria-label={`${stars} starred`}>{"★".repeat(stars)}</span>}
            </span>
            {conv.pinned && <span class="conv-pinned">pinned</span>}
          </p>
        </div>
        <div class="conv-tools">
          <button type="button" class="btn" onClick={onPlay} disabled={!conv.audio_available}
            title={conv.audio_available ? undefined : "The audio of this conversation is no longer kept."}><PlayIcon />Play</button>
          <button type="button" class="btn" onClick={toggle} disabled={busy}><PinIcon />{conv.pinned ? "Unpin" : "Pin"}</button>
        </div>
      </header>
      {error && <p class="conv-error" role="alert">{error}</p>}
      {transcriptItems(conv).map((item, i) =>
        item.kind === "line"
          ? <TranscriptLine key={`${item.line.clip_id}-${item.line.seq}`} line={item.line} starred={item.starred} />
          : item.kind === "star"
            ? <StarLine key={`star-${item.at_ms}`} at_ms={item.at_ms} />
            : <QuietGap key={`gap-${i}`} minutes={item.minutes} />)}
    </section>
  );
}
