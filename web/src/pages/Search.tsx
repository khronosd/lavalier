import { useEffect, useState } from "preact/hooks";
import { api, explainError, type Hit } from "../api";
import { Empty } from "../components/Empty";
import { Frame } from "../components/Frame";
import { dayTitle, hms } from "../format";
import { convStart, groupHits, jumpHref, renderSnippet } from "../search";

/** As many results as one page lists; the server's best matches first, then grouped by day here. */
export const SEARCH_LIMIT = 100;

type Load = { q: string; hits: Hit[] | null; error: string | null };

function HitRow({ hit }: { hit: Hit }) {
  const start = hit.conversation_id ? convStart(hit.conversation_id) : null;
  return (
    <a class="line hit" href={jumpHref(hit.day, `${hit.clip_id}-${hit.seq}`)}>
      <time class="time" dateTime={new Date(hit.at_ms).toISOString()}>{hms(hit.at_ms)}</time>
      <p>
        <span class="reading">{renderSnippet(hit.snippet)}</span>
        {hit.conversation_id && (
          <span class="hit-conv">{start ? `in the ${start} conversation` : "in a conversation"}</span>
        )}
      </p>
    </a>
  );
}

/** Search every day: the route's ?q=, results grouped by day with the matched words highlighted. */
export function Search({ q }: { q: string }) {
  const query = q.trim();
  const [load, setLoad] = useState<Load>({ q: query, hits: null, error: null });

  useEffect(() => {
    if (!query) return;
    let live = true;
    setLoad({ q: query, hits: null, error: null });
    api<Hit[]>("GET", `/api/search?q=${encodeURIComponent(query)}&limit=${SEARCH_LIMIT}`).then(
      (hits) => live && setLoad({ q: query, hits, error: null }),
      (e) => live && setLoad({ q: query, hits: null, error: explainError(e, "Search results") }),
    );
    return () => { live = false; };
  }, [query]);

  const hits = load.q === query ? load.hits : null;
  const error = load.q === query ? load.error : null;

  let body;
  if (!query) body = <Empty title="Type to search every day">Words from any transcript, in any day kept.</Empty>;
  else if (error) body = <p class="notice warn" role="alert">{error}</p>;
  else if (!hits) body = <p class="page-lead loading">Searching</p>;
  else if (hits.length === 0) body = <Empty title={`No matches for “${query}”`}>Try fewer or other words.</Empty>;
  else {
    body = (
      <>
        {hits.length >= SEARCH_LIMIT && <p class="page-lead">Showing the best {SEARCH_LIMIT} matches.</p>}
        {groupHits(hits).map((g) => (
          <section class="day-group" key={g.day} aria-labelledby={`g-${g.day}`}>
            <h2 class="group-title" id={`g-${g.day}`}>{dayTitle(g.day)}</h2>
            {g.hits.map((hit) => <HitRow key={`${hit.clip_id}-${hit.seq}`} hit={hit} />)}
          </section>
        ))}
      </>
    );
  }

  return (
    <Frame toolbar={{ search: "title" }}>
      <div class="page list-page">
        <h1 class="page-title">Search</h1>
        {body}
      </div>
    </Frame>
  );
}
