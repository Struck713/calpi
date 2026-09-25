"""Performance instrumentation (US-36). One place for every measurement.

    with perf.span("name"): ...                 # synchronous work, milliseconds
    perf.until_paint("name", widget, t0=None)   # time from t0 until the next frame is painted
    perf.report() -> {name: {n, p50, p90, max, ...}}

Samples live in bounded deques (US-37: no growth over weeks). Logging is DEBUG, or INFO with CALPI_PERF=1.
The pure parts (record/stats/report/since_boot) need no gi; only until_paint touches GTK objects.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from collections import defaultdict, deque
from contextlib import contextmanager

log = logging.getLogger("calpi.perf")

MAX_SAMPLES = 500
NO_PAINT_TIMEOUT_MS = 500

_samples: dict[str, deque] = defaultdict(lambda: deque(maxlen=MAX_SAMPLES))
_counts: dict[str, int] = defaultdict(int)          # total ever recorded (deque is bounded)
_no_paint: dict[str, int] = defaultdict(int)
_lock = threading.Lock()
_listeners: list = []                                # bench driver hooks: fn(name, ms)


def _level() -> int:
    return logging.INFO if os.environ.get("CALPI_PERF") == "1" else logging.DEBUG


def record(name: str, ms: float) -> None:
    with _lock:
        _samples[name].append(ms)
        _counts[name] += 1
    log.log(_level(), "perf: %s %.1f ms", name, ms)
    for fn in list(_listeners):
        try:
            fn(name, ms)
        except Exception:
            log.exception("perf listener failed")


def add_listener(fn) -> None:
    _listeners.append(fn)


def remove_listener(fn) -> None:
    if fn in _listeners:
        _listeners.remove(fn)


def record_no_paint(name: str) -> None:
    with _lock:
        _no_paint[name] += 1
    log.log(_level(), "perf: %s no-paint", name)


@contextmanager
def span(name: str):
    t = time.perf_counter()
    try:
        yield
    finally:
        record(name, (time.perf_counter() - t) * 1000)


def until_paint(name: str, widget, t0: float | None = None, timeout_ms: int = NO_PAINT_TIMEOUT_MS) -> None:
    """Record time from t0 (perf_counter; default now) to the next painted frame of widget's window.

    If nothing is painted within timeout_ms (nothing changed on screen) a no-paint is counted instead.
    Never raises: measurement must not break the UI.
    """
    if t0 is None:
        t0 = time.perf_counter()
    try:
        from gi.repository import GLib
        target = widget
        clock = target.get_frame_clock()
        if clock is None:
            root = target.get_root()
            clock = root.get_frame_clock() if root is not None else None
        if clock is None:
            record_no_paint(name)
            return
        state = {"hid": None, "src": None, "done": False}

        def finish(painted: bool):
            if state["done"]:
                return
            state["done"] = True
            try:
                if state["hid"] is not None:
                    clock.disconnect(state["hid"])
            except Exception:
                pass
            if state["src"] is not None and painted:
                GLib.source_remove(state["src"])
            if painted:
                record(name, (time.perf_counter() - t0) * 1000)
            else:
                record_no_paint(name)

        def on_paint(_c):
            finish(True)

        def on_timeout():
            state["src"] = None
            finish(False)
            return GLib.SOURCE_REMOVE

        state["hid"] = clock.connect("after-paint", on_paint)
        state["src"] = GLib.timeout_add(timeout_ms, on_timeout)
    except Exception:
        log.exception("perf.until_paint(%s) failed", name)


_PROFILE = os.environ.get("CALPI_PROFILE", "")
_profilers: dict = {}


@contextmanager
def profiled(name: str):
    """Dev: with CALPI_PROFILE=<name> accumulate cProfile stats and dump them to /tmp/calpi-<name>.pstats
    (every 20 calls). A no-op otherwise."""
    if _PROFILE != name:
        yield
        return
    import cProfile
    pr = _profilers.get(name)
    if pr is None:
        pr = _profilers[name] = [cProfile.Profile(), 0]
    pr[0].enable()
    try:
        yield
    finally:
        pr[0].disable()
        pr[1] += 1
        if pr[1] % 20 == 0:
            pr[0].dump_stats(f"/tmp/calpi-{name}.pstats")
            log.info("perf: profile written to /tmp/calpi-%s.pstats", name)


def percentile(sorted_vals: list[float], q: float) -> float:
    """Nearest-rank percentile on a sorted list (q in 0..100)."""
    if not sorted_vals:
        return 0.0
    k = max(0, min(len(sorted_vals) - 1, int(-(-q * len(sorted_vals) // 100)) - 1))
    return sorted_vals[k]


def stats(name: str, skip: int = 0) -> dict:
    """n, p50, p90, max, min (ms) for the stored samples, ignoring the first `skip` (warm-up)."""
    with _lock:
        vals = list(_samples.get(name, ()))[skip:]
        np_ = _no_paint.get(name, 0)
    vals.sort()
    out = {"n": len(vals), "p50": round(percentile(vals, 50), 1), "p90": round(percentile(vals, 90), 1),
           "max": round(vals[-1], 1) if vals else 0.0, "min": round(vals[0], 1) if vals else 0.0}
    if np_:
        out["no_paint"] = np_
    return out


def report() -> dict:
    with _lock:
        names = sorted(set(_samples) | set(_no_paint))
    return {n: stats(n) for n in names}


def reset() -> None:
    with _lock:
        _samples.clear()
        _counts.clear()
        _no_paint.clear()


def since_boot_ms() -> float:
    return time.clock_gettime(time.CLOCK_BOOTTIME) * 1000


def process_start_since_boot_ms() -> float | None:
    """Process start time in ms since boot (/proc/self/stat field 22, clock ticks)."""
    try:
        with open("/proc/self/stat") as f:
            data = f.read()
        fields = data[data.rindex(")") + 2:].split()      # after "pid (comm) "; fields[0] is state (field 3)
        ticks = int(fields[19])                           # field 22
        return ticks * 1000.0 / os.sysconf("SC_CLK_TCK")
    except (OSError, ValueError, IndexError):
        return None


def mark_first_paint(name_start: str, name_boot: str, widget, also_start: str | None = None) -> None:
    """Startup marks: process start -> now and boot -> now, when widget paints its first frame."""
    start = process_start_since_boot_ms()
    try:
        clock = widget.get_frame_clock()
        if clock is None:
            return
        hid = []

        def on_paint(c):
            c.disconnect(hid[0])
            now = since_boot_ms()
            if start is not None:
                record(name_start, now - start)
                if also_start:
                    record(also_start, now - start)
            record(name_boot, now)
        hid.append(clock.connect("after-paint", on_paint))
        clock.request_phase(__import__("gi.repository.Gdk", fromlist=["Gdk"]).FrameClockPhase.PAINT)
    except Exception:
        log.exception("perf.mark_first_paint failed")


def cpu_ticks(pid: int | str = "self") -> int | None:
    """utime+stime in clock ticks for a process (idle CPU sampling)."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            data = f.read()
        fields = data[data.rindex(")") + 2:].split()
        return int(fields[11]) + int(fields[12])
    except (OSError, ValueError, IndexError):
        return None


def rss_mb(pid: int | str = "self") -> float | None:
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
    except (OSError, ValueError):
        pass
    return None
