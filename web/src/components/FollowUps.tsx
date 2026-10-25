import type { FollowUp } from "../api";
import { hms } from "../format";
import { followUpHref } from "../insights";

function When({ day, fu }: { day: string; fu: FollowUp }) {
  if (fu.at_ms === null) return <span class="time" />;
  const iso = new Date(fu.at_ms).toISOString();
  const href = followUpHref(day, fu);
  return href
    ? <a class="time fu-jump" href={href} title="Show this moment in the transcript">{hms(fu.at_ms)}</a>
    : <time class="time" dateTime={iso}>{hms(fu.at_ms)}</time>;
}

/** One follow-up on the margin grid: the time links to the line it points at, when there is one. */
export function FollowUpLine({ day, fu }: { day: string; fu: FollowUp }) {
  return (
    <div class="line">
      <When day={day} fu={fu} />
      <p>{fu.text}</p>
    </div>
  );
}

/** The day's follow-ups on the margin grid. */
export function FollowUps({ day, items }: { day: string; items: FollowUp[] }) {
  return (
    <section class="ins-block follow-ups">
      <h2 class="section-title">Follow-ups</h2>
      {items.map((fu, i) => <FollowUpLine key={i} day={day} fu={fu} />)}
    </section>
  );
}
