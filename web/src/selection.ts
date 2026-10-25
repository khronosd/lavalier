// Which conversation the day view shows: the one the route names (?conv=, or the one ?at= points into),
// else the one the page remembers from before ?at= was dropped, else the first.

import type { DayView } from "./api";
import type { Route } from "./router";

const has = (view: DayView, id: string | null | undefined): id is string =>
  !!id && view.conversations.some((c) => c.conversation_id === id);

/** The conversation `?at=` points into: "c-<id>" names it, "<clip_id>-<seq>" a line of it; null otherwise. */
export function conversationOfTarget(view: DayView, at: string | undefined): string | null {
  if (!at) return null;
  if (at.startsWith("c-") && has(view, at.slice(2))) return at.slice(2);
  for (const c of view.conversations) {
    if (c.lines.some((l) => `${l.clip_id}-${l.seq}` === at)) return c.conversation_id;
  }
  return null;
}

/** The conversation the route names: ?conv= first, then the one ?at= points into; null when neither does. */
export function namedConversation(view: DayView, route: Route): string | null {
  if (has(view, route.query.conv)) return route.query.conv;
  return conversationOfTarget(view, route.query.at);
}

/** The selected conversation: the named one, else the remembered one, else the first; null with none. */
export function selectedConversation(view: DayView, named: string | null, remembered: string | null): string | null {
  if (has(view, named)) return named;
  if (has(view, remembered)) return remembered;
  return view.conversations[0]?.conversation_id ?? null;
}
