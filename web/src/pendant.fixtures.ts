// Test fixtures: a full device read and a status snapshot, with overrides.
import type { DeviceStatus, Status } from "./api";

export const device = (over: Partial<DeviceStatus> = {}): DeviceStatus => ({
  read_at_ms: 0, has_all_fields: true, recording_state: "LISTENING", oldest_page: 1, newest_page: 787,
  soc: 94, current_ma: -12, usb_state: "USB_DISCONNECTED", firmware_ver: "1.1.3", storage_instance: 7,
  pages_waiting: 787, source: "sync", charger_signal: "none", age_s: 30, ...over,
});

export const status = (over: Partial<Status> = {}): Status => ({
  days_with_clips: [], pending_transcripts: 0, failed_clips: 0, audio_bytes: 0, capture_bytes: 0,
  next_deletion: null, last_import: null, pinned: [], long_presses: 0, double_presses: 0, last_process: null,
  device: device(), last_sync: null, unmute_pending_since_ms: null, muted_by_recorder_since_ms: null,
  muted_by_owner_since_ms: null, busy: false, next_poll_ms: 0, app: { version: "0.3.0", pid: 1, started_ms: 0 },
  ...over,
});
