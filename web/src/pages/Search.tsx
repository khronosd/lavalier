import { useEffect, useState } from "preact/hooks";
import { api, explainError, type Hit } from "../api";
import { Conversation } from "../components/Conversation";
import { Empty } from "../components/Empty";
import { Frame } from "../components/Frame";
import { ChevronLeftIcon, ChevronRightIcon, ClockIcon } from "../components/icons";
import { useDayView } from "../dayCache";
import { dayTitle, hms } from "../format";
import { navigate, toHash } from "../router";
import { convStart, groupHits, hitId, jumpHref, recentSearches, rememberSearch, renderSnippet } from "../search";

/** As many results as one page lists; the server's best matches first, then grouped by day here. */
export const SEARCH_LIMIT = 100;

type Load = { q: string; hits: Hit[] | null; error: string | null };

const searchHref = (q: string, hit?: string) => toHash({ name: "search", params: {}, query: hit ? { q, hit } : { q } });
const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

function HitRow({ hit, selected, q }: { hit: Hit; selected: boolean; q: string }) {
  const start = hit.conversation_id ? convStart(hit.conversation_id) : null;
  return (
    <a class={selected ? "row hit selected" : "row hit"} href={searchHref(q, hitId(hit))} aria-current={selected ? "true" : undefined}>
      <span class="row-top">
        <time class="row-time" dateTime={new Date(hit.at_ms).toISOString()}>{hms(hit.at_ms)}</time>
        {hit.conversation_id && (
          <span class="hit-conv">{start ? `in the ${start} conversation` : "in a conversation"}</span>
        )}
      </span>
      <p class="row-quote reading">{renderSnippet(hit.snippet)}</p>
    </a>
  );
}

/** The content column for the selected hit: the day, this match's place among all, Open day, then the hit's
 * conversation with the words marked and the hit line tinted. */
function HitView({ hit, q, ordered }: { hit: Hit; q: string; ordered: Hit[] }) {
  const day = useDayView(hit.day);
  const at = ordered.indexOf(hit);
  const previous = ordered[at - 1];
  const next = ordered[at + 1];
  const lineId = hitId(hit);
  const conv = day.view?.conversations.find((c) => c.conversation_id === hit.conversation_id) ?? null;

  // the hit line into view once its day shows
  useEffect(() => {
    if (day.view) document.getElementById(lineId)?.scrollIntoView?.({ block: "center" });
  }, [lineId, day.view]);

  async function pin(id: string, pinned: boolean) {
    await api<unknown>("POST", `/api/${pinned ? "pin" : "unpin"}/${encodeURIComponent(id)}`);
    if (day.view) {
      day.update({ ...day.view, conversations: day.view.conversations.map((c) => c.conversation_id === id ? { ...c, pinned } : c) });
    }
  }

  let body;
  if (day.error) body = <p class="notice warn" role="alert">{day.error}</p>;
  else if (!day.view) body = <p class="page-lead loading">Loading…</p>;
  else if (!conv) body = <Empty title="This line is not in a conversation">Open the day to read it in place.</Empty>;
  else {
    body = (
      <Conversation key={conv.conversation_id} conv={conv} mark={q} hitLine={lineId} onPin={(p) => pin(conv.conversation_id, p)}
        onPlay={() => navigate(toHash({ name: "day", params: { date: hit.day }, query: { tab: "audio", conv: conv.conversation_id } }))} />
    );
  }
  return (
    <>
      <div class="hit-bar">
        <span class="hit-day">{dayTitle(hit.day)}</span>
        <nav class="segmented hit-nav" aria-label="Matches">
          {previous
            ? <a class="segment step" href={searchHref(q, hitId(previous))} aria-label="Previous match"><ChevronLeftIcon /></a>
            : <span class="segment step" aria-disabled="true" aria-label="Previous match"><ChevronLeftIcon /></span>}
          <span class="segment hit-count">{`${at + 1} of ${ordered.length}`}</span>
          {next
            ? <a class="segment step" href={searchHref(q, hitId(next))} aria-label="Next match"><ChevronRightIcon /></a>
            : <span class="segment step" aria-disabled="true" aria-label="Next match"><ChevronRightIcon /></span>}
        </nav>
        <a class="btn soft" href={jumpHref(hit.day, lineId)}>Open day</a>
      </div>
      {body}
    </>
  );
}

/** Search every day: the route's ?q=, the hits grouped by day in the list column, the selected hit's
 * conversation in the content column with the words marked, and the search's facts in the inspector. */
export function Search({ q, hit }: { q: string; hit?: string }) {
  const query = q.trim();
  const [load, setLoad] = useState<Load>({ q: query, hits: null, error: null });

  useEffect(() => {
    if (!query) return;
    let live = true;
    setLoad({ q: query, hits: null, error: null });
    api<Hit[]>("GET", `/api/search?q=${encodeURIComponent(query)}&limit=${SEARCH_LIMIT}`).then(
      (hits) => {
        if (!live) return;
        rememberSearch(query);
        setLoad({ q: query, hits, error: null });
      },
      (e) => live && setLoad({ q: query, hits: null, error: explainError(e, "Search results") }),
    );
    return () => { live = false; };
  }, [query]);

  const hits = load.q === query ? load.hits : null;
  const error = load.q === query ? load.error : null;
  const groups = hits ? groupHits(hits) : [];
  const ordered = groups.flatMap((g) => g.hits);
  const selected = ordered.find((h) => hitId(h) === hit) ?? ordered[0] ?? null;
  const recents = recentSearches().filter((r) => r !== query);

  const list = groups.length > 0
    ? groups.map((g) => (
      <div class="list-group" key={g.day}>
        <h2 class="hd list-head"><span class="hd-day">{dayTitle(g.day)}</span><span class="hd-count">{g.hits.length}</span></h2>
        {g.hits.map((h) => <HitRow key={hitId(h)} hit={h} selected={h === selected} q={query} />)}
      </div>
    ))
    : <p class="hd">Matches</p>;

  let content;
  if (!query) content = <Empty title="Type to search every day">Words from any transcript, in any day kept.</Empty>;
  else if (error) content = <p class="notice warn" role="alert">{error}</p>;
  else if (!hits) content = <p class="page-lead loading">Searching</p>;
  else if (hits.length === 0) content = <Empty title={`No matches for “${query}”`}>Try fewer or other words.</Empty>;
  else if (selected) content = <HitView key={hitId(selected)} hit={selected} q={query} ordered={ordered} />;

  const inspector = (hits && hits.length > 0) || recents.length > 0 ? (
    <>
      {hits && hits.length > 0 && (
        <div class="insp-block">
          <p class="insp-big">{plural(hits.length, "match", "matches")}</p>
          <p class="insp-sub">
            {`in ${plural(groups.length, "day", "days")}, ${hits.length >= SEARCH_LIMIT ? `the best ${SEARCH_LIMIT} shown` : "every day searched"}`}
          </p>
        </div>
      )}
      {groups.length > 0 && (
        <div class="insp-block">
          <p class="hd">Where it comes up</p>
          {groups.map((g) => (
            <a class="insp-row" key={g.day} href={searchHref(query, hitId(g.hits[0]))}>
              <span>{dayTitle(g.day)}</span><span class="insp-count">{g.hits.length}</span>
            </a>
          ))}
        </div>
      )}
      {recents.length > 0 && (
        <div class="insp-block">
          <p class="hd">Recent searches</p>
          {recents.map((r) => <a class="insp-row" key={r} href={searchHref(r)}><ClockIcon /><span>{r}</span></a>)}
        </div>
      )}
    </>
  ) : null;

  return (
    <Frame toolbar={{ search: "title" }} list={list} listLabel="Matches" inspector={inspector} inspectorLabel="About this search">
      <div class="page search-page">{content}</div>
    </Frame>
  );
}
