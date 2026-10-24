import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import type { DayView } from "../api";
import { duration } from "../format";
import { audioKeptLine, buildPlaylist, type Scope } from "../playlist";
import { span } from "./Conversation";
import { Player } from "./Player";

interface Props {
  view: DayView;
  /** ?conv=: the conversation a Transcript-tab Play asked for; it starts at once. */
  conv?: string;
}

/** The day's audio: a row per conversation with Play, Play day, and one player. */
export function AudioTab({ view, conv }: Props) {
  const [scope, setScope] = useState<Scope | null>(conv ? { conversation: conv } : null);
  // every Play starts the player afresh, even on the same conversation
  const [run, setRun] = useState(0);
  const applied = useRef(conv);
  useEffect(() => {
    if (conv && conv !== applied.current) {
      applied.current = conv;
      setScope({ conversation: conv });
      setRun((n) => n + 1);
    }
  }, [conv]);

  const built = scope ? buildPlaylist(view, scope) : null;
  // the same clips keep the same arrays across a refetch of the day, so the player sees no change
  const sameAs = built ? JSON.stringify([built.clips, built.unavailable]) : "";
  const playlist = useMemo(() => built, [sameAs]);
  const anyKept = view.conversations.some((c) => c.audio_available && c.clip_ids.length > 0);
  const byId = new Map(view.conversations.map((c) => [c.conversation_id, c]));
  const gone = (playlist?.unavailable ?? []).map((id) => byId.get(id)).filter((c) => c !== undefined);

  function play(next: Scope) {
    setScope(next);
    setRun((n) => n + 1);
  }

  return (
    <div class="audio-tab">
      <div class="audio-day">
        <p class="audio-kept">{audioKeptLine(view)}</p>
        <button type="button" class="btn" disabled={!anyKept} onClick={() => play("day")}>Play day</button>
      </div>
      {gone.length > 0 && (
        <p class="audio-gone">{`Not in the playlist, its audio is no longer kept: ${gone.map(span).join(", ")}.`}</p>
      )}
      {playlist && playlist.clips.length > 0 && (
        <Player key={run} items={playlist.clips} conversations={view.conversations} />
      )}
      <ul class="audio-list">
        {view.conversations.map((c) => (
          <li key={c.conversation_id} class="audio-row">
            <h2 class="audio-row-title">{span(c)}</h2>
            <span class="audio-dur">{`${duration(c.speech_ms)} speech`}</span>
            {!c.audio_available && <span class="audio-unavailable">no longer kept</span>}
            <button type="button" class="btn" disabled={!c.audio_available}
              onClick={() => play({ conversation: c.conversation_id })}>Play</button>
          </li>
        ))}
      </ul>
    </div>
  );
}
