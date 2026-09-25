"""Long-running stability (US-37): hourly self-monitoring, the last-resort safety valve, leak tools.

Everything that collects numbers is pure and reads /proc (unit-tested without gi). Only HealthMonitor
touches GLib, and it imports it lazily.

The hourly INFO line (the format is a contract for scripts/soak-analyze.py and US-31):

    health: rss=87.3MB fds=23 threads=3 sources=9 sync_procs=0 db=1.2MB wal=0.1MB journal=18MB uptime=3d04h

Dev-only hooks, all off unless their environment variable is set (never in normal operation):
    CALPI_LEAKCHECK=1   tracemalloc (25 frames) from the start of main(); SIGUSR2 logs the top 30
                        allocation diffs since the last snapshot plus the top 30 object types
    CALPI_SOAK=1        calpi.devtools.soak drives speeded-up activity (see that module)
    CALPI_HEALTH_SIGNAL=1   SIGUSR2 logs one health line without the other hooks
"""
from __future__ import annotations

import collections
import gc
import logging
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime

log = logging.getLogger("calpi.health")

INTERVAL_S = 3600
FIRST_SAMPLE_S = 60
EXIT_CODE_RESTART = 75            # EX_TEMPFAIL: systemd's Restart=always brings the app back

RSS_LIMIT_MB = 350.0              # acted on only inside the night window ...
FDS_LIMIT = 500
RSS_EMERGENCY_MB = 450.0          # ... unless RSS goes over this: then straight away
NIGHT_START_H, NIGHT_END_H = 2, 5

_START = time.monotonic()
_PAGE = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096


@dataclass
class HealthSample:
    rss_mb: float
    fds: int
    threads_py: int
    threads_os: int
    sources: int
    sync_procs: int
    db_mb: float
    wal_mb: float
    journal_mb: float | None
    uptime_s: float
    zombies: int = 0


# ---------------------------------------------------------------- collection (pure, /proc)
def read_rss_mb(pid: str | int = "self") -> float:
    """Resident set: /proc/<pid>/statm field 2 x page size."""
    try:
        with open(f"/proc/{pid}/statm") as f:
            return int(f.read().split()[1]) * _PAGE / (1024 * 1024)
    except (OSError, ValueError, IndexError):
        return 0.0


def count_fds() -> int:
    try:
        return len(os.listdir("/proc/self/fd"))
    except OSError:
        return 0


def os_threads() -> int:
    """Native threads (GTK/GLib/Python): /proc/self/status `Threads:`."""
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("Threads:"):
                    return int(line.split()[1])
    except (OSError, ValueError):
        pass
    return 0


def child_processes(pid: int | None = None) -> tuple[int, int]:
    """(children, zombies) of this process: scan /proc/*/stat for ppid == pid."""
    me = pid if pid is not None else os.getpid()
    kids = zombies = 0
    try:
        names = os.listdir("/proc")
    except OSError:
        return 0, 0
    for name in names:
        if not name.isdigit():
            continue
        try:
            with open(f"/proc/{name}/stat") as f:
                data = f.read()
            rest = data[data.rindex(")") + 2:].split()
            state, ppid = rest[0], int(rest[1])
        except (OSError, ValueError, IndexError):
            continue
        if ppid == me:
            kids += 1
            if state == "Z":
                zombies += 1
    return kids, zombies


def file_mb(path) -> float:
    try:
        return os.stat(path).st_size / (1024 * 1024)
    except OSError:
        return 0.0


def db_sizes() -> tuple[float, float]:
    """(db MB, wal MB) of the UI's database."""
    from calpi.data import db
    p = str(db.default_path())
    return file_mb(p), file_mb(p + "-wal")


_JOURNAL_RE = re.compile(r"take up\s+([\d.]+)\s*([KMGT]?)", re.I)


def parse_journal_usage(text: str) -> float | None:
    """`journalctl --disk-usage` -> MB. 'Archived and active journals take up 18.0M in the file system.'"""
    m = _JOURNAL_RE.search(text or "")
    if not m:
        return None
    mult = {"": 1 / (1024 * 1024), "K": 1 / 1024, "M": 1.0, "G": 1024.0, "T": 1024.0 * 1024}[m.group(2).upper()]
    return float(m.group(1)) * mult


def read_journal_mb(timeout: float = 15.0) -> float | None:
    """Blocking (a subprocess): call from a worker thread only."""
    try:
        r = subprocess.run(["journalctl", "--disk-usage"], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return parse_journal_usage(r.stdout + r.stderr) if r.returncode == 0 else None


def periodic_source_count() -> int:
    try:
        from calpi import tasks
        return len(tasks.periodic_sources())
    except Exception:            # no gi (unit tests of the pure parts)
        return 0


def sample(journal_mb: float | None = None) -> HealthSample:
    db_mb, wal_mb = db_sizes()
    kids, zombies = child_processes()
    return HealthSample(
        rss_mb=read_rss_mb(), fds=count_fds(), threads_py=threading.active_count(),
        threads_os=os_threads(), sources=periodic_source_count(), sync_procs=kids,
        db_mb=db_mb, wal_mb=wal_mb, journal_mb=journal_mb, uptime_s=time.monotonic() - _START,
        zombies=zombies)


# ---------------------------------------------------------------- formatting / parsing
def format_uptime(seconds: float) -> str:
    s = int(seconds)
    d, rem = divmod(s, 86400)
    return f"{d}d{rem // 3600:02d}h"


def parse_uptime(text: str) -> float:
    m = re.fullmatch(r"(\d+)d(\d+)h", text)
    return int(m.group(1)) * 86400 + int(m.group(2)) * 3600 if m else 0.0


def format_line(s: HealthSample) -> str:
    journal = "n/a" if s.journal_mb is None else f"{s.journal_mb:.0f}MB"
    return (f"health: rss={s.rss_mb:.1f}MB fds={s.fds} threads={s.threads_os} sources={s.sources} "
            f"sync_procs={s.sync_procs} db={s.db_mb:.1f}MB wal={s.wal_mb:.1f}MB journal={journal} "
            f"uptime={format_uptime(s.uptime_s)}")


_LINE_RE = re.compile(r"health: rss=(?P<rss>[\d.]+)MB fds=(?P<fds>\d+) threads=(?P<threads>\d+) "
                      r"sources=(?P<sources>\d+) sync_procs=(?P<sync_procs>\d+) db=(?P<db>[\d.]+)MB "
                      r"wal=(?P<wal>[\d.]+)MB journal=(?P<journal>[\d.]+MB|n/a) uptime=(?P<uptime>\d+d\d+h)")


def parse_line(text: str) -> dict | None:
    """Inverse of format_line (numbers only); None if the text is not a health line."""
    m = _LINE_RE.search(text)
    if not m:
        return None
    g = m.groupdict()
    return {"rss_mb": float(g["rss"]), "fds": int(g["fds"]), "threads": int(g["threads"]),
            "sources": int(g["sources"]), "sync_procs": int(g["sync_procs"]),
            "db_mb": float(g["db"]), "wal_mb": float(g["wal"]),
            "journal_mb": None if g["journal"] == "n/a" else float(g["journal"][:-2]),
            "uptime_s": parse_uptime(g["uptime"])}


# ---------------------------------------------------------------- the safety valve (pure)
def check_limits(s: HealthSample, now_local: datetime) -> str | None:
    """Acceptance criterion 4. Returns the reason to restart, or None.

    RSS > 350 MB or fds > 500: only between 02:00 and 05:00 local time.
    RSS > 450 MB: at once.
    """
    if s.rss_mb > RSS_EMERGENCY_MB:
        return f"rss={s.rss_mb:.0f}MB > {RSS_EMERGENCY_MB:.0f}MB"
    over = []
    if s.rss_mb > RSS_LIMIT_MB:
        over.append(f"rss={s.rss_mb:.0f}MB > {RSS_LIMIT_MB:.0f}MB")
    if s.fds > FDS_LIMIT:
        over.append(f"fds={s.fds} > {FDS_LIMIT}")
    if over and NIGHT_START_H <= now_local.hour < NIGHT_END_H:
        return ", ".join(over)
    return None


# ---------------------------------------------------------------- leak tools (dev)
def leakcheck_enabled() -> bool:
    return os.environ.get("CALPI_LEAKCHECK") == "1"


def start_leakcheck() -> None:
    """Call as early as possible in main(): tracemalloc with 25 frames (dev only)."""
    if leakcheck_enabled():
        import tracemalloc
        tracemalloc.start(25)
        log.warning("health: CALPI_LEAKCHECK on (tracemalloc, 25 frames): dev only, slower and bigger")


class LeakTools:
    def __init__(self):
        self._prev = None

    def snapshot_lines(self, top: int = 30) -> list[str]:
        import tracemalloc
        if not tracemalloc.is_tracing():
            return ["leak: tracemalloc is not running (set CALPI_LEAKCHECK=1)"]
        cur = tracemalloc.take_snapshot().filter_traces(
            (tracemalloc.Filter(False, tracemalloc.__file__), tracemalloc.Filter(False, "<frozen importlib._bootstrap>")))
        lines = []
        if self._prev is None:
            lines.append("leak: first snapshot taken (diffs start with the next signal)")
        else:
            lines.append(f"leak: top {top} allocation diffs since the previous snapshot")
            for st in cur.compare_to(self._prev, "lineno")[:top]:
                lines.append(f"leak:   {st}")
        self._prev = cur
        return lines


def object_census(top: int = 30) -> list[tuple[str, int]]:
    return collections.Counter(type(o).__name__ for o in gc.get_objects()).most_common(top)


# ---------------------------------------------------------------- the GLib part
class HealthMonitor:
    """Hourly timer (+ one sample 60 s after start), SIGUSR2 in dev, safety valve action."""

    def __init__(self, app, now=None):
        self.app = app
        self._now = now or datetime.now
        self._leaks = LeakTools()
        self._journal_mb: float | None = None
        self._busy = False
        self.last: HealthSample | None = None

    def start(self) -> None:
        from gi.repository import GLib
        from calpi import tasks
        tasks.add_periodic_seconds("health", INTERVAL_S,
                                   tasks.safe_callback(lambda: self.sample_async("hourly") or True, repeat=True))
        GLib.timeout_add_seconds(FIRST_SAMPLE_S, tasks.safe_callback(lambda: self.sample_async("startup"),
                                                                     repeat=False))
        if leakcheck_enabled() or os.environ.get("CALPI_SOAK") == "1" or os.environ.get("CALPI_HEALTH_SIGNAL") == "1":
            import signal
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR2, self._on_usr2)

    def _on_usr2(self):
        log.info("health: SIGUSR2")
        self.sample_async("signal")
        if leakcheck_enabled():
            self.log_leak_report()
        from gi.repository import GLib
        return GLib.SOURCE_CONTINUE

    def log_leak_report(self) -> None:
        for line in self._leaks.snapshot_lines():
            log.info(line)
        log.info("leak: top python object types: %s",
                 ", ".join(f"{n}={c}" for n, c in object_census()))

    def sample_async(self, why: str = "hourly") -> None:
        """Read the journal size in a worker (a subprocess), then log the line on the main thread."""
        if self._busy:
            return
        self._busy = True
        from calpi.tasks import run_in_thread
        run_in_thread(read_journal_mb, on_done=lambda mb: self._emit(mb, why),
                      on_error=lambda _e: self._emit(None, why), name="health-journal")

    def _emit(self, journal_mb: float | None, why: str) -> None:
        self._busy = False
        if journal_mb is not None:
            self._journal_mb = journal_mb
        s = sample(self._journal_mb)
        self.last = s
        log.info(format_line(s))
        from calpi import tasks
        log.debug("health: %s threads_py=%d zombies=%d periodic=%s", why, s.threads_py, s.zombies,
                  sorted(tasks.periodic_sources()))
        reason = check_limits(s, self._now())
        if reason:
            self.trip(reason)

    def trip(self, reason: str) -> None:
        """Last resort: exit with code 75 and let systemd restart us. Must never fire in the soak."""
        log.error("health: resource limit exceeded (%s), restarting", reason)
        try:
            from calpi import watchdog
            watchdog.stopping()
        except Exception:
            pass
        self.app.exit_code = EXIT_CODE_RESTART
        self.app.quit()


def install(app) -> HealthMonitor:
    mon = HealthMonitor(app)
    mon.start()
    return mon
