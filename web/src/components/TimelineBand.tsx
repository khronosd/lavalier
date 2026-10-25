import { useRef } from "preact/hooks";
import type { DayView } from "../api";
import { type Route, toHash } from "../router";
import { blocks, hourTicks, starDots, timelineRange } from "../timeline";
import { useWidth } from "../useWidth";

interface Props {
  view: DayView;
  selected: string | null;
  /** The route being shown; a block links to it with ?at= naming the conversation (a jump), the tab kept. */
  route: Route;
}

const at = (left: number) => `${left}%`;

/** One day as a horizontal axis: hour lines and labels, a block per conversation (a link that jumps to it),
 * its label above it unless that would crowd the last one, and a dot on the axis at each star. The lines,
 * labels and dots are decorative; the blocks carry the conversation's name and time. The geometry travels
 * as custom properties the stylesheet reads. */
export function TimelineBand({ view, selected, route }: Props) {
  const el = useRef<HTMLElement>(null);
  const width = useWidth(el);
  const range = timelineRange(view);
  const ticks = hourTicks(range, width);
  const items = blocks(view, range, selected, width);
  const dots = starDots(view, range);
  const { at: _at, conv: _conv, ...rest } = route.query;
  return (
    <nav class="timeline" aria-label="Timeline of the day" ref={el}>
      {ticks.map((t) => (
        <span key={t.ms} class="tl-hour" aria-hidden="true" style={{ "--left": at(t.left) }}>
          {t.label !== null && <span class="tl-hour-label">{t.label}</span>}
        </span>
      ))}
      <span class="tl-axis" aria-hidden="true" />
      {items.map((b) => (
        <span key={b.id} class="tl-item">
          <a class={b.selected ? "tl-block selected" : "tl-block"}
            href={toHash({ ...route, query: { ...rest, at: `c-${b.id}` } })}
            aria-label={b.name === b.range ? b.range : `${b.name}, ${b.range}`} title={b.name}
            style={{ "--left": at(b.left), "--width": at(b.width), "--h": `${b.height}px` }} />
          <span class={["tl-label", b.selected ? "selected" : "", b.labelShown ? "" : "dropped"].filter(Boolean).join(" ")}
            aria-hidden="true" style={{ "--left": at(b.centre), "--bottom": `${28 + b.height + 7}px` }}>{b.name}</span>
        </span>
      ))}
      {dots.map((left, i) => <span key={i} class="tl-star" aria-hidden="true" style={{ "--left": at(left) }} />)}
    </nav>
  );
}
