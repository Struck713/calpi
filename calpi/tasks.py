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
