// Shared fixtures for the Insights tests: the server's JSON as Task 8's routes send it.
import type { ConversationView, DayView, InsightDayState, InsightRecord, Job, ProviderFacts } from "./api";

export const at = (h: number, m: number, s = 0) => new Date(2026, 9, 23, h, m, s).getTime();

export const conv = (id: string, lines: ConversationView["lines"]): ConversationView => ({
  conversation_id: id, start_ms: at(22, 56), end_ms: at(22, 57), speech_ms: 16_000, star_ms: [], pinned: false,
  label: null, clip_ids: ["clip_b"], lines, audio_available: true,
});

export const view: DayView = {
  day: "2026-10-23", speech_ms: 16_000, noise_clips: 0, stars: [], audio_until: null, audio_kept_for_good: false,
  pending_pages: null,
  conversations: [conv("conv_test", [{ at_ms: at(22, 56, 9), text: "test one two three", clip_id: "clip_b", seq: 0 }])],
};

export const silentView: DayView = { ...view, conversations: [conv("conv_quiet", [])] };

export const ollama: ProviderFacts = {
  provider: "ollama", model: "qwen3:8b", auto: true, base_url: "", key_present: null, keychain_error: null,
  facts: { sends: "each day's transcript text and your questions", to: "Ollama on this Mac; nothing leaves the machine", cost: "free" },
  models: [], sentence: "Sends each day's transcript text to Ollama on this Mac once the day is complete.",
  display: "Ollama on this Mac", check: null,
};

export const anthropic: ProviderFacts = {
  ...ollama, provider: "anthropic", model: "claude-haiku", key_present: true, display: "Anthropic",
  sentence: "Sends each day's transcript text to Anthropic once the day is complete.",
};

export const noProvider: ProviderFacts = { ...ollama, provider: "", model: "", display: "", sentence: "", facts: null };

export const doneRecord: InsightRecord = {
  day: "2026-10-23", state: "done", provider: "ollama", model: "qwen3:8b", prompt_version: 1,
  generated_ms: at(23, 5, 30), input_chars: 1200, error: null, truncated: false,
  insight: {
    summary: "A short pendant test late in the evening.",
    follow_ups: [
      { text: "Check the mute survives a reboot", at_ms: at(22, 56, 9), line_id: "clip_b-0" },
      { text: "Plug the pendant in before the sync", at_ms: at(23, 4), line_id: null },
    ],
    people: ["Ana", "Ben"],
    topics: ["pendant firmware", "bluetooth"],
  },
};

export const errorRecord: InsightRecord = {
  ...doneRecord, state: "error", insight: null, error: "Ollama did not answer. Start it and try again.",
};

export const dayState = (over: Partial<InsightDayState> = {}): InsightDayState => ({
  state: "none", record: null, reason: null, job: null, ...over,
});

export const job = (over: Partial<Job> = {}): Job => ({
  id: "j1", kind: "generate", key: "day:2026-10-23", state: "running", result: null, error: null,
  started_ms: 1, finished_ms: null, ...over,
});
