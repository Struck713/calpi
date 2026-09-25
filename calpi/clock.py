"""ClockService: the one per-minute timer. Others subscribe (US-10)."""
from __future__ import annotations

import logging

from gi.repository import GLib

from calpi import tasks
from calpi.data import timeutil
from calpi.data.daychange import DayChangeDetector

log = logging.getLogger("calpi.clock")


def _fmt_delta(seconds: float) -> str:
    sign = "+" if seconds >= 0 else "-"
    s = int(abs(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{sign}{h}h{m:02d}m"
    if m:
        return f"{sign}{m}m{sec:02d}s"
    return f"{sign}{sec}s"


class ClockService:
    def __init__(self):
        self.detector = DayChangeDetector()
        self._minute: dict[int, object] = {}
        self._day: dict[int, object] = {}
        self._tz: dict[int, object] = {}
        self._next_handle = 1
        self._source = 0
        self._registered = False
        self._schedule()

    def _schedule(self) -> None:
        n = timeutil.now()
        delay = (60 - n.second) * 1000 - n.microsecond // 1000 + 50
        self._source = GLib.timeout_add(max(delay, 50), self._on_timer)
        if not self._registered:
            self._registered = True
            tasks.register_periodic("clock", self._source, 60)      # one per-minute timer, re-armed
        else:
            tasks.update_periodic("clock", self._source)

    def _on_timer(self):
        try:
            self._tick()
        except Exception:
            log.exception("clock tick failed")
        finally:
            self._schedule()
        return GLib.SOURCE_REMOVE

    def _tick(self) -> None:
        r = self.detector.tick()
        log.debug("clock: tick %s", r.now.strftime("%Y-%m-%d %H:%M"))
        if r.jump_seconds is not None:
            log.warning("clock: wall clock jumped by %s (NTP?)", _fmt_delta(r.jump_seconds))
        self._call(self._minute, r.now)
        if r.day_changed:
            old, new = r.day_changed
            log.info("clock: day changed %s -> %s", old, new)
            self._call(self._day, old, new)

    def notify_tz_changed(self) -> None:
        log.info("clock: display time zone is now %s", timeutil.display_tz().key)
        self._call(self._tz)
        self._tick()

    def _call(self, subs: dict, *args) -> None:
        for cb in list(subs.values()):
            try:
                cb(*args)
            except Exception:
                log.exception("clock subscriber failed")

    def _sub(self, table: dict, cb) -> int:
        h = self._next_handle
        self._next_handle += 1
        table[h] = cb
        return h

    def subscribe_minute(self, cb) -> int:
        return self._sub(self._minute, cb)

    def subscribe_day_changed(self, cb) -> int:
        return self._sub(self._day, cb)

    def subscribe_tz_changed(self, cb) -> int:
        return self._sub(self._tz, cb)

    def unsubscribe(self, handle: int) -> None:
        for t in (self._minute, self._day, self._tz):
            t.pop(handle, None)
