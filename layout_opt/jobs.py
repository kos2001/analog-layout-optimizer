"""Non-blocking compute service + async job registry for the web backend.

``ComputeService`` runs engine calls off the server's event loop and process:

* **process mode** (default): a shared, lazily started ``ProcessPoolExecutor``
  (spawn context). The engine is pure-Python CPU-bound code, so threads would
  serialize on the GIL and starve the live endpoints; separate processes keep
  the API process responsive and use every core. Requests/results are plain
  JSON-like dicts, so they pickle cheaply.
* **thread mode** (``ALO_EXECUTOR=thread``, or automatic fallback when no
  process pool can be started): same API, in-process.

Every submission goes through a provenance-keyed ``ResultCache``: a repeat of
an identical request is a cache hit, and concurrent identical requests share
one in-flight computation.

Stage progress: in process mode each task runs under a ``runlog.Profiler``
whose ``on_stage`` hook forwards ``with stage("...")`` completions over a
multiprocessing queue; listeners (jobs) receive them by provenance key.

``JobRegistry`` is the asynchronous front: submit -> 202 + job id, poll, SSE,
cancel-while-queued. At most ``max_running`` jobs are admitted to the compute
pool; the rest wait in a FIFO queue (cancellable). An identical request while
one is queued/running returns the *existing* job (deduplicated, not 409).
Finished jobs are evicted oldest-first beyond ``max_jobs``.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import multiprocessing
import os
import queue
import threading
import time
import uuid
from collections import OrderedDict, deque
from concurrent.futures import Future, ProcessPoolExecutor, ThreadPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass, field
from typing import Any, Callable

from .provenance import ResultCache, code_version
from .runlog import Profiler

log = logging.getLogger("alo.service")

TERMINAL = frozenset({"done", "error", "cancelled"})


# --------------------------------------------------------------------------
# Worker-process side (top-level so they pickle by reference)
# --------------------------------------------------------------------------
_progress_q = None
_skew: str | None = None


class CodeSkewError(RuntimeError):
    """A worker loaded different engine sources than the server keys results by."""


def _worker_init(q, expected_version: str | None = None) -> None:
    global _progress_q, _skew
    _progress_q = q
    # Hash the sources *before* any task imports them. A worker (re)spawned
    # after an edit would otherwise compute with new code under the server's
    # old provenance key and poison the cache.
    mine = code_version()
    if expected_version and mine != expected_version:
        _skew = (f"engine sources changed since the server started (worker {mine} "
                 f"!= server {expected_version}); restart the server")


def _worker_call(fn: Callable, kwargs: dict, tag: str, run_id: str) -> tuple[Any, list]:
    """Run one task; returns (result, event log).

    Events also stream live over the progress queue, but that channel is not
    ordered with the result pipe, so the full log rides along with the result
    and the parent replays whatever it has not seen before completing.
    """
    if _skew:
        raise CodeSkewError(_skew)
    events: list[tuple[int, str, dict]] = []

    def emit(event: str, data: dict) -> None:
        events.append((len(events) + 1, event, data))
        if _progress_q is not None:
            try:
                _progress_q.put_nowait((tag, run_id, len(events), event, data))
            except Exception:                  # noqa: BLE001 - live progress is best-effort
                pass

    emit("started", {})
    with Profiler(lambda st, wall: emit("stage", {"stage": st.name, "wallS": round(wall, 4)})):
        result = fn(**kwargs)
    return result, events


def _import_module(name: str) -> str:
    """Pre-warm a worker: import the module that owns the task functions."""
    if _skew:
        raise CodeSkewError(_skew)
    importlib.import_module(name)
    return name


def _thread_call(fn: Callable, kwargs: dict, tag: str, notify: Callable) -> Any:
    # runlog's active-profiler list is process-global, so per-thread stage
    # capture would mix concurrent jobs: thread mode reports start only.
    notify(tag, "started", {})
    return fn(**kwargs)


def gather_futures(futs: list[Future], combine: Callable[[list], Any]) -> Future:
    """Future of ``combine([f.result() ...])`` (input order); first error wins."""
    out: Future = Future()
    out.set_running_or_notify_cancel()
    remaining = [len(futs)]
    lock = threading.Lock()

    def _one(_f: Future) -> None:
        with lock:
            remaining[0] -= 1
            last = remaining[0] == 0
        if out.done():
            return
        if _f.cancelled() or _f.exception() is not None:
            err = _f.exception() if not _f.cancelled() else RuntimeError("sub-task cancelled")
            try:
                out.set_exception(err)
            except Exception:                  # noqa: BLE001 - lost the race to another error
                pass
            return
        if last:
            try:
                out.set_result(combine([f.result() for f in futs]))
            except BaseException as e:         # noqa: BLE001
                out.set_exception(e)

    if not futs:
        out.set_result(combine([]))
    for f in futs:
        f.add_done_callback(_one)
    return out


async def await_shared(fut: Future) -> Any:
    """Await a (possibly shared) concurrent Future without ever cancelling it.

    ``asyncio.wrap_future`` propagates cancellation of the awaiting task back
    into the source future, which would kill a computation other requests (or
    the cache) are waiting on. This one-way bridge never does.
    """
    loop = asyncio.get_running_loop()
    af = loop.create_future()

    def _copy(f: Future) -> None:
        if af.done():
            return
        if f.cancelled():
            af.set_exception(RuntimeError("computation cancelled"))
        elif f.exception() is not None:
            af.set_exception(f.exception())
        else:
            af.set_result(f.result())

    def _done(f: Future) -> None:
        try:
            loop.call_soon_threadsafe(_copy, f)
        except RuntimeError:                   # awaiting loop already closed
            pass

    fut.add_done_callback(_done)
    return await af


def _stop_pool(pool, grace_s: float) -> None:
    """Shut a pool down; terminate worker processes still alive after ``grace_s``."""
    # Captured before shutdown() drops the (private) process table.
    procs = list((getattr(pool, "_processes", None) or {}).values())
    pool.shutdown(wait=False, cancel_futures=True)
    deadline = time.monotonic() + grace_s
    for p in procs:
        p.join(timeout=max(0.0, deadline - time.monotonic()))
    for p in procs:
        if p.is_alive():
            p.terminate()
            p.join(timeout=1.0)
            if p.is_alive():
                p.kill()


# --------------------------------------------------------------------------
# Compute service
# --------------------------------------------------------------------------
class ComputeService:
    def __init__(self, mode: str | None = None, workers: int | None = None,
                 cache_size: int | None = None, warm_module: str | None = None):
        self.mode = (mode or os.environ.get("ALO_EXECUTOR", "process")).lower()
        if self.mode not in ("process", "thread"):
            raise ValueError(f"ALO_EXECUTOR must be 'process' or 'thread', got {self.mode!r}")
        cpus = os.cpu_count() or 1
        self.workers = workers or int(os.environ.get("ALO_WORKERS", 0)) or max(1, min(cpus - 1, 8))
        self.cache = ResultCache(cache_size if cache_size is not None
                                 else int(os.environ.get("ALO_CACHE_SIZE", 128)))
        self.warm_module = warm_module
        self._lock = threading.Lock()
        self._pool = None
        self._queue = None
        self._listeners: dict[str, list[Callable]] = {}
        self._seen: OrderedDict[str, float] = OrderedDict()   # run id -> last event seq
        # Single consumer = total order of live progress and task completions.
        self._events: queue.SimpleQueue = queue.SimpleQueue()
        self._dispatcher: threading.Thread | None = None
        self.fallback_reason: str | None = None

    # -- pool lifecycle ---------------------------------------------------
    def _ensure_pool(self):
        with self._lock:
            if self._pool is not None:
                return self._pool
            if self.mode == "process":
                try:
                    ctx = multiprocessing.get_context("spawn")
                    if self._queue is None:     # each queue gets its own reader thread
                        self._queue = ctx.Queue()
                        threading.Thread(target=self._drain_loop, args=(self._queue,),
                                         name="alo-progress", daemon=True).start()
                    self._pool = ProcessPoolExecutor(self.workers, mp_context=ctx,
                                                     initializer=_worker_init,
                                                     initargs=(self._queue, code_version()))
                except (OSError, NotImplementedError, AssertionError) as e:
                    self._fall_back_locked(f"process pool unavailable: {e}")
                else:
                    if self._dispatcher is None or not self._dispatcher.is_alive():
                        self._dispatcher = threading.Thread(target=self._dispatch_loop,
                                                            name="alo-dispatch", daemon=True)
                        self._dispatcher.start()
            if self._pool is None:
                self._pool = ThreadPoolExecutor(self.workers, thread_name_prefix="alo-compute")
            return self._pool

    def _fall_back_locked(self, reason: str) -> None:
        log.warning("compute service falling back to threads: %s", reason)
        self.fallback_reason = reason
        self.mode = "thread"

    def warm(self) -> None:
        """Start the worker processes and import the task module in each (non-blocking)."""
        if self.mode != "process" or not self.warm_module:
            return
        pool = self._ensure_pool()
        if not isinstance(pool, ProcessPoolExecutor):
            return
        for _ in range(self.workers):
            f = pool.submit(_import_module, self.warm_module)
            f.add_done_callback(self._check_warm)

    def _check_warm(self, f: Future) -> None:
        if f.cancelled() or f.exception() is None:
            return
        # Workers cannot import the task module (e.g. sys.path differs): every
        # real task would fail, so serve from threads instead.
        with self._lock:
            old, self._pool = self._pool, None
            self._fall_back_locked(f"worker import failed: {f.exception()!r}")
        if old is not None:
            threading.Thread(target=_stop_pool, args=(old, 0.0), daemon=True).start()

    def shutdown(self, grace_s: float = 2.0) -> None:
        """Cancel queued work, give running tasks ``grace_s``, then stop workers.

        ``ProcessPoolExecutor.shutdown(wait=False)`` alone can leave workers
        blocked on their call queue forever once the server process exits
        (observed: orphaned workers re-parented to init), so stragglers are
        terminated explicitly. Engine runs are pure and re-computable.
        """
        with self._lock:
            pool, self._pool = self._pool, None
            q, self._queue = self._queue, None
        if pool is not None:
            _stop_pool(pool, grace_s)
        if q is not None:
            try:
                q.put_nowait(None)             # stops the drain thread (it owns the reader)
            except Exception:                  # noqa: BLE001
                pass

    @property
    def started(self) -> bool:
        return self._pool is not None

    # -- progress ---------------------------------------------------------
    def _drain_loop(self, q) -> None:
        """Worker progress queue -> local dispatcher (keeps one total order)."""
        while True:
            try:
                item = q.get()
            except (EOFError, OSError, ValueError, TypeError):   # queue torn down
                return
            if item is None:
                return
            self._events.put(("event", item))

    def _dispatch_loop(self) -> None:
        while True:
            kind, item = self._events.get()
            try:
                if kind == "event":
                    tag, run_id, seq, event, data = item
                    self._dispatch(tag, event, data, run_id, seq)
                else:                          # "complete"
                    self._complete(*item)
            except Exception:                  # noqa: BLE001 - the dispatcher must survive
                log.exception("progress dispatch failed")

    def _complete(self, tag: str, run_id: str, raw: Future, out: Future) -> None:
        if raw.cancelled():
            out.set_exception(RuntimeError("computation cancelled"))
            return
        if raw.exception() is not None:
            out.set_exception(raw.exception())
            return
        result, events = raw.result()
        for seq, event, data in events:        # replay what the live channel has not delivered
            self._dispatch(tag, event, data, run_id, seq)
        with self._lock:
            self._seen[run_id] = float("inf")  # drop stragglers arriving after completion
        out.set_result(result)

    def _dispatch(self, tag: str, event: str, data: dict,
                  run_id: str | None = None, seq: int | None = None) -> None:
        with self._lock:
            if run_id is not None:
                if seq <= self._seen.get(run_id, 0):
                    return
                self._seen[run_id] = seq
                self._seen.move_to_end(run_id)
                while len(self._seen) > 4096:
                    self._seen.popitem(last=False)
            cbs = list(self._listeners.get(tag, ()))
        for cb in cbs:
            try:
                cb(event, data)
            except Exception:                  # noqa: BLE001 - a listener never breaks others
                log.exception("progress listener failed")

    def listen(self, tag: str, cb: Callable) -> None:
        with self._lock:
            self._listeners.setdefault(tag, []).append(cb)

    def unlisten(self, tag: str, cb: Callable) -> None:
        with self._lock:
            cbs = self._listeners.get(tag, [])
            if cb in cbs:
                cbs.remove(cb)
            if not cbs:
                self._listeners.pop(tag, None)

    # -- submission -------------------------------------------------------
    def _start(self, fn: Callable, kwargs: dict, tag: str) -> Future:
        for attempt in (0, 1):
            pool = self._ensure_pool()
            try:
                if isinstance(pool, ProcessPoolExecutor):
                    run_id = uuid.uuid4().hex
                    raw = pool.submit(_worker_call, fn, kwargs, tag, run_id)
                    fut = Future()
                    fut.set_running_or_notify_cancel()
                    raw.add_done_callback(
                        lambda r, out=fut: self._events.put(("complete", (tag, run_id, r, out))))
                else:
                    fut = pool.submit(_thread_call, fn, kwargs, tag, self._dispatch)
            except (BrokenProcessPool, RuntimeError) as e:
                # A worker died (OOM/segfault) or the pool was shut down:
                # replace it once and resubmit.
                log.warning("compute pool unusable (%s) — restarting it", e)
                with self._lock:
                    if self._pool is pool:
                        self._pool = None
                if attempt:
                    raise
                continue
            return fut
        raise RuntimeError("unreachable")

    def submit(self, key: str, fn: Callable, kwargs: dict,
               cacheable: Callable[[Any], bool] | None = None) -> tuple[Future, str]:
        """Cached + shared submission: returns (future, "hit"|"shared"|"miss")."""
        return self.cache.submit(key, lambda: self._start(fn, kwargs, key), cacheable)

    def submit_composite(self, key: str, starts: list[Callable[[], tuple[Future, str]]],
                         combine: Callable[[list], Any],
                         cacheable: Callable[[Any], bool] | None = None) -> tuple[Future, str]:
        """Fan out sub-tasks (each itself cached) and combine; the combination is cached too."""
        return self.cache.submit(
            key, lambda: gather_futures([s()[0] for s in starts], combine), cacheable)

    def stats(self) -> dict:
        return {"mode": self.mode, "workers": self.workers, "started": self.started,
                "fallbackReason": self.fallback_reason, "cache": self.cache.stats()}


# --------------------------------------------------------------------------
# Jobs
# --------------------------------------------------------------------------
@dataclass
class Plan:
    """A validated, keyed unit of work (built by the API layer)."""
    kind: str
    params: dict
    key: str
    start: Callable[[], tuple[Future, str]]     # cache-aware submission
    tags: list[tuple[str, dict]] = field(default_factory=list)  # progress keys + annotations


class QueueFull(Exception):
    pass


@dataclass
class Job:
    id: str
    plan: Plan
    status: str = "queued"
    created: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None
    cache: str | None = None
    result: Any = None
    error: str | None = None
    stages: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    seq: int = 0
    subscribers: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = field(default_factory=list)
    listeners: list[tuple[str, Callable]] = field(default_factory=list)

    def snapshot(self, include_result: bool = True) -> dict:
        now = time.time()
        out = {
            "job_id": self.id, "kind": self.plan.kind, "params": self.plan.params,
            "status": self.status, "cache": self.cache,
            "createdAt": self.created, "startedAt": self.started, "finishedAt": self.finished,
            "queueSeconds": round((self.started or now) - self.created, 4)
            if self.status != "cancelled" else None,
            "runSeconds": round((self.finished or now) - self.started, 4) if self.started else None,
            "stages": list(self.stages),
            "error": self.error,
        }
        if include_result:
            out["result"] = self.result if self.status == "done" else None
        return out


class JobRegistry:
    MAX_EVENTS = 1000

    def __init__(self, service: ComputeService, max_running: int | None = None,
                 max_jobs: int | None = None, max_queued: int | None = None):
        self.service = service
        self.max_running = max_running or service.workers
        self.max_jobs = max_jobs or int(os.environ.get("ALO_MAX_JOBS", 128))
        self.max_queued = max_queued or int(os.environ.get("ALO_MAX_QUEUED", 64))
        self._lock = threading.RLock()   # future callbacks may fire inline while held
        self._jobs: OrderedDict[str, Job] = OrderedDict()
        self._active: dict[str, str] = {}             # provenance key -> job id
        self._queue: deque[str] = deque()
        self._running = 0

    # -- public -----------------------------------------------------------
    def submit(self, plan: Plan) -> tuple[Job, bool]:
        """(job, deduplicated). Raises QueueFull when the waiting queue is full."""
        with self._lock:
            jid = self._active.get(plan.key)
            if jid is not None:
                return self._jobs[jid], True
            hit, value = self.service.cache.peek(plan.key)
            if not hit and len(self._queue) >= self.max_queued:
                raise QueueFull(f"{len(self._queue)} jobs already queued")
            job = Job(uuid.uuid4().hex, plan)
            self._jobs[job.id] = job
            self._publish(job, "status", {"status": "queued"})
            if hit:                             # served from cache: done immediately
                job.started = job.created
                job.cache = "hit"
                self._finish_locked(job, value, None)
            else:
                self._active[plan.key] = job.id
                self._queue.append(job.id)
                self._pump_locked()
            self._evict_locked()
            return job, False

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[dict]:
        with self._lock:
            return [j.snapshot(include_result=False) for j in reversed(self._jobs.values())]

    def cancel(self, job_id: str) -> tuple[Job | None, bool]:
        """(job, cancelled). Only queued jobs can be cancelled."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status != "queued":
                return job, False
            self._queue.remove(job.id)
            self._active.pop(job.plan.key, None)
            job.status, job.finished = "cancelled", time.time()
            self._publish(job, "status", {"status": "cancelled"})
            return job, True

    def counts(self) -> dict:
        with self._lock:
            c: dict[str, int] = {}
            for j in self._jobs.values():
                c[j.status] = c.get(j.status, 0) + 1
            return {"total": len(self._jobs), "maxJobs": self.max_jobs,
                    "maxRunning": self.max_running, **c}

    def subscribe(self, job_id: str, loop: asyncio.AbstractEventLoop):
        """(past events, queue) atomically, or None for an unknown job."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            q: asyncio.Queue = asyncio.Queue()
            if job.status not in TERMINAL:
                job.subscribers.append((loop, q))
            return list(job.events), q

    def unsubscribe(self, job_id: str, q: asyncio.Queue) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.subscribers = [s for s in job.subscribers if s[1] is not q]

    # -- internals --------------------------------------------------------
    def _publish(self, job: Job, etype: str, data: dict) -> None:
        job.seq += 1
        ev = {"id": job.seq, "type": etype, "data": {"job_id": job.id, **data}}
        if len(job.events) < self.MAX_EVENTS or etype == "status":
            job.events.append(ev)
        alive = []
        for loop, q in job.subscribers:
            try:
                loop.call_soon_threadsafe(q.put_nowait, ev)
                alive.append((loop, q))
            except RuntimeError:               # subscriber's loop is gone
                pass
        job.subscribers = alive

    def _pump_locked(self) -> None:
        while self._queue and self._running < self.max_running:
            self._launch_locked(self._jobs[self._queue.popleft()])

    def _launch_locked(self, job: Job) -> None:
        job.status, job.started = "running", time.time()
        self._running += 1
        self._publish(job, "status", {"status": "running"})
        for tag, extra in job.plan.tags:
            cb = self._progress_cb(job, extra)
            job.listeners.append((tag, cb))
            self.service.listen(tag, cb)
        try:
            fut, how = job.plan.start()
        except Exception as e:                 # noqa: BLE001 - submission failure is a job error
            self._finish_locked(job, None, e)
            return
        job.cache = how
        fut.add_done_callback(lambda f: self._on_done(job, f))

    def _progress_cb(self, job: Job, extra: dict) -> Callable:
        def cb(event: str, data: dict) -> None:
            with self._lock:
                if job.status != "running":
                    return
                payload = {"event": event, **data, **extra}
                if event == "stage":
                    job.stages.append({k: v for k, v in payload.items() if k != "event"})
                self._publish(job, "progress", payload)
        return cb

    def _on_done(self, job: Job, fut: Future) -> None:
        with self._lock:
            if fut.cancelled():
                self._finish_locked(job, None, RuntimeError("computation cancelled"))
            else:
                self._finish_locked(job, fut.result() if fut.exception() is None else None,
                                    fut.exception())
            self._pump_locked()

    def _finish_locked(self, job: Job, result: Any, err: BaseException | None) -> None:
        if job.status == "running":
            self._running -= 1
        for tag, cb in job.listeners:
            self.service.unlisten(tag, cb)
        job.listeners.clear()
        if self._active.get(job.plan.key) == job.id:
            del self._active[job.plan.key]
        job.finished = time.time()
        if err is None:
            job.status, job.result = "done", result
        else:
            job.status, job.error = "error", f"{type(err).__name__}: {err}"
        self._publish(job, "status", {"status": job.status, "cache": job.cache,
                                      "error": job.error,
                                      "runSeconds": round(job.finished - (job.started or job.created), 4)})
        job.subscribers = []

    def _evict_locked(self) -> None:
        excess = len(self._jobs) - self.max_jobs
        if excess <= 0:
            return
        for jid in [j.id for j in self._jobs.values() if j.status in TERMINAL][:excess]:
            del self._jobs[jid]
