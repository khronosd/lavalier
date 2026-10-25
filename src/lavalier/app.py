"""The long-lived app process: it alone owns the pendant.

The scheduled drain and every action (from the CLI or, later, the window) go through one
asyncio lock, so the pendant only ever sees one session at a time. The control server runs
in its own threads and hands everything to this process's loop.
"""

import argparse
import asyncio
import importlib.metadata
import json
import logging
import os
import platform
import signal
import sys
import threading
from datetime import date
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable, Optional

from lavalier import actions, audio, client, journal, pipeline, playback, search, settings
from lavalier.charger import cdc_present as _cdc_in, read_ioreg
from lavalier.config import Config, ConfigError, load_config
from lavalier.db import Database, InsightRecord, now_ms as _now_ms
from lavalier.insights import keys, registry, stage
from lavalier.insights.names import provider_id
from lavalier.insights.prompt import MAX_CHARS
from lavalier.insights.providers.anthropic import NO_KEY
from lavalier.insights.providers.base import Provider, ProviderError
from lavalier.jobs import JobFailed, JobRunning, JobTable, in_daemon_thread
from lavalier.lock import SyncLock
from lavalier.logsetup import quiet_fork_chatter
from lavalier.paths import Paths, default_root
from lavalier.pipeline import ProcessReport, status_summary
from lavalier.server import AppStopping, ControlServer, NotFound
from lavalier.sync import SyncReport, brought_audio, run_sync
from lavalier.transcribe import MlxWhisperTranscriber, Transcriber

ACTIONS = ("sync", "mute", "unmute", "status-live")
SERVER_FILE = ".server.json"
RETENTION_EVERY_MS = 86_400_000  # retention also runs at the end of every process
NO_MODEL = "No model chosen."
NO_QUESTION = "Ask a question."
RANGE_MAX_DAYS = 365
RANGE_KEY = "range"

_log = logging.getLogger("lavalier.app")


def _package_version() -> str:
    try:
        return importlib.metadata.version("lavalier")
    except importlib.metadata.PackageNotFoundError:
        return "0.0.0"


def _cdc_from_ioreg() -> bool:
    return _cdc_in(read_ioreg())


def _whisper(cfg: Config) -> Transcriber:
    return MlxWhisperTranscriber(cfg.whisper_model, cfg.whisper_language)


class App:
    def __init__(self, paths: Paths, cfg: Config, *, pendant_factory, transcriber_factory,
                 now_ms: Callable[[], int] = _now_ms, sleep=asyncio.sleep,
                 cdc_present: Callable[[], bool] = _cdc_from_ioreg, settle_s: float = 1.0,
                 lock: Optional[SyncLock] = None):
        self.paths, self.cfg = paths, cfg
        self._pendant_factory = pendant_factory
        self._transcriber_factory = transcriber_factory
        self._transcriber: Optional[Transcriber] = None
        self._now_ms = now_ms
        self._sleep = sleep
        self._cdc_present = cdc_present
        self.settle_s = settle_s
        self._device_lock = asyncio.Lock()   # one pendant session at a time, inside this process
        self._process_lock = asyncio.Lock()  # one processing run at a time; never held with the device
        self._action_tasks: set[asyncio.Task] = set()
        self._process_tasks: set[asyncio.Task] = set()  # processing started by an action, never awaited by it
        self._ticking = False
        self._lock = lock or SyncLock(paths.root / ".lock")  # and across processes
        self._db: Optional[Database] = None
        self._closed = False
        self.pendant = None                  # the pendant of the latest session
        self.last_process: Optional[ProcessReport] = None
        self.next_poll_ms = now_ms()
        self.next_retention_ms = now_ms()      # due at once: run() sweeps at start-up
        self._stopping = False
        self._sleep_task: Optional[asyncio.Task] = None
        self.token_path = paths.root / SERVER_FILE
        self.started_ms = now_ms()             # reset when run() starts the loop's work
        self.config_error: Optional[str] = None  # why the last reload failed, if it did
        self._audio_locks: dict[str, list] = {}  # clip id -> [asyncio.Lock, users]: one transcode per clip
        self.jobs = JobTable(lambda: self._now_ms())
        # builds the configured provider on the loop (one Keychain read); tests hand back a fake
        self.provider_factory: Callable[[Config], Optional[Provider]] = lambda cfg: registry.make_provider(cfg)
        self._insights_job: Optional[str] = None  # the loop's latest automatic run
        self._attempted: set[date] = set()          # days the automatic run tried in this process
        self._key_present: dict[str, Optional[bool]] = {}  # see note_key; never the key itself
        self._key_errors: dict[str, str] = {}
        self._key_version: dict[str, int] = {}             # bumped by every key route write
        self._key_lock = threading.Lock()
        self._key_fill: Optional[threading.Thread] = None
        self._key_arrived_ms: Optional[int] = None         # a key became present for the active provider
        self._asks = 0

    # state

    @property
    def db(self) -> Database:
        """Opened on first use, on the loop's thread; only the loop uses it."""
        if self._closed:
            raise RuntimeError("the app is closed")
        if self._db is None:
            self.paths.ensure()
            db = Database(self.paths.db)
            db.migrate()
            self._db = db
        return self._db

    def close(self) -> None:
        self._closed = True
        if self._db is not None:
            self._db.close()
            self._db = None

    @property
    def busy(self) -> bool:
        return self._device_lock.locked()

    def snapshot(self) -> dict:
        summary = status_summary(self.db, self.paths, self.cfg, now_ms=self._now_ms())
        summary["insights"] = {**summary.get("insights", {}), "provider": self.cfg.insights_provider,
                               "model": self.cfg.insights_model, "auto": self.cfg.insights_auto,
                               "generating": self._generating_days()}
        return {**summary, "busy": self.busy, "next_poll_ms": self.next_poll_ms,
                "app": {"version": _package_version(), "pid": os.getpid(), "started_ms": self.started_ms}}

    # the window's data; called on the loop, the only thread that uses self.db

    def view_days(self) -> list:
        return journal.to_json(journal.days_index(self.db, self.cfg, now_ms=self._now_ms()))

    def view_day(self, day: date) -> dict:
        return journal.to_json(journal.day_view(self.db, day, self.cfg, now_ms=self._now_ms()))

    def view_starred(self) -> list:
        return [{"day": d.isoformat(), "star": journal.to_json(s)} for d, s in journal.all_stars(self.db, self.cfg)]

    def view_search(self, text: str, limit: int) -> list:
        return [journal.to_json(h) for h in search.search(self.db, text, limit=limit)]

    def set_pinned(self, conversation_id: str, pinned: bool) -> dict:
        conv = self.db.conversation(conversation_id)
        if conv is None:
            raise NotFound(conversation_id)
        with self.db.transaction():
            (self.db.pin if pinned else self.db.unpin)(conversation_id)
            self.db.mark_day_dirty(conv.day)  # the next write refreshes the day file
        return {"pinned": pinned}

    def get_settings(self) -> dict:
        return settings.read_settings(self.cfg, self.paths)

    def update_settings(self, patch: dict) -> dict:
        """Patch config.toml as it is on disk (another writer, the window, may have saved since this
        process read it), then use the result, so the next tick and action see the new values. A
        drain already running keeps the Config it started with."""
        before = self.cfg
        try:
            self.cfg = settings.apply(self.cfg, patch, self.paths.config)
        except ConfigError as e:
            self.config_error = str(e)
            raise RuntimeError(f"not saved: {e}") from e
        self.config_error = None
        self._note_insights_change(before)
        if (before.insights_model, before.insights_base_url) != (self.cfg.insights_model, self.cfg.insights_base_url):
            self._attempted.clear()  # another model may well manage the days the last one failed
        return self.get_settings()

    def _provider_id(self, cfg: Optional[Config] = None) -> str:
        cfg = cfg or self.cfg
        return provider_id(cfg.insights_provider, cfg.insights_base_url)

    def _restart_auto(self, at_ms: int) -> None:
        """Automatic insights cover the days completed from `at_ms` on, never the backlog (which is sent
        only from the range, with its estimate). The provider is stored beside the moment."""
        self.db.set_status("insights_enabled_at_ms", str(at_ms))
        self.db.set_status("insights_enabled_provider", self._provider_id())
        self._attempted.clear()

    def _note_insights_change(self, before: Config) -> None:
        """Choosing a provider (or another, or another endpoint) and turning auto back on each restart the
        automatic run from now. Clearing the provider or turning auto off leaves the moment as it was."""
        now_id = self._provider_id()
        if not now_id:
            return
        changed = now_id != self._provider_id(before)
        if changed or (self.cfg.insights_auto and not before.insights_auto):
            self._restart_auto(self._now_ms())
        account = self._key_account()
        if changed and self.cfg.insights_provider in registry.KEYED and self._key_present.get(account) is None:
            self._fill_key_cache(account)  # the automatic run waits until the key is known present

    def _enabled_at_ms(self) -> Optional[int]:
        """Loop only: the moment automatic insights start from, after applying a key that arrived since."""
        with self._key_lock:
            arrived, self._key_arrived_ms = self._key_arrived_ms, None
        if arrived is not None and self.cfg.insights_provider:
            self._restart_auto(arrived)
        raw = self.db.get_status("insights_enabled_at_ms")
        return int(raw) if raw else None

    async def audio_file(self, clip_id: str) -> Path:
        """The clip's AAC file, transcoded once on first use. The row is read here on the loop; only
        ffmpeg runs in a worker thread, under the clip's own lock, so one clip is never transcoded twice."""
        entry = self._audio_locks.setdefault(clip_id, [asyncio.Lock(), 0])
        entry[1] += 1
        try:
            async with entry[0]:
                src, dst = playback.locate(self.db, self.paths, clip_id, cfg=self.cfg, now_ms=self._now_ms())
                if not dst.exists():
                    await asyncio.to_thread(playback.transcode, src, dst)
                return dst
        finally:
            entry[1] -= 1
            if not entry[1]:
                del self._audio_locks[clip_id]


    # insights: the loop's automatic run, and the jobs the window and the CLI start and poll.
    # The loop never reads the Keychain or builds a provider (a Keychain prompt would stall the loop that
    # owns the pendant): workers do, and what they learn of a key lands in a small cache read here.

    def note_key(self, provider: str, present: Optional[bool], error: Optional[str] = None, *,
                 seen: Optional[int] = None) -> None:
        """What the app knows of a provider's key (never the key). The key routes write it as they are
        (`seen` None) and bump the provider's version; a worker or the start-up fill passes the version it
        saw before its own Keychain read (`_key_seen`), and its answer is dropped when a route wrote since.
        Plain dict operations under a lock: safe from any thread, and never a Keychain call."""
        with self._key_lock:
            if seen is None:
                self._key_version[provider] = self._key_version.get(provider, 0) + 1
            elif self._key_version.get(provider, 0) != seen:
                return
            before = self._key_present.get(provider)
            # a key that first becomes present for the active provider (saved in Settings, or found by a
            # worker where there was none) restarts the automatic run from now: the days that piled up
            # without a key go through the range and its estimate
            if present is True and (before is False or (seen is None and before is not True)) \
                    and self.cfg.insights_provider in registry.KEYED and provider == self._key_account():
                self._key_arrived_ms = self._now_ms()
            self._key_present[provider] = present
            if error is None:
                self._key_errors.pop(provider, None)
            else:
                self._key_errors[provider] = error

    def _key_seen(self, provider: str) -> int:
        with self._key_lock:
            return self._key_version.get(provider, 0)

    def _read_key_presence(self, provider: str) -> bool:
        """Off the loop only: read the Keychain once and note what it said. Raises KeychainError."""
        seen = self._key_seen(provider)
        try:
            present = keys.has_key(provider)
        except keys.KeychainError as e:
            self.note_key(provider, None, str(e), seen=seen)
            raise
        self.note_key(provider, present, seen=seen)
        return present

    def _fill_key_cache(self, provider: str) -> None:
        """The start-up fill, on a daemon thread of its own: never awaited, and never waited for at exit,
        so a Keychain prompt nobody answers holds up neither the first drain nor a stop."""
        def fill():
            try:
                self._read_key_presence(provider)
            except keys.KeychainError as e:
                _log.warning("the Keychain did not answer for %s: %s", provider, e)
            except Exception:
                _log.exception("reading the key cache failed")
        self._key_fill = threading.Thread(target=fill, name="lavalier-key-fill", daemon=True)
        self._key_fill.start()

    def _unusable_reason(self, *, keychain_errors: bool = True) -> Optional[str]:
        """Why Generate and Ask are refused, from the config and the key cache only; None when usable. A key
        not known either way counts as present: the worker reads it and reports NO_KEY itself. With
        `keychain_errors=False` a cached Keychain error counts as not known either way."""
        name = self.cfg.insights_provider
        if not name:
            return NO_MODEL
        if name in registry.KEYED:
            account = self._key_account()
            error = self._key_errors.get(account)
            if error is not None:
                return error if keychain_errors else None
            if self._key_present.get(account) is False:
                return NO_KEY
        return None

    def _check_usable(self) -> None:
        """On-demand runs: a cached Keychain error does not refuse them (the worker reads the Keychain
        again, and its answer refreshes the cache); the automatic run and the shown reason keep it."""
        if self._stopping:
            raise AppStopping()
        reason = self._unusable_reason(keychain_errors=False)
        if reason is not None:
            raise ValueError(reason)

    def _key_account(self, cfg: Optional[Config] = None) -> str:
        """The Keychain account the key cache is kept under for the configured provider (one per endpoint)."""
        return registry.key_account(cfg or self.cfg)

    def _build_provider(self, cfg: Config) -> Provider:
        """Worker thread only: the Keychain read and the provider, with the key cache brought up to date."""
        if cfg.insights_provider in registry.KEYED:
            try:
                present = self._read_key_presence(self._key_account(cfg))
            except keys.KeychainError as e:
                raise JobFailed(str(e)) from None
            if not present:
                raise JobFailed(NO_KEY)
        try:
            provider = self.provider_factory(cfg)
        except (keys.KeychainError, ValueError) as e:
            raise JobFailed(str(e)) from None
        if provider is None:
            raise JobFailed(NO_MODEL)
        return provider

    def _generating_days(self) -> list[str]:
        return sorted(k.split(":", 1)[1] for k in self.jobs.running_keys() if k.startswith("day:"))

    def _days_without_done(self) -> list[date]:
        """Complete days with speech that have no done row (an error row counts as none); oldest first."""
        now = self._now_ms()
        return [d for d in self.db.days_with_speech()
                if stage.day_is_complete(d, now) and not _is_done(self.db.insight(d))]

    async def insights_if_due(self) -> bool:
        """One due day per loop turn, like retention: under the process lock, never waiting for it (a due
        day that finds it held is tried on a later turn). It runs as a `day:` job, so a Generate for the
        same day is refused meanwhile and the day reads "generating"; the job is not awaited, so a slow
        model never holds up the scheduled drain. Each day is tried at most once per process, whatever
        the outcome, except when the key was missing (it is tried again once one is saved). True when a
        run was started."""
        enabled_at = self._enabled_at_ms()
        if self._stopping or not self.cfg.insights_provider or not self._process_lock_free():
            return False
        due = [d for d in stage.due_days(self.db, self.cfg, now_ms=self._now_ms(), enabled_at_ms=enabled_at)
               if d not in self._attempted and self.jobs.running(f"day:{d.isoformat()}") is None]
        if not due:
            return False
        day = due[0]
        reason = self._unusable_reason()
        if reason == NO_KEY:
            return False  # waits for a key; Settings show why
        if reason is not None:  # a Keychain refusal: said once for the day
            _log.warning("insights: %s skipped: %s", day.isoformat(), reason)
            self._attempted.add(day)
            return False
        if self.cfg.insights_provider in registry.KEYED and self._key_present.get(self._key_account()) is not True:
            return False  # not known either way yet: the start-up fill or Settings will tell
        self._attempted.add(day)
        cfg = self.cfg
        self._insights_job = self.jobs.start(
            "auto", f"day:{day.isoformat()}", lambda provider: self._generate_job(cfg, day, provider),
            prepare=lambda: self._build_provider(cfg), lock=self._process_lock,
            on_done=lambda job: self._auto_done(day, job))
        return True

    def _auto_done(self, day: date, job: dict) -> None:
        if job["state"] == "error":
            if job["error"] == NO_KEY:
                self._attempted.discard(day)  # tried again once a key is saved
            _log.warning("insights: %s failed: %s", day.isoformat(), job["error"])
            return
        rec = job["result"]["record"]
        if rec["state"] == "done":
            _log.info("insights: %s done by %s", day.isoformat(), rec["model"])
        else:
            _log.warning("insights: %s failed: %s", day.isoformat(), rec["error"])

    def generate(self, day: date) -> str:
        """Generate (or regenerate) one day as a job. It waits for the process lock before its thread
        starts and releases it when the thread ends."""
        key = f"day:{day.isoformat()}"
        if self.jobs.running(key) is not None:
            raise JobRunning(key)
        self._check_usable()
        cfg = self.cfg
        return self.jobs.start("generate", key, lambda provider: self._generate_job(cfg, day, provider),
                               prepare=lambda: self._build_provider(cfg), lock=self._process_lock)

    def _generate_job(self, cfg: Config, day: date, provider: Provider) -> dict:
        """Worker thread, under the process lock; the provider was built before the lock was taken."""
        db = Database(self.paths.db)
        try:
            rec = stage.generate_day(db, self.paths, cfg, provider, day, now_ms=self._now_ms())
            return {"record": journal.to_json(rec), "stored": _is_stored(db, rec)}
        finally:
            db.close()

    def generate_range(self, days: int) -> str:
        """One job for the newest `days` complete days with speech and no done row, generated oldest
        first. It takes the process lock for one day at a time, so drains and processing interleave
        with a long backfill."""
        if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= RANGE_MAX_DAYS:
            raise ValueError(f"days must be a whole number from 1 to {RANGE_MAX_DAYS}")
        if self.jobs.running(RANGE_KEY) is not None:
            raise JobRunning(RANGE_KEY)
        self._check_usable()
        cfg, todo = self.cfg, self._days_without_done()[-days:]
        return self.jobs.start_coro("generate_range", RANGE_KEY, lambda: self._range(cfg, todo))

    async def _range(self, cfg: Config, todo: list[date]) -> dict:
        done, errors = 0, []
        if not todo:
            return {"done": done, "errors": errors}
        provider = await in_daemon_thread(lambda: self._build_provider(cfg))  # before any lock is taken
        for d in todo:
            if self._stopping:
                break
            await self._process_lock.acquire()
            try:
                worker = in_daemon_thread(lambda d=d: self._range_day(cfg, d, provider))
            except BaseException:
                self._process_lock.release()
                raise
            worker.add_done_callback(lambda w: self._process_lock.release())  # when the thread ends
            rec = await asyncio.shield(worker)
            if rec is None:
                continue
            if rec.state == "done":
                done += 1
            else:
                errors.append({"day": d.isoformat(), "error": rec.error})
        return {"done": done, "errors": errors}

    def _range_day(self, cfg: Config, day: date, provider: Provider) -> Optional[InsightRecord]:
        """Worker thread, under the process lock: one day of a range, with the provider built before."""
        db = Database(self.paths.db)
        try:
            if _is_done(db.insight(day)):  # generated on its own while the range waited
                return None
            return stage.generate_day(db, self.paths, cfg, provider, day, now_ms=self._now_ms())
        finally:
            db.close()

    def ask(self, day: date, question: str) -> str:
        """A question about one day, as a job. It only reads, so it takes no lock."""
        q = question.strip() if isinstance(question, str) else ""
        if not q:
            raise ValueError(NO_QUESTION)
        self._check_usable()
        cfg = self.cfg
        self._asks += 1
        return self.jobs.start("ask", f"ask:{day.isoformat()}:{self._asks}",
                               lambda provider: self._ask_job(cfg, day, q, provider),
                               prepare=lambda: self._build_provider(cfg))

    def _ask_job(self, cfg: Config, day: date, question: str, provider: Provider) -> dict:
        db = Database(self.paths.db)
        try:
            return {"answer": stage.ask_day(db, cfg, provider, day, question, now_ms=self._now_ms())}
        except (ProviderError, keys.KeychainError) as e:
            raise JobFailed(str(e)) from None
        finally:
            db.close()

    def job(self, job_id: str) -> dict:
        j = self.jobs.get(job_id)
        if j is None:
            raise NotFound(job_id)
        return j

    def insights_day(self, day: date) -> dict:
        rec = self.db.insight(day)
        job = self.jobs.running(f"day:{day.isoformat()}")
        state = "generating" if job is not None else rec.state if rec is not None else "none"
        reason = self._unusable_reason()
        if reason is None and day not in self.db.days_with_speech():
            reason = stage.NO_SPEECH
        return {"state": state, "record": journal.to_json(rec) if rec is not None else None,
                "reason": reason, "job": job}

    def insights_index(self) -> dict:
        now = self._now_ms()
        done = self.db.insights_all()  # newest day first
        follow_ups = sorted(({"day": r.day.isoformat(), "text": f.text, "at_ms": f.at_ms, "line_id": f.line_id}
                             for r in done for f in r.insight.follow_ups),
                            key=lambda f: (f["day"], f["at_ms"] or 0), reverse=True)
        # `chars`: what a failed run sent, else an estimate of the day's text from one query (its
        # transcript characters, capped at what one send can carry), never the day text built per day
        estimate = self.db.day_text_chars()
        without = []
        for d in reversed(self._days_without_done()):  # newest first
            rec = self.db.insight(d)
            chars = rec.input_chars if rec is not None else min(estimate.get(d, 0), MAX_CHARS)
            without.append({"day": d.isoformat(), "chars": chars, "error": rec.error if rec is not None else None})
        due = stage.due_days(self.db, self.cfg, now_ms=now, enabled_at_ms=self._enabled_at_ms())
        return {"follow_ups": follow_ups, "people": _by_name(done, "people"), "topics": _by_name(done, "topics"),
                "days_without": without, "generating": self._generating_days(),
                "due": [d.isoformat() for d in due],
                "auto": bool(self.cfg.insights_auto and self.cfg.insights_provider)}

    # device work, always under self._device_lock

    def reload_config(self) -> bool:
        """Re-read config.toml; the next tick and action use the new values.
        An unreadable file keeps the old config, is logged, and returns False."""
        before = self.cfg
        try:
            self.cfg = load_config(self.paths.config)
        except ConfigError as e:
            _log.error("config reload failed, keeping the previous settings: %s", e)
            self.config_error = str(e)
            return False
        self.config_error = None
        self._note_insights_change(before)
        return True

    def _make_pendant(self, cfg: Config):
        self.pendant = self._pendant_factory(cfg)
        return self.pendant

    def _make_transcriber(self) -> Transcriber:
        if self._transcriber is None:
            self._transcriber = self._transcriber_factory(self.cfg)
        return self._transcriber

    def _process(self, report: SyncReport) -> Optional[ProcessReport]:
        """Runs in a worker thread, so it opens its own connection to the database."""
        db = Database(self.paths.db)
        try:
            return actions.process_after_sync(db, self.paths, self.cfg, report, self._make_transcriber,
                                              now_ms=self._now_ms())
        finally:
            db.close()

    async def _sync_device(self, *, scheduled: bool = False) -> SyncReport:
        """The device half of a sync; the caller holds the device lock."""
        if not self.cfg.pendant_address:
            return SyncReport(outcome="error", reason=actions.ADDRESS_MISSING, error=actions.ADDRESS_MISSING)
        return await run_sync(self.db, self.paths, self.cfg, self._make_pendant(self.cfg), now_ms=self._now_ms,
                              lock=self._lock, cdc_present=self._cdc_present, settle_s=self.settle_s, log=_log, scheduled=scheduled)

    async def _process_capture(self, report: SyncReport) -> Optional[ProcessReport]:
        """Process what came in, whatever the outcome. No device involved, so the device lock is
        free meanwhile; the process lock keeps two processing runs from overlapping. The lock is
        released when the worker thread ends, not when this coroutine does: cancelling the wait
        cannot stop the thread, so it must not let a second run start beside it."""
        if not brought_audio(report):
            return None
        await self._process_lock.acquire()
        try:
            worker = asyncio.ensure_future(asyncio.to_thread(self._process, report))
        except BaseException:
            self._process_lock.release()
            raise
        worker.add_done_callback(self._process_finished)
        try:
            return await asyncio.shield(worker)
        except Exception:
            return None  # logged by _process_finished

    def _process_finished(self, worker: asyncio.Future) -> None:
        self._process_lock.release()
        if worker.cancelled():
            return
        if worker.exception() is not None:
            _log.error("processing after the sync failed", exc_info=worker.exception())
        elif worker.result() is not None:
            self.last_process = worker.result()

    # start-up: finish what an earlier run left pending

    async def process_pending_if_any(self) -> bool:
        """Clips an earlier run left pending (ffmpeg was missing, a crash mid-process) are finished at
        start-up without waiting for the next drain. Under the process lock, never waiting for it:
        a run in progress will cover them. True when a run was made."""
        if not (self.db.clips_needing_transcript() or self.db.clips_needing_loudness()):
            return False
        if self._process_lock.locked():
            return False
        await self._process_lock.acquire()  # free: returns without yielding
        try:
            worker = asyncio.ensure_future(asyncio.to_thread(self._process_pending))
        except BaseException:
            self._process_lock.release()
            raise
        worker.add_done_callback(self._pending_finished)
        try:
            await asyncio.shield(worker)
        except Exception:
            pass  # logged by _pending_finished
        return True

    def _process_pending(self) -> ProcessReport:
        """Runs in a worker thread, on its own connection, like _process."""
        db = Database(self.paths.db)
        try:
            now = self._now_ms()
            report = pipeline.process(db, self.paths, self.cfg, self._make_transcriber(), now_ms=now)
            db.set_status("last_process", json.dumps({**report.to_json_dict(), "processed_ms": now}))
            return report
        finally:
            db.close()

    def _pending_finished(self, worker: asyncio.Future) -> None:
        self._process_lock.release()
        if worker.cancelled():
            return
        if worker.exception() is not None:
            _log.error("start-up processing failed", exc_info=worker.exception())
            return
        r = worker.result()
        self.last_process = r
        _log.info("start-up processing: %d transcribed, %d failed, %d day file(s) written",
                  r.transcribed, r.failed, len(r.days_written))

    def _process_lock_free(self) -> bool:
        """Whether acquiring the process lock now returns without yielding. A generate job queued for
        it counts as held: just after a release the lock reads free while that waiter is owed it, and
        an acquire then would queue behind the job."""
        return not self._process_lock.locked() and not any(
            k.startswith("day:") or k == RANGE_KEY for k in self.jobs.running_keys())

    def _retention(self) -> ProcessReport:
        """Runs in a worker thread, like _process, on its own connection."""
        db = Database(self.paths.db)
        try:
            return pipeline.retention_tick(db, self.paths, self.cfg, now_ms=self._now_ms())
        finally:
            db.close()

    async def retention_if_due(self) -> bool:
        """Retention once a day, so audio expires even when no drain brings any (a process sweeps
        too). It takes the process lock and never waits for it: a run in progress sweeps itself, and
        a due tick that finds it held is tried again on the next loop turn. Like a process, the lock
        is released when the worker thread ends. True when it ran (or failed, logged: either way the
        next is a day later)."""
        now = self._now_ms()
        if now < self.next_retention_ms or not self._process_lock_free():
            return False
        await self._process_lock.acquire()  # free: returns without yielding
        try:
            worker = asyncio.ensure_future(asyncio.to_thread(self._retention))
        except BaseException:
            self._process_lock.release()
            raise
        worker.add_done_callback(self._retention_finished)
        self.next_retention_ms = now + RETENTION_EVERY_MS
        try:
            await asyncio.shield(worker)
        except Exception:
            pass  # logged by _retention_finished
        return True

    def _retention_finished(self, worker: asyncio.Future) -> None:
        self._process_lock.release()
        if worker.cancelled():
            return
        if worker.exception() is not None:
            _log.error("retention failed", exc_info=worker.exception())
        else:
            r = worker.result()
            _log.info("retention: %d clip(s) and %d capture(s) deleted, %d day file(s) rewritten",
                      r.clips_deleted, r.captures_deleted, len(r.days_written))

    def _schedule_process(self, report: SyncReport) -> Optional[str]:
        """Processing after an action runs as its own task: an action cancelled or timed out
        afterwards can never interrupt it."""
        if not brought_audio(report):
            return None
        task = asyncio.ensure_future(self._process_capture(report))
        self._process_tasks.add(task)
        task.add_done_callback(self._process_tasks.discard)
        return "scheduled"

    async def processing_done(self) -> None:
        """Wait for every processing run an action scheduled."""
        while self._process_tasks:
            await asyncio.gather(*self._process_tasks, return_exceptions=True)

    async def tick(self) -> SyncReport:
        # marked before the wait, so a signal cancels a tick queued behind an action as well
        self._ticking = True
        try:
            async with self._device_lock:
                if self._stopping:  # stop() came while this waited: no new session during shutdown
                    return SyncReport(outcome="skipped", reason="stopping")
                report = await self._sync_device(scheduled=True)
        finally:
            self._ticking = False
        _log.info("sync: %s (%s)", report.outcome, report.reason)
        await self._process_capture(report)
        return report

    async def action(self, name: str) -> dict:
        if name not in ACTIONS:
            raise ValueError(f"unknown action: {name}")
        if self._stopping:
            raise AppStopping()
        task = asyncio.current_task()
        self._action_tasks.add(task)
        try:
            async with self._device_lock:
                if self._stopping:  # stop() came while this waited for the device
                    raise AppStopping()
                if name == "sync":
                    report = await self._sync_device()
                else:
                    return await self._device_action(name)
            return {"sync": report.to_json_dict(), "process": self._schedule_process(report)}
        finally:
            self._action_tasks.discard(task)

    async def _device_action(self, name: str) -> dict:
        kw = {"lock": self._lock, "cdc_present": self._cdc_present, "now_ms": self._now_ms}
        if name == "mute":
            return await actions.mute(self.db, self.cfg, self._make_pendant, **kw)
        if name == "unmute":
            return await actions.unmute(self.db, self.cfg, self._make_pendant, settle_s=self.settle_s, **kw)
        return await actions.status_live(self.db, self.paths, self.cfg, self._make_pendant, **kw)

    # the scheduler

    @property
    def stopping(self) -> bool:
        return self._stopping

    def stop(self) -> None:
        """Refuse new actions, end an interval sleep at once, and cancel the actions in flight: each
        session's own cleanup (restore, lock release, disconnect) runs as it unwinds. Only the first
        call acts: a later one must not cancel a restore that is already running."""
        if self._stopping:
            _log.info("already stopping")
            return
        self._stopping = True
        if self._sleep_task is not None:
            self._sleep_task.cancel()
        for task in list(self._action_tasks):
            task.cancel()

    def _startup_housekeeping(self) -> None:
        """A sync row still "running" belongs to a process that died: close it before the first tick."""
        closed = self.db.close_running_sync_runs(self._now_ms())
        if closed:
            _log.warning("closed %d sync run(s) left running by an earlier process", closed)
        if self.cfg.insights_provider and (self.db.get_status("insights_enabled_at_ms") is None or
                                           self.db.get_status("insights_enabled_provider") != self._provider_id()):
            # a provider set or changed in config.toml by hand while stopped: automatic insights start from
            # now, never from a moment recorded for another provider
            self._restart_auto(self._now_ms())

    async def run(self) -> None:
        self._stopping = False
        self.started_ms = self._now_ms()
        self.next_retention_ms = self.started_ms
        self.db  # open it on this loop's thread
        self._startup_housekeeping()
        server = ControlServer(self, token_path=self.token_path)
        try:
            server.start()
            if self.cfg.insights_provider in registry.KEYED:  # the key cache, read off the loop, not awaited
                self._fill_key_cache(self._key_account())
            try:
                await self.process_pending_if_any()
            except Exception:
                _log.exception("start-up processing failed")
            while not self._stopping:
                try:
                    await self.retention_if_due()
                except Exception:
                    _log.exception("retention failed")
                try:
                    await self.tick()
                except Exception:
                    _log.exception("scheduled sync failed")
                try:  # after the drain and its processing: a day is due only once its audio is in
                    await self.insights_if_due()
                except Exception:
                    _log.exception("insights failed")
                if self._stopping:
                    break
                interval = self.cfg.poll_interval_s
                self.next_poll_ms = self._now_ms() + interval * 1000
                self._sleep_task = asyncio.ensure_future(self._sleep(interval))
                try:
                    await asyncio.wait({self._sleep_task})
                finally:
                    self._sleep_task.cancel()
                    self._sleep_task = None
        finally:
            self._stopping = True
            # in this order: every session has unwound (restored, written to the DB, file lock
            # released by its owner), then the server goes, then the file lock and the DB
            async with self._device_lock:
                server.stop()
                self._lock.release()  # only if this process still holds it
                self.close()


def _is_done(rec: Optional[InsightRecord]) -> bool:
    return rec is not None and rec.state == "done"


def _is_stored(db: Database, rec: InsightRecord) -> bool:
    """Whether the record a generate returned is the day's row now (a failed regenerate is not)."""
    row = db.insight(rec.day)
    return row is not None and (row.state, row.generated_ms, row.error) == (rec.state, rec.generated_ms, rec.error)


def _by_name(records: list[InsightRecord], attr: str) -> list[dict]:
    """Each name (people or topics) with the days it appears on, newest first; the most days first,
    names compared without case (the first spelling seen is kept)."""
    names: dict[str, dict] = {}
    for r in records:
        for name in getattr(r.insight, attr):
            entry = names.setdefault(name.casefold(), {"name": name, "days": []})
            if r.day.isoformat() not in entry["days"]:
                entry["days"].append(r.day.isoformat())
    return sorted(names.values(), key=lambda e: (-len(e["days"]), e["name"].casefold()))


def _configure_logging(paths: Paths) -> None:
    paths.logs.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    file_handler = RotatingFileHandler(paths.logs / "app.log", maxBytes=5_000_000, backupCount=3)
    stderr_handler = logging.StreamHandler(sys.stderr)
    for h in (file_handler, stderr_handler):
        h.setFormatter(fmt)
    logging.basicConfig(level=logging.INFO, handlers=[file_handler, stderr_handler], force=True)


async def _serve(app: App) -> None:
    loop = asyncio.get_running_loop()
    task = asyncio.current_task()

    def on_signal(signame: str) -> None:
        if app.stopping:  # a second Ctrl-C or TERM must not cancel a restore in progress
            _log.info("%s: already stopping", signame)
            return
        _log.info("%s: stopping", signame)
        app.stop()  # cancels the actions in flight
        if app._ticking:  # the scheduled sync runs in this task; its cleanup runs as it unwinds
            task.cancel()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, on_signal, sig.name)
    try:
        await app.run()
    except asyncio.CancelledError:
        _log.info("stopped during a device session")
    finally:
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.remove_signal_handler(sig)


def main(argv=None) -> int:
    argparse.ArgumentParser(prog="lavalier app", description="Run the lavalier app process.").parse_args(argv)
    paths = Paths(default_root())
    paths.ensure()
    _configure_logging(paths)
    quiet_fork_chatter()
    _log.info("python %s utf8_mode=%d ffmpeg=%s", platform.python_version(), sys.flags.utf8_mode,
              audio.ensure_ffmpeg_on_path())
    if client.app_running(paths.root / SERVER_FILE):
        _log.error("the lavalier app is already running")
        return 1
    cfg = load_config(paths.config)
    app = App(paths, cfg, pendant_factory=actions.ble_pendant, transcriber_factory=_whisper)
    asyncio.run(_serve(app))
    _log.info("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
