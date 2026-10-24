import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/preact";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import type { ConversationView, DayView } from "../api";
import { AudioTab } from "./AudioTab";

const at = (h: number, m: number, s = 0) => new Date(2026, 9, 23, h, m, s).getTime();
const conv = (id: string, start: number, end: number, clips: string[], audio_available = true): ConversationView => ({
  conversation_id: id, start_ms: start, end_ms: end, speech_ms: end - start, star_ms: [], pinned: false, label: null,
  clip_ids: clips, lines: [], audio_available,
});
const view: DayView = {
  day: "2026-10-23", speech_ms: 0, noise_clips: 0, stars: [], audio_until: "2026-11-07", audio_kept_for_good: false,
  pending_pages: null,
  conversations: [
    conv("old", at(9, 0), at(9, 10), ["c_old"], false),
    conv("eve", at(17, 33), at(17, 40), ["c1", "c2"]),
    conv("test", at(22, 56, 0), at(22, 56, 16), ["c3"]),
  ],
};

const created: string[] = [];
const revoked: string[] = [];
let fetched: string[] = [];
let answer: (clip: string) => Response;

beforeEach(() => {
  created.length = 0;
  revoked.length = 0;
  fetched = [];
  answer = () => new Response(new Blob(["aac"]), { status: 200, headers: { "Content-Type": "audio/mp4" } });
  let n = 0;
  vi.stubGlobal("URL", Object.assign(URL, {
    createObjectURL: vi.fn(() => { const u = `blob:${++n}`; created.push(u); return u; }),
    revokeObjectURL: vi.fn((u: string) => { revoked.push(u); }),
  }));
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    const clip = decodeURIComponent(url.replace("/api/audio/", "").replace(".m4a", ""));
    fetched.push(clip);
    return answer(clip);
  }));
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

test("a row per conversation; the one whose audio is gone cannot be played; the day says how long audio is kept", () => {
  const { container } = render(<AudioTab view={view} />);
  expect(screen.getByText("Audio is kept until 7 November.")).toBeTruthy();
  const rows = [...container.querySelectorAll(".audio-row")];
  expect(rows.map((r) => r.querySelector("h2")!.textContent)).toEqual(["09:00 to 09:10", "17:33 to 17:40", "22:56"]);
  expect(rows[0].textContent).toContain("no longer kept");
  expect((rows[0].querySelector("button") as HTMLButtonElement).disabled).toBe(true);
  expect((rows[1].querySelector("button") as HTMLButtonElement).disabled).toBe(false);
  expect(rows[2].querySelector(".audio-dur")!.textContent).toBe("16 s speech");
  expect(container.querySelector("audio")).toBeNull();
  expect(fetched).toEqual([]);
});

test("Play day plays every kept clip in order, skips the gone conversation, and advances on ended", async () => {
  const { container } = render(<AudioTab view={view} />);
  fireEvent.click(screen.getByRole("button", { name: "Play day" }));
  await waitFor(() => expect(screen.getByText("clip 1 of 3")).toBeTruthy());
  expect(screen.getByText("Not in the playlist, its audio is no longer kept: 09:00 to 09:10.")).toBeTruthy();
  expect(container.querySelector(".player-title")!.textContent).toBe("17:33 to 17:40");
  const audio = container.querySelector("audio")!;
  await waitFor(() => expect(audio.getAttribute("src")).toBe("blob:1"));
  expect(screen.getByRole("button", { name: "Pause" })).toBeTruthy();

  act(() => { audio.dispatchEvent(new Event("ended")); });
  await waitFor(() => expect(screen.getByText("clip 2 of 3")).toBeTruthy());
  await waitFor(() => expect(audio.getAttribute("src")).toBe("blob:2"));
  expect(revoked).toEqual(["blob:1"]);

  fireEvent.click(screen.getByRole("button", { name: "Next clip" }));
  await waitFor(() => expect(container.querySelector(".player-title")!.textContent).toBe("22:56"));
  expect(screen.getByText("clip 3 of 3")).toBeTruthy();
  expect((screen.getByRole("button", { name: "Next clip" }) as HTMLButtonElement).disabled).toBe(true);
  expect(fetched).toEqual(["c1", "c2", "c3"]);
  await waitFor(() => expect(audio.getAttribute("src")).toBe("blob:3"));

  cleanup();
  expect(revoked).toEqual(["blob:1", "blob:2", "blob:3"]);
});

test("?conv= starts that conversation at once", async () => {
  render(<AudioTab view={view} conv="test" />);
  await waitFor(() => expect(screen.getByText("clip 1 of 1")).toBeTruthy());
  expect(fetched).toEqual(["c3"]);
});

test("a clip the app no longer keeps stops the player on it with the reason", async () => {
  answer = (clip) => clip === "c2"
    ? new Response(JSON.stringify({ error: "gone" }), { status: 410, headers: { "Content-Type": "application/json" } })
    : new Response(new Blob(["aac"]), { status: 200 });
  const { container } = render(<AudioTab view={view} conv="eve" />);
  const audio = await waitFor(() => {
    const a = container.querySelector("audio")!;
    expect(a.getAttribute("src")).toBe("blob:1");
    return a;
  });
  act(() => { audio.dispatchEvent(new Event("ended")); });
  expect((await screen.findByRole("alert")).textContent).toBe("This audio is no longer kept");
  expect(screen.getByText("clip 2 of 2")).toBeTruthy();
  expect(HTMLMediaElement.prototype.pause).toHaveBeenCalled();
  expect(fetched).toEqual(["c1", "c2"]);
});

test("a 500 says the audio could not be prepared, with the app's message", async () => {
  answer = () => new Response(JSON.stringify({ error: "ffmpeg failed" }), { status: 500 });
  render(<AudioTab view={view} conv="test" />);
  expect((await screen.findByRole("alert")).textContent).toBe("Could not prepare the audio: ffmpeg failed");
});

test("a day whose audio is gone says so and offers nothing to play", () => {
  const gone: DayView = { ...view, audio_until: null,
    conversations: view.conversations.map((c) => ({ ...c, audio_available: false })) };
  render(<AudioTab view={gone} />);
  expect(screen.getByText("The audio for this day is no longer kept.")).toBeTruthy();
  expect((screen.getByRole("button", { name: "Play day" }) as HTMLButtonElement).disabled).toBe(true);
});

test("a clip that arrives after the player moved on is revoked, never played", async () => {
  let release!: () => void;
  const gate = new Promise<void>((r) => { release = r; });
  answer = () => new Response(new Blob(["aac"]), { status: 200 });
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    fetched.push(url);
    await gate;
    return answer(url);
  }));
  render(<AudioTab view={view} conv="eve" />);
  cleanup(); // closed before the first clip arrived
  release();
  await waitFor(() => expect(revoked).toEqual(["blob:1"]));
  expect(created).toEqual(["blob:1"]);
  expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled();
});
