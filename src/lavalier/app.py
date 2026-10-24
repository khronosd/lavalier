"""The long-lived app process: it alone owns the pendant.

The scheduled drain and every action (from the CLI or, later, the window) go through one
asyncio lock, so the pendant only ever sees one session at a time. The control server runs
in its own threads and hands everything to this process's loop.
"""

import argparse
import asyncio
import logging
import signal
import sys
from logging.handlers import RotatingFileHandler
from typing import Callable, Optional

from lavalier import actions, client
from lavalier.charger import cdc_present as _cdc_in, read_ioreg
from lavalier.config import Config, load_config
from lavalier.db import Database, now_ms as _now_ms
from lavalier.lock import SyncLock
from lavalier.paths import Paths, default_root
from lavalier.pipeline import ProcessReport, status_summary
from lavalier.server import ControlServer
from lavalier.sync import SyncReport, run_sync
from lavalier.transcribe import MlxWhisperTranscriber, Transcriber

ACTIONS = ("sync", "mute", "unmute", "status-live")
SERVER_FILE = ".server.json"

_log = logging.getLogger("lavalier.app")


def _cdc_from_ioreg() -> bool:
    return _cdc_in(read_ioreg())


def _whisper(cfg: Config) -> Transcriber:
    return MlxWhisperTranscriber(cfg.whisper_model, cfg.whisper_language)


class App:
    def __init__(self, paths: Paths, cfg: Config, *, pendant_factory, transcriber_factory,
                 now_ms: Callable[[], int] = _now_ms, sleep=asyncio.sleep,
                 cdc_present: Callable[[], bool] = _cdc_from_ioreg, settle_s: float = 1.0):
        self.paths, self.cfg = paths, cfg
        self._pendant_factory = pendant_factory
        self._transcriber_factory = transcriber_factory
        self._transcriber: Optional[Transcriber] = None
        self._now_ms = now_ms
        self._sleep = sleep
        self._cdc_present = cdc_present
        self.settle_s = settle_s
        self._device_lock = asyncio.Lock()   # one pendant session at a time, inside this process
        self._lock = SyncLock(paths.root / ".lock")  # and across processes
        self._db: Optional[Database] = None
        self.pendant = None                  # the pendant of the latest session
        self.last_process: Optional[ProcessReport] = None
        self.next_poll_ms = now_ms()
        self._stopping = False
        self._sleep_task: Optional[asyncio.Task] = None
        self.token_path = paths.root / SERVER_FILE

    # state

    @property
    def db(self) -> Database:
        """Opened on first use, on the loop's thread; only the loop uses it."""
        if self._db is None:
            self.paths.ensure()
            db = Database(self.paths.db)
            db.migrate()
            self._db = db
        return self._db

    def close(self) -> None:
        if self._db is not None:
            self._db.close()
            self._db = None

    @property
    def busy(self) -> bool:
        return self._device_lock.locked()

    def snapshot(self) -> dict:
        return {**status_summary(self.db, self.paths, self.cfg, now_ms=self._now_ms()),
                "busy": self.busy, "next_poll_ms": self.next_poll_ms}

    # device work, always under self._device_lock

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

    async def _sync(self) -> tuple[SyncReport, Optional[ProcessReport]]:
        if not self.cfg.pendant_address:
            return SyncReport(outcome="error", reason=actions.ADDRESS_MISSING, error=actions.ADDRESS_MISSING), None
        report = await run_sync(self.db, self.paths, self.cfg, self._make_pendant(self.cfg), now_ms=self._now_ms,
                                lock=self._lock, cdc_present=self._cdc_present, settle_s=self.settle_s, log=_log)
        processed = None
        if report.capture is not None:  # whatever the outcome: a capture came in
            try:
                processed = await asyncio.to_thread(self._process, report)
            except Exception:
                _log.exception("processing after the sync failed")
            if processed is not None:
                self.last_process = processed
        return report, processed

    async def tick(self) -> SyncReport:
        async with self._device_lock:
            report, _ = await self._sync()
        _log.info("sync: %s (%s)", report.outcome, report.reason)
        return report

    async def action(self, name: str) -> dict:
        if name not in ACTIONS:
            raise ValueError(f"unknown action: {name}")
        async with self._device_lock:
            if name == "sync":
                return actions.sync_result(*await self._sync())
            kw = {"lock": self._lock, "cdc_present": self._cdc_present, "now_ms": self._now_ms}
            if name == "mute":
                return await actions.mute(self.db, self.cfg, self._make_pendant, **kw)
            if name == "unmute":
                return await actions.unmute(self.db, self.cfg, self._make_pendant, settle_s=self.settle_s, **kw)
            return await actions.status_live(self.db, self.paths, self.cfg, self._make_pendant, **kw)

    # the scheduler

    def stop(self) -> None:
        """Stop after the current tick or action; an interval sleep ends at once."""
        self._stopping = True
        if self._sleep_task is not None:
            self._sleep_task.cancel()

    async def run(self) -> None:
        self._stopping = False
        self.db  # open it on this loop's thread
        server = ControlServer(self, token_path=self.token_path)
        try:
            server.start()
            while not self._stopping:
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
        _log.info("%s: stopping", signame)
        app.stop()
        if app.busy:  # the session's own cleanup runs on the way out: restore, lock release, disconnect
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
