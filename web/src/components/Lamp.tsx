import type { LampState } from "../pendant";

/** The pendant's LED: lit while listening, lit with a ring while recording, dark when muted,
 * a grey outline before any reading. Decorative: the state is always written beside it. */
export function Lamp({ state }: { state: LampState }) {
  return <span class={`lamp lamp-${state}`} aria-hidden="true" />;
}
