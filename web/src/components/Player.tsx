import { useEffect, useRef, useState } from "preact/hooks";
import { type ConversationView, fetchAudioBlobUrl } from "../api";
import { audioErrorLine, type PlaylistItem } from "../playlist";
import { span } from "./Conversation";

interface Props {
  items: PlaylistItem[];
  conversations: ConversationView[];
}

const clock = (s: number) => {
  const whole = Number.isFinite(s) ? Math.floor(s) : 0;
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
};

/** One <audio> element fed clip by clip. Each clip is fetched as a Blob URL (the API needs the token
 * header, which an audio src cannot carry); the previous URL is revoked when the next one starts and
 * the last on unmount. A clip that fails stops the player on it, with the reason. */
export function Player({ items, conversations }: Props) {
  const audio = useRef<HTMLAudioElement>(null);
  const url = useRef<string | null>(null);
  const [index, setIndex] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState({ at: 0, of: 0 });

  // keyed on the clip, not on the items array: a refetched day hands over an equal array with a new
  // identity, and that must not restart what is playing
  const clipId = items[index]?.clip_id;
  useEffect(() => {
    let live = true;
    setError(null);
    setTime({ at: 0, of: 0 });
    if (!clipId) return;
    fetchAudioBlobUrl(clipId).then(
      (next) => {
        if (!live) { URL.revokeObjectURL(next); return; } // the clip changed while this was fetched
        const previous = url.current;
        url.current = next;
        const el = audio.current!;
        el.src = next;
        if (previous) URL.revokeObjectURL(previous);
        el.play().catch(() => setPlaying(false)); // a refused autoplay leaves Play for the person
      },
      (e) => {
        if (!live) return;
        audio.current?.pause();
        setPlaying(false);
        setError(audioErrorLine(e));
      },
    );
    return () => { live = false; };
  }, [clipId]);

  useEffect(() => () => {
    if (url.current) URL.revokeObjectURL(url.current);
    url.current = null;
  }, []);

  const item = items[index];
  const conv = conversations.find((c) => c.conversation_id === item?.conversation_id);

  function toggle() {
    const el = audio.current!;
    if (el.paused) el.play().catch(() => setPlaying(false));
    else el.pause();
  }

  function ended() {
    if (index < items.length - 1) setIndex(index + 1);
    else setPlaying(false);
  }

  return (
    <section class="player" aria-label="Player">
      <audio ref={audio} preload="auto"
        onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onEnded={ended}
        onTimeUpdate={(e) => {
          const el = e.currentTarget;
          setTime({ at: el.currentTime, of: Number.isFinite(el.duration) ? el.duration : 0 });
        }}
        onError={() => { if (url.current) { setPlaying(false); setError("This clip could not be played"); } }} />
      <div class="player-head">
        <h2 class="player-title">{conv ? span(conv) : ""}</h2>
        <span class="player-index">{`clip ${index + 1} of ${items.length}`}</span>
      </div>
      <div class="player-controls">
        <button type="button" class="btn" disabled={index === 0} onClick={() => setIndex(index - 1)}>Previous clip</button>
        <button type="button" class="btn" disabled={error !== null} onClick={toggle}>{playing ? "Pause" : "Play"}</button>
        <button type="button" class="btn" disabled={index >= items.length - 1} onClick={() => setIndex(index + 1)}>Next clip</button>
        <progress class="player-progress" max={time.of || 1} value={time.at} aria-label="Progress in this clip" />
        <span class="player-time">{`${clock(time.at)} / ${clock(time.of)}`}</span>
      </div>
      {error && <p class="player-error" role="alert">{error}</p>}
    </section>
  );
}
