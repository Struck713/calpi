"""Main-loop discipline helpers. See the gtk-kiosk-app skill: never touch widgets off the main thread.

Rules for run_in_thread:
- `work` must not touch any widget, or any GObject owned by the UI.
- `on_done` and `on_error` run on the main thread and may touch widgets.
- If the screen that asked for the work has been closed by the time the result
  arrives, `on_done` must cope (check a "still showing" flag; don't rely on the widget being alive).
"""
from __future__ import annotations

import functools
import logging
import threading
from typing import Any, Callable

from gi.repository import GLib

log = logging.getLogger("calpi.tasks")


def safe_callback(fn=None, *, repeat: bool | None = None):
    """Wrap a GLib timeout/idle callback so an exception is logged and doesn't kill the source.

    repeat=None  -> return whatever fn returns (SOURCE_CONTINUE/REMOVE); None means REMOVE;
                    on exception the source is removed.
    repeat=True  -> always continue (also after an exception).
    repeat=False -> always remove.
    Usage: GLib.timeout_add_seconds(60, safe_callback(self._tick, repeat=True))
    """
    def deco(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            try:
                result = f(*args, **kwargs)
            except Exception:
                log.exception("callback %s failed", getattr(f, "__qualname__", f))
                return GLib.SOURCE_CONTINUE if repeat else GLib.SOURCE_REMOVE
            if repeat is None:
                return result if result is not None else GLib.SOURCE_REMOVE
            return GLib.SOURCE_CONTINUE if repeat else GLib.SOURCE_REMOVE
        return wrapper
    return deco(fn) if fn is not None else deco


class CallbackList(list):
    """List of callbacks. `add` returns a handle for `remove`; plain list `append` keeps working."""

    def add(self, cb):
        self.append(cb)
        return cb

    def remove(self, handle) -> None:
        try:
            super().remove(handle)
        except ValueError:
            pass

    def call(self, *args) -> None:
        """Call every callback; an exception in one is logged and doesn't stop the others."""
        for cb in list(self):
            try:
                cb(*args)
            except Exception:
                log.exception("callback %s failed", getattr(cb, "__qualname__", cb))


def call_on_main(fn: Callable[..., Any], *args) -> None:
    """Schedule fn(*args) on the main loop once. Safe from any thread."""
    GLib.idle_add(safe_callback(lambda: fn(*args), repeat=False))


def run_in_thread(work: Callable[[], Any], *,
                  on_done: Callable[[Any], None] | None = None,
                  on_error: Callable[[BaseException], None] | None = None,
                  name: str = "calpi-worker") -> threading.Thread:
    """Run blocking `work()` in a daemon thread; deliver the result or exception on the main thread."""
    def runner():
        try:
            result = work()
        except BaseException as e:  # noqa: BLE001 - must reach on_error
            log.warning("worker %s failed: %s", name, e, exc_info=True)
            if on_error:
                call_on_main(on_error, e)
            return
        if on_done:
            call_on_main(on_done, result)
    t = threading.Thread(target=runner, name=name, daemon=True)
    t.start()
    return t


# --- periodic-source registry (US-37 D1) ---------------------------------------------------------
# GLib cannot list its sources, so every REPEATING timer of the app registers itself here. The
# hourly health line logs the count (a growing count = a leak / a duplicate timer) and the names at
# DEBUG. One-shot timers are not registered. A timer that re-arms itself (the minute clock) registers
# once and refreshes its id with update_periodic().
_periodic: dict[str, int] = {}
_periodic_interval: dict[str, float | None] = {}


def register_periodic(name: str, source_id: int, interval_s: float | None = None) -> None:
    """Record a repeating source. A second registration under the same name is a bug: warn."""
    if name in _periodic:
        log.warning("periodic source %s registered twice", name)
    _periodic[name] = source_id
    _periodic_interval[name] = interval_s


def update_periodic(name: str, source_id: int) -> None:
    """A registered source re-armed itself (new GLib id): no duplicate warning."""
    _periodic[name] = source_id


def unregister_periodic(name: str) -> None:
    _periodic.pop(name, None)
    _periodic_interval.pop(name, None)


def periodic_sources() -> dict[str, int]:
    return dict(_periodic)


def periodic_wakeups_per_hour() -> dict[str, float | None]:
    """Nominal wakeups per hour of every registered repeating source (the wakeup audit)."""
    return {n: (3600.0 / s if s else None) for n, s in _periodic_interval.items()}


def add_periodic_seconds(name: str, seconds: int, fn) -> int:
    """timeout_add_seconds + register. `fn` should be safe_callback-wrapped and return CONTINUE."""
    sid = GLib.timeout_add_seconds(seconds, fn)
    register_periodic(name, sid, seconds)
    return sid


def remove_periodic(name: str) -> None:
    """Remove a registered source from the main loop (if still there) and forget it."""
    sid = _periodic.get(name)
    if sid:
        try:
            GLib.source_remove(sid)
        except Exception:
            pass
    unregister_periodic(name)
