import { useRef } from "preact/hooks";
import { clock, hm } from "../format";
import { STEP_S, usePlayback } from "../playback";
import { useWidth } from "../useWidth";
import { seedOf, waveBars } from "../wave";
import { span } from "./Conversation";
import { ChevronLeftIcon, ChevronRightIcon, CloseIcon, PauseIcon, PlayIcon } from "./icons";

/** Bars 3px wide, 2px apart, until clips carry loudness; an unmeasured scrubber draws thirty. */
const BAR_PITCH_PX = 5;

/** The floating player at the bottom of the content column, on every page, while something is playing:
 * play or pause, previous and next clip, the title (the conversation's label, else its range) over the
 * clip's place in the playlist or the reason it failed, a scrubber of bars that fills as the clip plays,
 * elapsed and total, the speed, and Stop. It follows the clip the window is playing; the Audio tab keeps
 * the full playlist. */
export function MiniPlayer() {
  const playback = usePlayback();
  const scrub = useRef<HTMLDivElement>(null);
  const width = useWidth(scrub, playback.state !== null);
  if (!playback.state) return null;
  const { items, conversations, index, playing, time, error } = playback.state;
  const item = items[index];
  const conv = conversations.find((c) => c.conversation_id === item?.conversation_id);
  const name = conv ? conv.label ?? span(conv) : "";
  const n = width > 0 ? Math.max(1, Math.floor(width / BAR_PITCH_PX)) : 30;
  const bars = waveBars(seedOf(item?.clip_id ?? ""), n, 4, 24);
  const played = time.of > 0 ? Math.round((time.at / time.of) * n) : 0;

  function seekTo(e: MouseEvent) {
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    if (rect.width > 0 && time.of > 0) playback.seek(((e.clientX - rect.left) / rect.width) * time.of);
  }
  function nudge(e: KeyboardEvent) {
    if (e.key === "ArrowRight") playback.seek(Math.min(time.of, time.at + STEP_S));
    else if (e.key === "ArrowLeft") playback.seek(Math.max(0, time.at - STEP_S));
    else return;
    e.preventDefault();
  }

  return (
    <div class="mini" role="region" aria-label="Player">
      <button type="button" class="mini-play" aria-label={playing ? "Pause" : "Play"} disabled={error !== null}
        onClick={playback.toggle}>{playing ? <PauseIcon /> : <PlayIcon />}</button>
      <button type="button" class="tb mini-step" aria-label="Previous clip" disabled={index === 0} onClick={playback.previous}>
        <ChevronLeftIcon />
      </button>
      <button type="button" class="tb mini-step" aria-label="Next clip" disabled={index >= items.length - 1} onClick={playback.next}>
        <ChevronRightIcon />
      </button>
      <div class={error ? "mini-title warn" : "mini-title"}>
        <span class="mini-name">{name}</span>
        <span class="mini-sub">
          {conv && <span>{`${hm(conv.start_ms)} · `}</span>}
          <span class="mini-clip">{`clip ${index + 1} of ${items.length}`}</span>
          {error && <>{" · "}<span class="mini-error" role="alert">{error}</span></>}
        </span>
      </div>
      <div class="mini-scrub" ref={scrub} role="slider" aria-label="Position in this clip" tabIndex={0}
        aria-valuemin={0} aria-valuemax={Math.round(time.of)} aria-valuenow={Math.round(time.at)}
        onClick={seekTo} onKeyDown={nudge}>
        {bars.map((h, i) => <span key={i} class={i < played ? "mini-bar played" : "mini-bar"} style={{ "--h": `${h}px` }} />)}
      </div>
      <span class="mini-time">{`${clock(time.at)} / ${clock(time.of)}`}</span>
      <button type="button" class="tb mini-speed" aria-label={`Playback speed, ${playback.speed}x`}
        onClick={playback.cycleSpeed}>{`${playback.speed}×`}</button>
      <button type="button" class="tb mini-close" aria-label="Stop playing" onClick={playback.stop}><CloseIcon /></button>
    </div>
  );
}
