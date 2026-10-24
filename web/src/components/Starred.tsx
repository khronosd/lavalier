import type { ConversationView, StarView } from "../api";
import { hm, hms } from "../format";

interface Props {
  stars: StarView[];
  conversations: ConversationView[];
}

/** Bring a conversation into view without touching the hash (the hash is the route). */
function jump(e: MouseEvent, conversationId: string) {
  const target = document.getElementById(`c-${conversationId}`);
  if (!target) return;
  e.preventDefault();
  target.scrollIntoView?.({ block: "start" });
  target.focus({ preventScroll: true });
}

/** The day's starred moments, above the transcript, each linked to its conversation. */
export function Starred({ stars, conversations }: Props) {
  if (stars.length === 0) return null;
  const byId = new Map(conversations.map((c) => [c.conversation_id, c]));
  return (
    <section class="starred" aria-labelledby="starred-heading">
      <h2 class="section-title" id="starred-heading"><span class="glyph" aria-hidden="true">★</span> Starred</h2>
      {stars.map((s, i) => {
        const conv = s.conversation_id ? byId.get(s.conversation_id) : undefined;
        return (
          <div class="line" key={`${s.at_ms}-${i}`}>
            <time class="time" dateTime={new Date(s.at_ms).toISOString()}>{hms(s.at_ms)}</time>
            <p>
              {s.quote ? <span class="reading quote">{s.quote}</span> : <span class="no-quote">Nothing was said at this moment</span>}
              {conv && (
                <a class="star-link" href={`#c-${conv.conversation_id}`} onClick={(e) => jump(e, conv.conversation_id)}>
                  in the {hm(conv.start_ms)} conversation
                </a>
              )}
            </p>
          </div>
        );
      })}
    </section>
  );
}
