import { useState } from "preact/hooks";
import { lampState, pendingUnmuteLine, pillLabel, pillWord } from "../pendant";
import type { PendantStatus } from "../usePendantStatus";
import { BatteryIcon } from "./icons";
import { Lamp } from "./Lamp";
import { PendantCard } from "./PendantCard";
import { Popover } from "./Popover";

/** The pendant in the toolbar: a pill with the lamp, the state word and the battery, named in full for a
 * screen reader. It opens the pendant card (Sync now, Mute, Unmute) as a popover under it. The pill is
 * read-only on device state, like the card: it says what the latest read said, never what an action meant. */
export function PendantPill({ pendant }: { pendant: PendantStatus }) {
  const [open, setOpen] = useState(false);
  const { status, noAddress, busyWith, inflight } = pendant;
  const lamp = noAddress ? "unknown" : lampState(status);
  const device = lamp === "unknown" ? null : status?.device ?? null;
  const busy = inflight || status?.busy;
  return (
    <div class="popover-anchor">
      <button type="button" class="pill" aria-label={pillLabel(status, noAddress, busyWith)} aria-haspopup="dialog"
        aria-expanded={open} aria-busy={busy ? "true" : undefined} onClick={() => setOpen((o) => !o)}>
        <Lamp state={lamp} />
        <span class="pill-word">{pillWord(lamp, noAddress, busyWith)}</span>
        {pendingUnmuteLine(status) && <span class="pill-pending" aria-hidden="true" />}
        {device && (
          <>
            <span class="pill-divider" aria-hidden="true" />
            <BatteryIcon soc={device.soc} />
            <span class="pill-soc">{`${device.soc}%`}</span>
          </>
        )}
      </button>
      <Popover open={open} onClose={() => setOpen(false)} role="dialog" label="Pendant" class="pill-popover">
        <PendantCard pendant={pendant} />
      </Popover>
    </div>
  );
}
