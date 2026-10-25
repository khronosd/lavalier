"""Polled jobs: work the window or the CLI starts and then asks about by id.

Loop-thread only. Each job runs its function in a worker thread; a job may first wait for a lock,
which it releases when the thread ends (never when the waiting coroutine does), so a cancelled
wait can never let a second holder in beside a running thread.
"""

import asyncio
import logging
import secrets
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

JOB_KEEP_MS = 600_000  # a finished job is kept ten minutes, then dropped

_log = logging.getLogger("lavalier.jobs")


class JobRunning(Exception):
    """A job with the same key is still running: the server answers 409."""


class JobFailed(Exception):
    """An expected failure (the provider's own message): the job's error, logged without a traceback."""


@dataclass
class _Job:
    id: str
    kind: str
    key: str
    started_ms: int
    state: str = "running"
    result: object = None
    error: Optional[str] = None
    finished_ms: Optional[int] = None
    done: asyncio.Event = field(default_factory=asyncio.Event)
    on_done: Optional[Callable[[dict], None]] = None

    def to_dict(self) -> dict:
        return {"id": self.id, "kind": self.kind, "key": self.key, "state": self.state, "result": self.result,
                "error": self.error, "started_ms": self.started_ms, "finished_ms": self.finished_ms}


class JobTable:
    def __init__(self, now_ms: Callable[[], int]):
        self._now_ms = now_ms
        self._jobs: dict[str, _Job] = {}
        self._tasks: set[asyncio.Task] = set()

    def _prune(self) -> None:
        cutoff = self._now_ms() - JOB_KEEP_MS
        for jid in [j.id for j in self._jobs.values() if j.state != "running" and j.finished_ms < cutoff]:
            del self._jobs[jid]

    def running_keys(self) -> list[str]:
        return [j.key for j in self._jobs.values() if j.state == "running"]

    def running(self, key: str) -> Optional[str]:
        """The id of the running job with this key, if any."""
        return next((j.id for j in self._jobs.values() if j.state == "running" and j.key == key), None)

    def _new(self, kind: str, key: str, on_done: Optional[Callable[[dict], None]]) -> _Job:
        self._prune()
        if self.running(key) is not None:
            raise JobRunning(key)
        job = _Job(secrets.token_urlsafe(8), kind, key, self._now_ms(), on_done=on_done)
        self._jobs[job.id] = job
        return job

    def _spawn(self, coro) -> None:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def start(self, kind: str, key: str, fn: Callable[[], object], *, lock: Optional[asyncio.Lock] = None,
              holding: bool = False, on_done: Optional[Callable[[dict], None]] = None) -> str:
        """Run `fn` in a worker thread, after waiting for `lock` when one is given (or with it already
        acquired by the caller, `holding=True`); the lock is released when the thread ends. `on_done`
        gets the finished job's dict, on the loop. Returns the job id."""
        if not holding:
            job = self._new(kind, key, on_done)
            self._spawn(self._run(job, fn, lock))
            return job.id
        try:  # the caller holds the lock: the thread starts now, so nothing can strand the lock
            job = self._new(kind, key, on_done)
            worker = asyncio.ensure_future(asyncio.to_thread(fn))
        except BaseException:
            if lock is not None:
                lock.release()
            raise
        worker.add_done_callback(lambda w: self._worker_done(job, w, lock))
        return job.id

    def start_coro(self, kind: str, key: str, make: Callable[[], Awaitable[object]], *,
                   on_done: Optional[Callable[[dict], None]] = None) -> str:
        """Run a coroutine on the loop as a job (one that takes and releases locks itself)."""
        job = self._new(kind, key, on_done)
        self._spawn(self._run_coro(job, make))
        return job.id

    def get(self, job_id: str) -> Optional[dict]:
        self._prune()
        job = self._jobs.get(job_id)
        return job.to_dict() if job is not None else None

    async def wait(self, job_id: str) -> None:
        job = self._jobs.get(job_id)
        if job is not None:
            await job.done.wait()

    def _finish(self, job: _Job, *, result=None, error: Optional[str] = None) -> None:
        job.state = "error" if error is not None else "done"
        job.result, job.error, job.finished_ms = result, error, self._now_ms()
        job.done.set()
        if job.on_done is not None:
            try:
                job.on_done(job.to_dict())
            except Exception:
                _log.exception("%s job %s: the done callback failed", job.kind, job.key)

    async def _run_coro(self, job: _Job, make: Callable[[], Awaitable[object]]) -> None:
        try:
            result = await make()
        except asyncio.CancelledError:
            self._finish(job, error="cancelled")
            raise
        except JobFailed as e:
            _log.info("%s job %s failed: %s", job.kind, job.key, e)
            self._finish(job, error=str(e))
        except Exception as e:
            _log.error("%s job %s failed", job.kind, job.key, exc_info=e)
            self._finish(job, error=str(e) or type(e).__name__)
        else:
            self._finish(job, result=result)

    async def _run(self, job: _Job, fn: Callable[[], object], lock: Optional[asyncio.Lock]) -> None:
        try:
            if lock is not None:
                await lock.acquire()
            try:
                worker = asyncio.ensure_future(asyncio.to_thread(fn))
            except BaseException:
                if lock is not None:
                    lock.release()
                raise
        except asyncio.CancelledError:  # the app is shutting down while this waited
            self._finish(job, error="cancelled")
            raise
        worker.add_done_callback(lambda w: self._worker_done(job, w, lock))

    def _worker_done(self, job: _Job, worker: asyncio.Future, lock: Optional[asyncio.Lock]) -> None:
        if lock is not None:
            lock.release()
        if worker.cancelled():
            self._finish(job, error="cancelled")
        elif isinstance(worker.exception(), JobFailed):
            _log.info("%s job %s failed: %s", job.kind, job.key, worker.exception())
            self._finish(job, error=str(worker.exception()))
        elif worker.exception() is not None:
            e = worker.exception()
            _log.error("%s job %s failed", job.kind, job.key, exc_info=e)
            self._finish(job, error=str(e) or type(e).__name__)
        else:
            self._finish(job, result=worker.result())
