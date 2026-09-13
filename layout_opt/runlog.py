"""Per-stage runtime / memory accounting for flow runs.

Flow code marks its stages with ``with stage("routing"):``. Outside a
``Profiler`` that is a no-op, so library and web callers pay nothing; the batch
runner (``python -m layout_opt flow``) activates a Profiler and prints the
familiar EDA-tool resource summary (wall, CPU, peak RSS per stage).
"""

from __future__ import annotations

import resource
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass

_active: list["Profiler"] = []


def peak_rss_mb() -> float:
    """Process peak resident set size in MB (ru_maxrss is bytes on macOS, KB on Linux)."""
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return rss / (1024 * 1024) if sys.platform == "darwin" else rss / 1024


def _cpu_s() -> float:
    ru = resource.getrusage(resource.RUSAGE_SELF)
    return ru.ru_utime + ru.ru_stime


@dataclass
class StageStat:
    name: str
    calls: int = 0
    wall_s: float = 0.0
    cpu_s: float = 0.0
    peak_rss_mb: float = 0.0


class Profiler:
    """Collects StageStats for every ``stage()`` entered while it is active.

    Nested stages are recorded independently (a parent's time includes its
    children); repeated stages — e.g. one per seed in a sweep — accumulate.
    """

    def __init__(self, on_stage=None):
        self.stats: dict[str, StageStat] = {}
        self.on_stage = on_stage          # callback(StageStat, wall_s) after each stage

    def __enter__(self) -> "Profiler":
        _active.append(self)
        return self

    def __exit__(self, *exc) -> None:
        _active.remove(self)

    def record(self, name: str, wall: float, cpu: float) -> None:
        st = self.stats.setdefault(name, StageStat(name))
        st.calls += 1
        st.wall_s += wall
        st.cpu_s += cpu
        st.peak_rss_mb = max(st.peak_rss_mb, peak_rss_mb())
        if self.on_stage is not None:
            self.on_stage(st, wall)


@contextmanager
def stage(name: str):
    if not _active:
        yield
        return
    t0, c0 = time.perf_counter(), _cpu_s()
    try:
        yield
    finally:
        wall, cpu = time.perf_counter() - t0, _cpu_s() - c0
        for prof in list(_active):
            prof.record(name, wall, cpu)
