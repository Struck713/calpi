"""Crash-loop detection (US-12 D4). No gi imports.

One line per start (Unix time) in <runtime_dir>/starts. The runtime dir is tmpfs and survives
service restarts (RuntimeDirectoryPreserve=yes) but not reboots.
"""
from __future__ import annotations

import logging
import time

from calpi import paths
from calpi.data.atomic import atomic_write_bytes

log = logging.getLogger("calpi.crashguard")

WINDOW_S = 600
THRESHOLD = 4          # >= 4 earlier starts inside the window -> safe mode
STABLE_S = 600


def _file():
    return paths.runtime_dir() / "starts"


def record_start_and_check(now: float | None = None) -> bool:
    """Record this start; return True if this start should run in safe mode."""
    now = time.time() if now is None else now
    f = _file()
    try:
        prev = [float(x) for x in f.read_text().split() if x.strip()]
    except (OSError, ValueError):
        prev = []
    recent = [t for t in prev if 0 <= now - t < WINDOW_S]
    try:
        atomic_write_bytes(f, ("\n".join(repr(t) for t in recent + [now]) + "\n").encode(), mode=0o600)
    except OSError:
        log.warning("crashguard: cannot write %s", f, exc_info=True)
    safe = len(recent) >= THRESHOLD
    if safe:
        log.warning("SAFE MODE: %d starts in %d min", len(recent), WINDOW_S // 60)
    return safe


def mark_stable() -> None:
    try:
        _file().write_text("")
    except OSError:
        pass


def test_crash_point(kind: str, safe_mode: bool) -> None:
    """Dev/test hook: CALPI_TEST_CRASH=<kind> raises SystemExit(1) at that point.

    'render' (data-triggered crash) is skipped in safe mode; 'start' is not, on purpose.
    """
    import os
    if os.environ.get("CALPI_TEST_CRASH") != kind:
        return
    if kind == "render" and safe_mode:
        return
    logging.getLogger("calpi").critical("CALPI_TEST_CRASH=%s: crashing on purpose", kind)
    raise SystemExit(1)
