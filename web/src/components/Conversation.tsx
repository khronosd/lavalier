import { useState } from "preact/hooks";
import type { ConversationView } from "../api";
import { placeStars } from "../day";
import { duration, hm } from "../format";
import { StarLine, TranscriptLine } from "./TranscriptLine";

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

/** One conversation of the transcript: its heading, tools, and lines with stars in place. */
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
        <h2 class="conv-title" id={`h-${conv.conversation_id}`}>{span(conv)}</h2>
        <span class="conv-dur">{`${duration(conv.speech_ms)} speech`}</span>
        {stars > 0 && <span class="conv-stars" aria-label={`${stars} starred`}>{"★".repeat(stars)}</span>}
        {conv.pinned && <span class="conv-pinned">pinned</span>}
        <div class="conv-tools">
          <button type="button" class="btn" onClick={onPlay} disabled={!conv.audio_available}
            title={conv.audio_available ? undefined : "The audio of this conversation is no longer kept."}>Play</button>
          <button type="button" class="btn" onClick={toggle} disabled={busy}>{conv.pinned ? "Unpin" : "Pin"}</button>
        </div>
      </header>
      {error && <p class="conv-error" role="alert">{error}</p>}
      {conv.label && <p class="conv-label">{conv.label}</p>}
      {placeStars(conv).map((item) =>
        item.kind === "line"
          ? <TranscriptLine key={`${item.line.clip_id}-${item.line.seq}`} line={item.line} />
          : <StarLine key={`star-${item.at_ms}`} at_ms={item.at_ms} />)}
    </section>
  );
}
