import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/preact";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { ConversationView } from "../api";
import { PlaybackProvider, usePlayback } from "../playback";
import type { PlaylistItem } from "../playlist";
import { MiniPlayer } from "./MiniPlayer";

const at = (h: number, m: number) => new Date(2026, 9, 23, h, m).getTime();
const conv: ConversationView = {
  conversation_id: "conv_a", start_ms: at(9, 12), end_ms: at(9, 41), speech_ms: 20 * 60_000, star_ms: [], pinned: false,
  label: "Firmware standup", clip_ids: ["c1", "c2"], lines: [], audio_available: true,
};
const items: PlaylistItem[] = [{ clip_id: "c1", conversation_id: "conv_a" }, { clip_id: "c2", conversation_id: "conv_a" }];

/** A page with something to play, and the player as the frame mounts it. */
function Harness() {
  const playback = usePlayback();
  return (
    <>
      <button type="button" onClick={() => playback.play(items, [conv])}>Go</button>
      <MiniPlayer />
    </>
  );
}

const revoked: string[] = [];
beforeEach(() => {
  revoked.length = 0;
  let n = 0;
  vi.stubGlobal("URL", Object.assign(URL, {
    createObjectURL: vi.fn(() => `blob:${++n}`), revokeObjectURL: vi.fn((u: string) => { revoked.push(u); }),
  }));
  vi.stubGlobal("fetch", vi.fn(async () => new Response(new Blob(["aac"]), { status: 200 })));
  vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(function (this: HTMLMediaElement) {
    this.dispatchEvent(new Event("play"));
    return Promise.resolve();
  });
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(function (this: HTMLMediaElement) {
    this.dispatchEvent(new Event("pause"));
  });
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

async function start() {
  render(<PlaybackProvider><Harness /></PlaybackProvider>);
  fireEvent.click(screen.getByText("Go"));
  const player = await screen.findByRole("region", { name: "Player" });
  const audio = await waitFor(() => {
    const a = document.querySelector("audio")!;
    expect(a.getAttribute("src")).toBe("blob:1");
    return a;
  });
  return { player, audio };
}

test("nothing shows until something plays; then the title, the clip, Pause, the scrubber, the time and the speed", async () => {
  render(<PlaybackProvider><Harness /></PlaybackProvider>);
  expect(screen.queryByRole("region", { name: "Player" })).toBeNull();
  expect(document.querySelector("audio")).toBeNull();
  fireEvent.click(screen.getByText("Go"));
  const player = await screen.findByRole("region", { name: "Player" });
  expect(player.querySelector(".mini-name")!.textContent).toBe("Firmware standup");
  expect(player.querySelector(".mini-sub")!.textContent).toBe("09:12 · clip 1 of 2");
  await waitFor(() => expect(screen.getByRole("button", { name: "Pause" })).toBeTruthy());
  expect(screen.getByRole("slider", { name: "Position in this clip" })).toBeTruthy();
  expect(player.querySelectorAll(".mini-bar")).toHaveLength(30);
  expect(screen.getByText("0:00 / 0:00")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Playback speed, 1x" }).textContent).toBe("1×");
  expect(screen.queryByRole("alert")).toBeNull();
});

test("the scrubber fills as the clip plays; a click on it and the arrow keys seek", async () => {
  const { audio } = await start();
  Object.defineProperty(audio, "currentTime", { configurable: true, writable: true, value: 7 });
  Object.defineProperty(audio, "duration", { configurable: true, value: 30 });
  act(() => { audio.dispatchEvent(new Event("timeupdate")); });
  expect(screen.getByText("0:07 / 0:30")).toBeTruthy();
  expect(document.querySelectorAll(".mini-bar.played")).toHaveLength(7);
  const slider = screen.getByRole("slider", { name: "Position in this clip" });
  expect(slider.getAttribute("aria-valuenow")).toBe("7");
  expect(slider.getAttribute("aria-valuemax")).toBe("30");
  slider.getBoundingClientRect = () => ({ left: 100, width: 300, top: 0, height: 28, right: 400, bottom: 28, x: 100, y: 0, toJSON: () => undefined });
  fireEvent.click(slider, { clientX: 250 });
  expect(audio.currentTime).toBe(15);
  fireEvent.keyDown(slider, { key: "ArrowRight" });
  expect(audio.currentTime).toBe(12); // five seconds on from the last position the element reported
  fireEvent.keyDown(slider, { key: "ArrowLeft" });
  expect(audio.currentTime).toBe(2);
});

test("the speed button cycles 1, 1.5 and 2 and sets the element's rate", async () => {
  const { audio } = await start();
  expect(audio.playbackRate).toBe(1);
  fireEvent.click(screen.getByRole("button", { name: "Playback speed, 1x" }));
  expect(screen.getByRole("button", { name: "Playback speed, 1.5x" }).textContent).toBe("1.5×");
  expect(audio.playbackRate).toBe(1.5);
  fireEvent.click(screen.getByRole("button", { name: "Playback speed, 1.5x" }));
  expect(audio.playbackRate).toBe(2);
  fireEvent.click(screen.getByRole("button", { name: "Playback speed, 2x" }));
  expect(audio.playbackRate).toBe(1);
});

test("Stop playing removes the player and lets the clip's URL go", async () => {
  await start();
  fireEvent.click(screen.getByRole("button", { name: "Stop playing" }));
  expect(screen.queryByRole("region", { name: "Player" })).toBeNull();
  expect(document.querySelector("audio")).toBeNull();
  expect(revoked).toEqual(["blob:1"]);
  expect(HTMLMediaElement.prototype.pause).toHaveBeenCalled();
});

test("playing the same playlist again starts it afresh", async () => {
  const { audio } = await start();
  const plays = vi.mocked(HTMLMediaElement.prototype.play).mock.calls.length;
  fireEvent.click(screen.getByText("Go"));
  await waitFor(() => expect(audio.getAttribute("src")).toBe("blob:2"));
  expect(revoked).toEqual(["blob:1"]);
  expect(vi.mocked(HTMLMediaElement.prototype.play).mock.calls.length).toBe(plays + 1);
});
