"""Inactivity detection: pure InactivityTracker plus the GTK InactivityMonitor."""
from __future__ import annotations

import logging
import time
from typing import Callable

log = logging.getLogger("calpi.inactivity")

DEFAULT_RETURN_SECONDS = 120


class InactivityTracker:
    """Pure logic. `clock` returns monotonic seconds (injectable for tests)."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._last = clock()
        self._listeners: dict[int, list] = {}      # handle -> [seconds, callback, fired]
        self._next = 1

    def touch(self) -> None:
        self._last = self._clock()
        for entry in self._listeners.values():
            entry[2] = False                         # re-arm

    def idle_seconds(self) -> float:
        return self._clock() - self._last

    def add(self, seconds: float, callback: Callable[[], None]) -> int:
        h = self._next
        self._next += 1
        self._listeners[h] = [seconds, callback, False]
        return h

    def remove(self, handle: int) -> None:
        self._listeners.pop(handle, None)

    def set_timeout(self, handle: int, seconds: float) -> None:
        if handle in self._listeners:
            self._listeners[handle][0] = seconds

    def check(self) -> None:
        idle = self.idle_seconds()
        for entry in list(self._listeners.values()):
            seconds, cb, fired = entry
            if not fired and idle >= seconds:
                entry[2] = True
                try:
                    cb()
                except Exception:
                    log.exception("inactivity callback failed")


class InactivityMonitor:
    """Watches all window input through the WindowEventHub (US-11); one coarse timer."""
    CHECK_INTERVAL_S = 5

    def __init__(self, hub):
        from gi.repository import Gdk, GLib
        from calpi.tasks import safe_callback
        self.tracker = InactivityTracker()
        names = ("MOTION_NOTIFY", "BUTTON_PRESS", "BUTTON_RELEASE", "TOUCH_BEGIN",
                 "TOUCH_UPDATE", "TOUCH_END", "KEY_PRESS", "SCROLL")
        self._activity = {getattr(Gdk.EventType, n) for n in names if hasattr(Gdk.EventType, n)}
        hub.event_hooks.append(self._on_event)
        from calpi import tasks
        tasks.add_periodic_seconds("inactivity", self.CHECK_INTERVAL_S,
                                   safe_callback(self.tracker.check, repeat=True))

    def _on_event(self, event) -> None:
        if event.get_event_type() in self._activity:
            self.tracker.touch()

    def add_idle_callback(self, seconds: float, cb: Callable[[], None]) -> int:
        return self.tracker.add(seconds, cb)

    def remove(self, handle: int) -> None:
        self.tracker.remove(handle)

    def poke(self) -> None:
        self.tracker.touch()
