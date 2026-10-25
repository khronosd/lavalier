// What the window plays: one <audio> element for every page, fed clip by clip, and the state the
// mini-player draws. The Audio tab hands over a playlist; the player follows its clips until they end.

import { type ComponentChildren, createContext } from "preact";
import { useContext, useEffect, useRef, useState } from "preact/hooks";
import { type ConversationView, fetchAudioBlobUrl } from "./api";
import { audioErrorLine, type PlaylistItem } from "./playlist";

export const SPEEDS = [1, 1.5, 2] as const;
/** What the arrow keys move the position by. */
export const STEP_S = 5;

export interface PlaybackState {
  items: PlaylistItem[];
  conversations: ConversationView[];
  index: number;
  playing: boolean;
  time: { at: number; of: number };
  /** Why the clip under the player could not be played; the player stays on it. */
  error: string | null;
}

export interface Playback {
  state: PlaybackState | null;
  speed: number;
  /** Start a playlist afresh at its first clip, even the same one again. */
  play(items: PlaylistItem[], conversations: ConversationView[]): void;
  /** The same playlist as a refetch delivers it: the clip under the player reloads only if it changed. */
  update(items: PlaylistItem[], conversations: ConversationView[]): void;
  stop(): void;
  toggle(): void;
  previous(): void;
  next(): void;
  seek(seconds: number): void;
  cycleSpeed(): void;
}

const noop = () => undefined;

/** Outside the app (a page rendered on its own): nothing plays and nothing can. */
export const PlaybackContext = createContext<Playback>({
  state: null, speed: 1, play: noop, update: noop, stop: noop, toggle: noop, previous: noop, next: noop, seek: noop, cycleSpeed: noop,
});
export const usePlayback = () => useContext(PlaybackContext);

/** The window's one player. Each clip is fetched as a Blob URL (the API needs the token header, which an
 * audio src cannot carry); the previous URL is revoked when the next one starts, the last when the playlist
 * is stopped or the window closes. A clip that fails stops the player on it, with the reason. */
export function PlaybackProvider({ children }: { children: ComponentChildren }) {
  const audio = useRef<HTMLAudioElement>(null);
  const url = useRef<string | null>(null);
  const [state, setState] = useState<PlaybackState | null>(null);
  const [run, setRun] = useState(0);
  const [speed, setSpeed] = useState<number>(SPEEDS[0]);
  const speedRef = useRef(speed);
  speedRef.current = speed;

  const patch = (change: Partial<PlaybackState>) => setState((s) => s && { ...s, ...change });

  // keyed on the clip and the run, not on the items array: a refetched day hands over an equal array with a
  // new identity, and that must not restart what is playing; a new Play does, even of the same clip
  const clipId = state?.items[state.index]?.clip_id;
  useEffect(() => {
    if (!clipId) return;
    let live = true;
    patch({ error: null, time: { at: 0, of: 0 } });
    fetchAudioBlobUrl(clipId).then(
      (next) => {
        if (!live) { URL.revokeObjectURL(next); return; } // the clip changed, or the player stopped, while this was fetched
        const previous = url.current;
        url.current = next;
        const el = audio.current!;
        el.src = next;
        el.playbackRate = speedRef.current;
        if (previous) URL.revokeObjectURL(previous);
        el.play().catch(() => patch({ playing: false })); // a refused autoplay leaves Play for the person
      },
      (e) => {
        if (!live) return;
        audio.current?.pause();
        patch({ playing: false, error: audioErrorLine(e) });
      },
    );
    return () => { live = false; };
  }, [clipId, run]);

  useEffect(() => {
    if (audio.current) audio.current.playbackRate = speed;
  }, [speed]);

  useEffect(() => () => {
    if (url.current) URL.revokeObjectURL(url.current);
    url.current = null;
  }, []);

  const api: Playback = {
    state,
    speed,
    play(items, conversations) {
      if (items.length === 0) return;
      setState({ items, conversations, index: 0, playing: false, time: { at: 0, of: 0 }, error: null });
      setRun((n) => n + 1);
    },
    update(items, conversations) {
      setState((s) => s && items.length > 0 ? { ...s, items, conversations, index: Math.min(s.index, items.length - 1) } : s);
    },
    stop() {
      audio.current?.pause();
      if (url.current) URL.revokeObjectURL(url.current);
      url.current = null;
      setState(null);
    },
    toggle() {
      const el = audio.current;
      if (!el) return;
      if (el.paused) el.play().catch(() => patch({ playing: false }));
      else el.pause();
    },
    previous() {
      setState((s) => s && s.index > 0 ? { ...s, index: s.index - 1 } : s);
    },
    next() {
      setState((s) => s && s.index < s.items.length - 1 ? { ...s, index: s.index + 1 } : s);
    },
    seek(seconds) {
      const el = audio.current;
      if (el) el.currentTime = seconds;
    },
    cycleSpeed() {
      setSpeed((cur) => SPEEDS[(SPEEDS.indexOf(cur as (typeof SPEEDS)[number]) + 1) % SPEEDS.length]);
    },
  };

  function ended() {
    setState((s) => {
      if (!s) return s;
      return s.index < s.items.length - 1 ? { ...s, index: s.index + 1 } : { ...s, playing: false };
    });
  }

  return (
    <PlaybackContext.Provider value={api}>
      {state && (
        <audio ref={audio} preload="auto"
          onPlay={() => patch({ playing: true })} onPause={() => patch({ playing: false })} onEnded={ended}
          onLoadedMetadata={(e) => {
            const el = e.currentTarget;
            patch({ time: { at: el.currentTime, of: Number.isFinite(el.duration) ? el.duration : 0 } });
          }}
          onTimeUpdate={(e) => {
            const el = e.currentTarget;
            patch({ time: { at: el.currentTime, of: Number.isFinite(el.duration) ? el.duration : 0 } });
          }}
          onError={() => { if (url.current) patch({ playing: false, error: "This clip could not be played" }); }} />
      )}
      {children}
    </PlaybackContext.Provider>
  );
}
