import { expect, test } from "vitest";
import type { ConversationView, DayView } from "./api";
import { parseHash } from "./router";
import { conversationOfTarget, namedConversation, selectedConversation } from "./selection";

const conv = (id: string, clip: string): ConversationView => ({
  conversation_id: id, start_ms: 0, end_ms: 1, speech_ms: 1, star_ms: [], pinned: false, label: null, clip_ids: [clip],
  lines: [{ at_ms: 0, text: "x", clip_id: clip, seq: 0 }, { at_ms: 1, text: "y", clip_id: clip, seq: 1 }], audio_available: true,
});
const view: DayView = {
  day: "2026-10-23", speech_ms: 2, conversations: [conv("c-20261023-080500", "clip_a"), conv("c-20261023-091200", "clip_b")],
  stars: [], noise_clips: 0, audio_until: null, audio_kept_for_good: false, pending_pages: null,
};

test("conversationOfTarget reads a conversation id or a line id, and knows nothing else", () => {
  expect(conversationOfTarget(view, "c-c-20261023-091200")).toBe("c-20261023-091200");
  expect(conversationOfTarget(view, "clip_b-1")).toBe("c-20261023-091200");
  expect(conversationOfTarget(view, "clip_a-0")).toBe("c-20261023-080500");
  expect(conversationOfTarget(view, "clip_zzz-0")).toBeNull();
  expect(conversationOfTarget(view, "c-c-20261023-000000")).toBeNull();
  expect(conversationOfTarget(view, undefined)).toBeNull();
});

test("namedConversation prefers ?conv=, then the conversation ?at= points into", () => {
  expect(namedConversation(view, parseHash("#/day/2026-10-23?conv=c-20261023-080500&at=clip_b-1"))).toBe("c-20261023-080500");
  expect(namedConversation(view, parseHash("#/day/2026-10-23?conv=nope&at=clip_b-1"))).toBe("c-20261023-091200");
  expect(namedConversation(view, parseHash("#/day/2026-10-23"))).toBeNull();
});

test("selectedConversation falls back from the named one to the remembered one to the first", () => {
  expect(selectedConversation(view, "c-20261023-091200", null)).toBe("c-20261023-091200");
  expect(selectedConversation(view, null, "c-20261023-091200")).toBe("c-20261023-091200");
  expect(selectedConversation(view, null, "gone")).toBe("c-20261023-080500");
  expect(selectedConversation(view, null, null)).toBe("c-20261023-080500");
  expect(selectedConversation({ ...view, conversations: [] }, null, null)).toBeNull();
});
