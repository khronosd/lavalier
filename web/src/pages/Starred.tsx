import { useEffect, useState } from "preact/hooks";
import { api, explainError, type StarredEntry } from "../api";
import { Empty } from "../components/Empty";
import { dayTitle, hms } from "../format";
import { convStart, groupByDay, jumpHref } from "../search";

function StarRow({ entry }: { entry: StarredEntry }) {
  const { day, star } = entry;
  const start = star.conversation_id ? convStart(star.conversation_id) : null;
  return (
    <div class="line star-row">
      <time class="time" dateTime={new Date(star.at_ms).toISOString()}>{hms(star.at_ms)}</time>
      <p>
        {star.quote
          ? <span class="reading quote">{star.quote}</span>
          : <span class="no-quote">Nothing was said at this moment</span>}
        {star.conversation_id
          ? <a class="star-link" href={jumpHref(day, `c-${star.conversation_id}`)}>
              {start ? `in the ${start} conversation` : "in its conversation"}
            </a>
          : <a class="star-link" href={jumpHref(day)}>{`Open ${dayTitle(day)}`}</a>}
      </p>
    </div>
  );
}

/** Every starred moment of every day, newest first, each with its quote and a way to the moment. */
export function StarredPage() {
  const [entries, setEntries] = useState<StarredEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api<StarredEntry[]>("GET", "/api/starred").then(
      (list) => live && setEntries(list),
      (e) => live && setError(explainError(e, "The starred moments")),
    );
    return () => { live = false; };
  }, []);

  let body;
  if (error) body = <p class="notice warn" role="alert">{error}</p>;
  else if (!entries) body = <p class="page-lead loading">Loading starred moments</p>;
  else if (entries.length === 0) {
    body = <Empty title="No starred moments yet">Press the pendant's button once to star the moment.</Empty>;
  } else {
    const newestFirst = [...entries].sort((a, b) => b.star.at_ms - a.star.at_ms);
    body = groupByDay(newestFirst).map((g) => (
      <section class="day-group" key={g.day} aria-labelledby={`s-${g.day}`}>
        <h2 class="group-title" id={`s-${g.day}`}>{dayTitle(g.day)}</h2>
        {g.items.map((entry, i) => <StarRow key={`${entry.star.at_ms}-${i}`} entry={entry} />)}
      </section>
    ));
  }

  return (
    <div class="page list-page">
      <h1 class="page-title">Starred</h1>
      {body}
    </div>
  );
}
