// What the Audio tab plays: the clips of one conversation or of the whole day, in time order.

import { ApiError, type DayView } from "./api";
import { dayMonth } from "./format";

export type Scope = { conversation: string } | "day";

export interface PlaylistItem {
  clip_id: string;
  conversation_id: string;
}

export interface Playlist {
  clips: PlaylistItem[];
  /** Conversations in scope whose audio is no longer kept; they are left out of clips. */
  unavailable: string[];
}

/** The chosen conversation(s) in the day's order, each one's clips in order. */
export function buildPlaylist(view: DayView, scope: Scope): Playlist {
  const chosen = scope === "day"
    ? view.conversations
    : view.conversations.filter((c) => c.conversation_id === scope.conversation);
  const clips: PlaylistItem[] = [];
  const unavailable: string[] = [];
  for (const c of chosen) {
    if (!c.audio_available) {
      unavailable.push(c.conversation_id);
      continue;
    }
    for (const clip_id of c.clip_ids) clips.push({ clip_id, conversation_id: c.conversation_id });
  }
  return { clips, unavailable };
}

/** Why a clip's audio could not be fetched, in the words the player shows. */
export function audioErrorLine(e: unknown): string {
  if (e instanceof ApiError && e.status === 410) return "This audio is no longer kept";
  if (e instanceof ApiError && e.status === 404) return "This clip is unknown";
  return `Could not prepare the audio: ${e instanceof Error ? e.message : String(e)}`;
}

/** How long the day's audio is kept; the date first, as in the day's summary. */
export function audioKeptLine(view: DayView): string {
  if (view.audio_until) return `Audio is kept until ${dayMonth(view.audio_until)}.`;
  if (view.audio_kept_for_good) return "Audio is kept for good.";
  return "The audio for this day is no longer kept.";
}
