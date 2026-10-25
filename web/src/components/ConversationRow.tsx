import type { ConversationView } from "../api";
import { duration } from "../format";
import { seedOf, waveBars } from "../wave";
import { span } from "./Conversation";
import { PinIcon, StarFillIcon } from "./icons";

interface Props {
  conv: ConversationView;
  selected: boolean;
  href: string;
}

/** Fourteen 2px bars, 2px apart, 3 to 16px tall: decorative, from the conversation's id until clips carry loudness. */
function Wave({ seed }: { seed: number }) {
  return (
    <svg class="wave" viewBox="0 0 54 16" width="54" height="16" aria-hidden="true">
      {waveBars(seed).map((h, i) => <rect key={i} x={i * 4} y={16 - h} width="2" height={h} rx="1" />)}
    </svg>
  );
}

/** A conversation in the list column: its title (the calendar label, else the time range) with the range
 * beside a label, the first line as a one-line snippet next to a small waveform, then the speech total,
 * the star count and a pin when kept. */
export function ConversationRow({ conv, selected, href }: Props) {
  const range = span(conv);
  const first = [...conv.lines].sort((a, b) => a.at_ms - b.at_ms || a.seq - b.seq)[0];
  const stars = conv.star_ms.length;
  return (
    <a class={selected ? "row selected" : "row"} href={href} aria-current={selected ? "true" : undefined}>
      <span class="row-top">
        <span class="row-title">{conv.label ?? range}</span>
        {conv.label && <span class="row-time">{range}</span>}
      </span>
      <span class="row-mid">
        <span class="row-snippet">{first?.text ?? ""}</span>
        <Wave seed={seedOf(conv.conversation_id)} />
      </span>
      <span class="row-foot">
        <span class="row-len">{duration(conv.speech_ms)}</span>
        {stars > 0 && <span class="row-stars" aria-label={`${stars} starred`}><StarFillIcon />{stars}</span>}
        {conv.pinned && <span class="row-pinned" title="Pinned"><PinIcon /></span>}
      </span>
    </a>
  );
}
