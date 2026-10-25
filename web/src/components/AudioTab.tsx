import { useEffect, useRef, useState } from "preact/hooks";
import type { DayView } from "../api";
import { duration } from "../format";
import { usePlayback } from "../playback";
import { audioKeptLine, buildPlaylist, type Scope } from "../playlist";
import { span } from "./Conversation";
import { PlayIcon } from "./icons";

interface Props {
  view: DayView;
  /** ?conv=: the conversation a Play elsewhere asked for; it starts at once. */
  conv?: string;
}

/** The day's audio: a row per conversation with Play, and Play day. What plays goes to the window's player
 * (the mini-player at the bottom of the content column), which follows the clips from here on. */
export function AudioTab({ view, conv }: Props) {
  const playback = usePlayback();
  const [scope, setScope] = useState<Scope | null>(null);

  function start(next: Scope) {
    setScope(next);
    const built = buildPlaylist(view, next);
    playback.play(built.clips, view.conversations);
  }

  // every ?conv= starts that conversation afresh, once per value
  const applied = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (conv && conv !== applied.current) {
      applied.current = conv;
      start({ conversation: conv });
    }
  }, [conv]);

  const built = scope ? buildPlaylist(view, scope) : null;
  // a refetched day hands over the same clips in a new array: the player keeps what it plays, and only a
  // clip that changed under it reloads
  const sameAs = built ? JSON.stringify([built.clips, built.unavailable]) : "";
  useEffect(() => {
    if (built) playback.update(built.clips, view.conversations);
  }, [sameAs]);

  const anyKept = view.conversations.some((c) => c.audio_available && c.clip_ids.length > 0);
  const byId = new Map(view.conversations.map((c) => [c.conversation_id, c]));
  const gone = (built?.unavailable ?? []).map((id) => byId.get(id)).filter((c) => c !== undefined);

  return (
    <div class="audio-tab">
      <div class="audio-day">
        <p class="audio-kept">{audioKeptLine(view)}</p>
        <button type="button" class="btn" disabled={!anyKept} onClick={() => start("day")}><PlayIcon />Play day</button>
      </div>
      {gone.length > 0 && (
        <p class="audio-gone">{`Not in the playlist, its audio is no longer kept: ${gone.map(span).join(", ")}.`}</p>
      )}
      <ul class="audio-list">
        {view.conversations.map((c) => (
          <li key={c.conversation_id} class="audio-row">
            <h2 class="audio-row-title">{c.label ?? span(c)}</h2>
            {c.label && <span class="audio-span">{span(c)}</span>}
            <span class="audio-dur">{`${duration(c.speech_ms)} speech`}</span>
            {!c.audio_available && <span class="audio-unavailable">no longer kept</span>}
            <button type="button" class="btn" disabled={!c.audio_available}
              onClick={() => start({ conversation: c.conversation_id })}><PlayIcon />Play</button>
          </li>
        ))}
      </ul>
    </div>
  );
}
