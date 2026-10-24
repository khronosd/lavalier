"""The long-lived app process: it alone owns the pendant.

The scheduled drain and every action (from the CLI or, later, the window) go through one
asyncio lock, so the pendant only ever sees one session at a time. The control server runs
in its own threads and hands everything to this process's loop.
"""

import argparse
import asyncio
import importlib.metadata
import logging
import os
import signal
import sys
from datetime import date
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable, Optional

from lavalier import actions, client, journal, pipeline, playback, search, settings
from lavalier.charger import cdc_present as _cdc_in, read_ioreg
from lavalier.config import Config, ConfigError, load_config
from lavalier.db import Database, now_ms as _now_ms
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
        return {**status_summary(self.db, self.paths, self.cfg, now_ms=self._now_ms()),
                "busy": self.busy, "next_poll_ms": self.next_poll_ms,
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
        try:
            self.cfg = settings.apply(self.cfg, patch, self.paths.config)
        except ConfigError as e:
            self.config_error = str(e)
            raise RuntimeError(f"not saved: {e}") from e
        self.config_error = None
        return self.get_settings()

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

    # device work, always under self._device_lock

    def reload_config(self) -> bool:
        """Re-read config.toml; the next tick and action use the new values.
        An unreadable file keeps the old config, is logged, and returns False."""
        try:
            self.cfg = load_config(self.paths.config)
        except ConfigError as e:
            _log.error("config reload failed, keeping the previous settings: %s", e)
            self.config_error = str(e)
            return False
        self.config_error = None
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
        if now < self.next_retention_ms or self._process_lock.locked():
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

    async def run(self) -> None:
        self._stopping = False
        self.started_ms = self._now_ms()
        self.next_retention_ms = self.started_ms
        self.db  # open it on this loop's thread
        self._startup_housekeeping()
        server = ControlServer(self, token_path=self.token_path)
        try:
            server.start()
            while not self._stopping:
                try:
                    await self.retention_if_due()
                except Exception:
                    _log.exception("retention failed")
                try:
                    await self.tick()
                except Exception:
                    _log.exception("scheduled sync failed")
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
