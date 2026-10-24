import { age } from "../format";
import { batteryLine, buttonsDisabled, lampState, pagesSentence, pendingUnmuteLine, stateText } from "../pendant";
import type { PendantStatus } from "../usePendantStatus";
import { Lamp } from "./Lamp";

/** The one dark element: the pendant's state from its latest read, and Sync now, Mute or Unmute. The
 * shell owns the status (usePendantStatus), since its polls also tell the pages when to refetch. */
export function PendantCard({ pendant }: { pendant: PendantStatus }) {
  const { status, inflight, result, liveError, noAddress, unreachable, run } = pendant;
  const lamp = lampState(status);
  const device = lamp === "unknown" ? null : status?.device ?? null;
  const disabled = buttonsDisabled(status, inflight);
  const pages = device ? pagesSentence(device.pages_waiting) : "";
  const pending = pendingUnmuteLine(status);

  return (
    <section class="pendant" aria-label="Pendant status" aria-busy={inflight || status?.busy ? "true" : undefined}>
      <div class="pendant-state">
        <Lamp state={lamp} />
        <span>{stateText(lamp)}</span>
      </div>
      {noAddress ? (
        <p class="pendant-note">No pendant address set. Add it in Settings › Pendant.</p>
      ) : (
        <>
          <ul class="pendant-facts">
            {unreachable ? <li class="pendant-strong">Cannot reach the app</li> : device && <li>{age(device.age_s)}</li>}
            {device && <li class="pendant-strong">{batteryLine(device)}</li>}
            {pages && <li>{pages}</li>}
            {pending && <li class="pendant-pending">{pending}</li>}
            {liveError && !result && <li>{liveError}</li>}
          </ul>
          <div class="pendant-actions">
            <button type="button" class="pendant-btn primary" disabled={disabled} onClick={() => void run("sync")}>
              Sync now
            </button>
            {lamp === "muted" && (
              <button type="button" class="pendant-btn" disabled={disabled} onClick={() => void run("unmute")}>Unmute</button>
            )}
            {(lamp === "listening" || lamp === "recording") && (
              <button type="button" class="pendant-btn" disabled={disabled} onClick={() => void run("mute")}>Mute</button>
            )}
          </div>
          {result && <p class="pendant-result" role="status">{result}</p>}
        </>
      )}
    </section>
  );
}
