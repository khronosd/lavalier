import type { ConversationView, StarView } from "../api";
import { hm, hms, noQuote } from "../format";
import { type Route, toHash } from "../router";

interface Props {
  stars: StarView[];
  conversations: ConversationView[];
  /** The today or day route being shown; each link is that route with ?at= naming the conversation. */
  route: Route;
}

/** The day's starred moments, above the transcript, each linked to its conversation. */
export function Starred({ stars, conversations, route }: Props) {
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
              {s.quote ? <span class="reading quote">{s.quote}</span> : <span class="no-quote">{noQuote(s)}</span>}
              {conv && (
                <a class="star-link" href={toHash({ ...route, query: { at: `c-${conv.conversation_id}` } })}>
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
