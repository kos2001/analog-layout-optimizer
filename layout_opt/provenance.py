"""Provenance keys + a bounded result cache with in-flight sharing.

Every flow result is a pure function of (what was asked, which code ran,
which external tools were visible). ``digest`` turns any JSON-like request into
a stable sha256 over canonical JSON, and ``cache_key`` adds the code version so
a result computed by an older engine is never served for a newer one.

``ResultCache`` is the server-side half: a thread-safe LRU whose misses are
*shared* — N concurrent identical requests run the computation once and all
wait on the same ``concurrent.futures.Future`` (usable from plain threads via
``.result()`` and from asyncio via ``asyncio.wrap_future``). A failed or
cancelled computation is evicted, never cached, so the next request retries.

    cache = ResultCache(maxsize=128)
    value = cache.get_or_compute(key, lambda: expensive())        # sync, inline
    fut, how = cache.submit(key, lambda: pool.submit(fn, *args))   # async / pooled

Cached values are shared between callers: treat them as immutable (copy
before mutating).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import shutil
import threading
from collections import OrderedDict
from concurrent.futures import Future
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

_PKG_DIR = Path(__file__).resolve().parent


# --------------------------------------------------------------------------
# Canonical digests
# --------------------------------------------------------------------------
def _default(o: Any) -> Any:
    """JSON fallback for non-JSON values; deterministic for the common cases."""
    if isinstance(o, (set, frozenset)):
        return sorted(o, key=canonical_json)
    if dataclasses.is_dataclass(o) and not isinstance(o, type):
        return dataclasses.asdict(o)
    if hasattr(o, "tolist"):                   # numpy arrays and scalars
        return o.tolist()
    return str(o)


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=_default)


def digest(obj: Any) -> str:
    """sha256 hex of the canonical JSON encoding of ``obj``."""
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def file_digest(*paths: str | Path) -> str:
    """Content hash over files (path-name + bytes); missing files hash as absent."""
    h = hashlib.sha256()
    for p in sorted(Path(x) for x in paths):
        h.update(p.name.encode())
        try:
            h.update(hashlib.sha256(p.read_bytes()).digest())
        except OSError:
            h.update(b"<missing>")
    return h.hexdigest()


@lru_cache(maxsize=1)
def code_version() -> str:
    """Hash of the layout_opt sources as loaded by *this* process.

    Content hashes (not git HEAD) so uncommitted edits change the key, and
    cached per process because a running process keeps executing the code it
    imported at startup — exactly what produced its results. ~1 ms once.
    """
    return file_digest(*_PKG_DIR.glob("*.py"))[:16]


def tool_fingerprint() -> dict:
    """External tools/PDK visible to the engine; results that shell out depend on them."""
    return {
        "PDK_ROOT": os.environ.get("PDK_ROOT", ""),
        **{t: shutil.which(t) or "" for t in ("ngspice", "spectre", "klayout")},
    }


def cache_key(kind: str, params: Any, *, version: str | None = None,
              env: dict | None = None) -> str:
    return digest({"kind": kind, "params": params,
                   "code": version or code_version(), "env": env or {}})


# --------------------------------------------------------------------------
# Bounded LRU with in-flight sharing
# --------------------------------------------------------------------------
class ResultCache:
    """Thread-safe LRU of finished results + registry of in-flight futures."""

    def __init__(self, maxsize: int = 128):
        if maxsize < 0:
            raise ValueError("maxsize must be >= 0")
        self.maxsize = maxsize
        self._lock = threading.RLock()       # start() may re-enter (composite jobs)
        self._done: OrderedDict[str, Any] = OrderedDict()
        self._inflight: dict[str, Future] = {}
        self.hits = self.misses = self.shared = self.errors = 0

    # -- inspection -------------------------------------------------------
    def peek(self, key: str) -> tuple[bool, Any]:
        """(True, value) on a finished hit (refreshes LRU order), else (False, None)."""
        with self._lock:
            if key in self._done:
                self._done.move_to_end(key)
                return True, self._done[key]
        return False, None

    def inflight(self, key: str) -> Future | None:
        with self._lock:
            return self._inflight.get(key)

    def stats(self) -> dict:
        with self._lock:
            return {"size": len(self._done), "maxsize": self.maxsize,
                    "inflight": len(self._inflight), "hits": self.hits,
                    "misses": self.misses, "shared": self.shared, "errors": self.errors}

    def clear(self) -> None:
        with self._lock:
            self._done.clear()

    # -- core -------------------------------------------------------------
    def submit(self, key: str, start: Callable[[], Future],
               cacheable: Callable[[Any], bool] | None = None) -> tuple[Future, str]:
        """Return (future, how) with how in {"hit", "shared", "miss"}.

        On a miss ``start()`` must return a Future for the computation (e.g.
        ``executor.submit(...)``); it is registered as in-flight so concurrent
        identical requests share it. ``cacheable(result)`` may veto storing a
        result (e.g. a transient "tool unavailable" answer). ``start`` runs
        under the cache lock (two identical misses can never both start) and
        may itself call ``submit`` for sub-tasks.
        """
        with self._lock:
            if key in self._done:
                self._done.move_to_end(key)
                self.hits += 1
                fut: Future = Future()
                fut.set_result(self._done[key])
                return fut, "hit"
            if key in self._inflight:
                self.shared += 1
                return self._inflight[key], "shared"
            fut = start()                      # may raise: nothing registered then
            self._inflight[key] = fut
            self.misses += 1
        # Outside the lock: an already-finished future runs the callback inline.
        fut.add_done_callback(lambda f: self._settle(key, f, cacheable))
        return fut, "miss"

    def get_or_compute(self, key: str, fn: Callable[[], Any],
                       cacheable: Callable[[Any], bool] | None = None) -> Any:
        """Synchronous form: compute inline on a miss, wait on a shared one."""
        own: Future = Future()
        fut, how = self.submit(key, lambda: own, cacheable)
        if how == "miss":
            try:
                own.set_result(fn())
            except BaseException as e:         # noqa: BLE001 - propagated to every waiter
                own.set_exception(e)
        return fut.result()

    def _settle(self, key: str, fut: Future, cacheable) -> None:
        with self._lock:
            if self._inflight.get(key) is fut:
                del self._inflight[key]
            if fut.cancelled() or fut.exception() is not None:
                self.errors += 1
                return                         # evict on error: next caller retries
            value = fut.result()
            if self.maxsize == 0 or (cacheable is not None and not cacheable(value)):
                return
            self._done[key] = value
            self._done.move_to_end(key)
            while len(self._done) > self.maxsize:
                self._done.popitem(last=False)
