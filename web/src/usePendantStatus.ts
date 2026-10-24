// The pendant card's data and its two timers. GET /api/status (cheap, no device) every 15 s picks up
// the app's own ticks; POST /api/status-live (a real read over Bluetooth) every 60 s, only while
// shouldRefresh allows it, and once after every action. Unmounting clears both timers.

import { useEffect, useRef, useState } from "preact/hooks";
import {
  api, ApiError, type LiveResult, type Status, type SyncActionResult, type ToggleResult,
} from "./api";
import { isNoAddress, requestErrorLine, shouldRefresh, syncResultLine, toggleResultLine } from "./pendant";

export const STATUS_EVERY_MS = 15_000;
export const LIVE_EVERY_MS = 60_000;
const NOT_IN_RANGE = "Pendant not in range";

export type PendantAction = "sync" | "mute" | "unmute";

export interface PendantStatus {
  status: Status | null;
  /** A request of this card (an action or a live read) is in flight. */
  inflight: boolean;
  /** The last action's result in one line. */
  result: string | null;
  /** Why the last live read failed, when it did. */
  liveError: string | null;
  /** The app has no pendant address: nothing can be done from the card. */
  noAddress: boolean;
  /** The last GET /api/status failed: the reading shown may be stale. */
  unreachable: boolean;
  run: (action: PendantAction) => Promise<void>;
}

const isVisible = () => document.visibilityState === "visible";

export function usePendantStatus(): PendantStatus {
  const [status, setStatus] = useState<Status | null>(null);
  const [inflight, setInflight] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [liveError, setLiveError] = useState<string | null>(null);
  const [noAddress, setNoAddress] = useState(false);
  const [unreachable, setUnreachable] = useState(false);

  // the timers read these, not the render's values
  const statusRef = useRef<Status | null>(null);
  const inflightRef = useRef(false);
  const mounted = useRef(true);
  /** A live read found no pendant: wait for a new sync run or an action before reading again. */
  const absentSince = useRef<number | null | undefined>(undefined);

  function take(next: Status) {
    if (!mounted.current) return;
    if (absentSince.current !== undefined && (next.last_sync?.id ?? null) !== absentSince.current) {
      absentSince.current = undefined; // a sync has run since: the pendant may be back
    }
    statusRef.current = next;
    setStatus(next);
    if (isNoAddress(next.last_sync?.error)) setNoAddress(true);
  }

  async function readStatus(): Promise<Status | null> {
    try {
      const next = await api<Status>("GET", "/api/status");
      take(next);
      if (mounted.current) setUnreachable(false);
      return next;
    } catch {
      if (mounted.current) setUnreachable(true); // the next tick tries again
      return null;
    }
  }

  async function readLive(): Promise<void> {
    if (inflightRef.current) return;
    inflightRef.current = true; // a live read holds the pendant too: the buttons wait for it
    setInflight(true);
    try {
      const live = await api<LiveResult>("POST", "/api/status-live");
      if (!mounted.current) return;
      const prev = statusRef.current;
      if (prev) take({ ...prev, ...live.summary });
      setLiveError(live.ok ? null : live.error);
      setNoAddress(isNoAddress(live.error));
      if (live.error === NOT_IN_RANGE) absentSince.current = statusRef.current?.last_sync?.id ?? null;
    } catch (e) {
      // 409 busy or 503 stopping: the app is already talking to the pendant or going away; try later
      if (!(e instanceof ApiError && (e.status === 409 || e.status === 503)) && mounted.current) {
        setLiveError(requestErrorLine(e));
      }
    } finally {
      inflightRef.current = false;
      if (mounted.current) setInflight(false);
    }
    // the summary carries no busy: a poll that landed while this read held the pendant left busy set,
    // so take the app's whole snapshot now that the read has let go
    if (mounted.current) await readStatus();
  }

  function liveAllowed(s: Status | null): boolean {
    return absentSince.current === undefined && shouldRefresh(s, isVisible(), (s?.busy ?? false) || inflightRef.current);
  }

  async function run(action: PendantAction): Promise<void> {
    if (inflightRef.current) return;
    inflightRef.current = true;
    setInflight(true);
    setResult(null);
    let refused = false;
    try {
      if (action === "sync") {
        const r = await api<SyncActionResult>("POST", "/api/sync");
        if (!mounted.current) return;
        setResult(syncResultLine(r));
        setNoAddress(isNoAddress(r.sync.error) || isNoAddress(r.sync.reason));
      } else {
        const r = await api<ToggleResult>("POST", `/api/${action}`);
        if (!mounted.current) return;
        setResult(toggleResultLine(r));
        setNoAddress(isNoAddress(r.error));
      }
    } catch (e) {
      refused = e instanceof ApiError && (e.status === 409 || e.status === 503);
      if (!mounted.current) return;
      setResult(requestErrorLine(e));
      if (isNoAddress(e instanceof Error ? e.message : null)) setNoAddress(true);
    } finally {
      inflightRef.current = false;
      if (mounted.current) setInflight(false);
    }
    // read again at once: the app's view, then the pendant's own (an action is a reason to look)
    absentSince.current = undefined;
    const next = await readStatus();
    if (!refused && mounted.current && liveAllowed(next)) await readLive();
  }

  useEffect(() => {
    mounted.current = true;
    readStatus().then((first) => {
      if (mounted.current && first && liveAllowed(first)) return readLive();
    });
    const statusTimer = setInterval(() => void readStatus(), STATUS_EVERY_MS);
    const liveTimer = setInterval(() => {
      if (liveAllowed(statusRef.current)) void readLive();
    }, LIVE_EVERY_MS);
    // a window brought back to the front reads the pendant at once instead of waiting for the timer
    const onVisible = () => {
      if (isVisible() && liveAllowed(statusRef.current)) void readLive();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      mounted.current = false;
      clearInterval(statusTimer);
      clearInterval(liveTimer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, []);

  return { status, inflight, result, liveError, noAddress, unreachable, run };
}
