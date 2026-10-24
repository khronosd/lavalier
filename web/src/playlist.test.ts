import { expect, test } from "vitest";
import { ApiError, type ConversationView, type DayView } from "./api";
import { audioErrorLine, audioKeptLine, buildPlaylist } from "./playlist";

const conv = (id: string, clips: string[], audio_available = true): ConversationView => ({
  conversation_id: id, start_ms: 0, end_ms: 0, speech_ms: 0, star_ms: [], pinned: false, label: null,
  clip_ids: clips, lines: [], audio_available,
});
const view = (conversations: ConversationView[]): DayView => ({
  day: "2026-10-23", speech_ms: 0, conversations, stars: [], noise_clips: 0,
  audio_until: "2026-11-07", audio_kept_for_good: false, pending_pages: null,
});

const day = view([conv("a", ["a1", "a2"]), conv("gone", ["g1"], false), conv("b", ["b1"])]);

test("the day plays every available conversation's clips in order and lists the unavailable ones", () => {
  expect(buildPlaylist(day, "day")).toEqual({
    clips: [
      { clip_id: "a1", conversation_id: "a" },
      { clip_id: "a2", conversation_id: "a" },
      { clip_id: "b1", conversation_id: "b" },
    ],
    unavailable: ["gone"],
  });
});

test("one conversation plays only its own clips, in order", () => {
  expect(buildPlaylist(day, { conversation: "a" })).toEqual({
    clips: [{ clip_id: "a1", conversation_id: "a" }, { clip_id: "a2", conversation_id: "a" }],
    unavailable: [],
  });
});

test("a conversation whose audio is gone plays nothing and is listed as unavailable", () => {
  expect(buildPlaylist(day, { conversation: "gone" })).toEqual({ clips: [], unavailable: ["gone"] });
});

test("an unknown conversation plays nothing", () => {
  expect(buildPlaylist(day, { conversation: "nope" })).toEqual({ clips: [], unavailable: [] });
});

test("an empty day is an empty playlist", () => {
  expect(buildPlaylist(view([]), "day")).toEqual({ clips: [], unavailable: [] });
});

test("a clip that cannot be fetched says why", () => {
  expect(audioErrorLine(new ApiError(410, "gone"))).toBe("This audio is no longer kept");
  expect(audioErrorLine(new ApiError(404, "unknown clip"))).toBe("This clip is unknown");
  expect(audioErrorLine(new ApiError(500, "ffmpeg failed"))).toBe("Could not prepare the audio: ffmpeg failed");
  expect(audioErrorLine(new TypeError("Failed to fetch"))).toBe("Could not prepare the audio: Failed to fetch");
});

test("the day says how long its audio is kept", () => {
  expect(audioKeptLine(day)).toBe("Audio is kept until 7 November.");
  expect(audioKeptLine({ ...day, audio_until: null, audio_kept_for_good: true })).toBe("Audio is kept for good.");
  expect(audioKeptLine({ ...day, audio_until: null })).toBe("The audio for this day is no longer kept.");
  // with both, the date comes first, as in the day's summary: it is when the unprotected audio goes
  expect(audioKeptLine({ ...day, audio_kept_for_good: true })).toBe("Audio is kept until 7 November.");
});
