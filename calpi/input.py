"""Input handling for the kiosk: cursor policy, key routing, touch-target checker.

Input conventions (every UI story must follow these)
----------------------------------------------------
* Use Gtk.Button for anything you press. A custom clickable widget uses
  Gtk.GestureClick and acts on `released` inside the widget bounds.
* Targets are at least 72x72 px with at least 16 px between neighbours
  (list rows: full width, at least 72 px tall). Give custom targets the CSS
  class `touch-target`; mark deliberate exceptions `target-exempt`.
* Press feedback is an instant `:active` style. No hover dependence (`:hover`
  looks like the normal state), no tooltips, no transitions.
* No long-press and no double-tap gestures.
* Screen keys: implement `on_key(name, state) -> bool` on the screen widget;
  KeyRouter calls it. Escape means "back" everywhere (never quits the app).
* Scrollable content goes in a Gtk.ScrolledWindow (kinetic scrolling on).
* Cursor: hidden by default, shown on mouse motion, hidden 3 s after the last
  motion or at once on touch (window.cursor is the CursorManager).
* One capture-phase event controller per window: WindowEventHub. Register
  callbacks with `hub.event_hooks.append(fn)`; do not add another controller.
* Run with CALPI_CHECK_TARGETS=1 to log `input: small target ...` violations.

The module imports gi lazily so the pure logic (CursorPolicy, route_key) is
unit-testable without a display.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Callable

log = logging.getLogger("calpi.input")

CURSOR_HIDE_S = 3.0
MIN_TARGET = 72

# Sources (strings so the pure logic needs no gi).
MOUSE, TOUCHPAD, TOUCHSCREEN, OTHER = "mouse", "touchpad", "touchscreen", "other"
MOTION, BUTTON, TOUCH, KEY = "motion", "button", "touch", "key"


class CursorPolicy:
    """Pure cursor state machine. Times are monotonic seconds.

    on_event() returns the desired visibility (or None for "no change") and
    tells the caller whether it must schedule a timer (at most one pending).
    """

    def __init__(self, hide_after: float = CURSOR_HIDE_S):
        self.hide_after = hide_after
        self.visible = False
        self.timer_pending = False
        self._last_motion = 0.0

    def on_event(self, source: str, kind: str, t: float) -> tuple[bool | None, float | None]:
        """Return (new_visibility_or_None, timer_delay_or_None)."""
        if source == TOUCHSCREEN or kind == TOUCH:
            self.visible = False
            return False, None          # a pending timer will fire harmlessly
        if kind == MOTION and source in (MOUSE, TOUCHPAD):
            self._last_motion = t
            self.visible = True
            delay = None
            if not self.timer_pending:
                self.timer_pending = True
                delay = self.hide_after
            return True, delay
        return None, None

    def on_timer(self, t: float) -> tuple[bool | None, float | None]:
        """Timer fired: hide if idle long enough, else re-arm for the remainder."""
        self.timer_pending = False
        if not self.visible:
            return None, None
        remaining = self.hide_after - (t - self._last_motion)
        if remaining > 0.01:
            self.timer_pending = True
            return None, remaining
        self.visible = False
        return False, None


def route_key(nav, name: str, state) -> bool:
    """Pure key routing: screen.on_key first, then global keys (Escape = back)."""
    current = nav.current
    screen = nav.get(current)
    handler = getattr(screen, "on_key", None)
    try:
        if handler and handler(name, state):
            return True
    except Exception:
        log.exception("on_key failed for %s", current)
    if name == "Escape" and current != "calendar":
        nav.back()
        return True
    return False


def is_touch(event) -> bool:
    from gi.repository import Gdk
    dev = event.get_device()
    if dev is not None and dev.get_source() == Gdk.InputSource.TOUCHSCREEN:
        return True
    return event.get_event_type() in (Gdk.EventType.TOUCH_BEGIN, Gdk.EventType.TOUCH_UPDATE,
                                      Gdk.EventType.TOUCH_END, Gdk.EventType.TOUCH_CANCEL)


def _classify(event) -> tuple[str, str]:
    from gi.repository import Gdk
    et = event.get_event_type()
    dev = event.get_device()
    src = dev.get_source() if dev is not None else None
    source = {Gdk.InputSource.MOUSE: MOUSE, Gdk.InputSource.TOUCHPAD: TOUCHPAD,
              Gdk.InputSource.TOUCHSCREEN: TOUCHSCREEN}.get(src, OTHER)
    if et == Gdk.EventType.MOTION_NOTIFY:
        kind = MOTION
    elif et in (Gdk.EventType.TOUCH_BEGIN, Gdk.EventType.TOUCH_UPDATE,
                Gdk.EventType.TOUCH_END, Gdk.EventType.TOUCH_CANCEL):
        kind = TOUCH
    else:
        kind = BUTTON
    return source, kind


class WindowEventHub:
    """The single capture-phase legacy controller of a window, fanning out to hooks."""

    def __init__(self, window):
        from gi.repository import Gtk
        self.event_hooks: list[Callable] = []
        ctl = Gtk.EventControllerLegacy()
        ctl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        ctl.connect("event", self._on_event)
        window.add_controller(ctl)

    def _on_event(self, _ctl, event) -> bool:
        if event is None:
            return False
        for hook in self.event_hooks:
            try:
                hook(event)
            except Exception:
                log.exception("event hook failed")
        return False                     # never consume events


class CursorManager:
    def __init__(self, window, hub: WindowEventHub):
        from gi.repository import Gdk
        self._window = window
        self._policy = CursorPolicy()
        self._arrow = Gdk.Cursor.new_from_name("default", None)
        # If "none" does not hide under cage, switch to a 1x1 transparent texture.
        self._hidden = Gdk.Cursor.new_from_name("none", None)
        self._shown: bool | None = None
        self._apply(False)
        hub.event_hooks.append(self.on_event)

    @property
    def visible(self) -> bool:
        return bool(self._shown)

    def on_event(self, event) -> None:
        source, kind = _classify(event)
        if kind == BUTTON and source == OTHER:
            return
        self._handle(self._policy.on_event(source, kind, time.monotonic()))

    def _handle(self, result) -> None:
        vis, delay = result
        if vis is not None:
            self._apply(vis)
        if delay is not None:
            self._arm(delay)

    def _arm(self, delay: float) -> None:
        from gi.repository import GLib
        GLib.timeout_add(max(1, int(delay * 1000)), self._on_timer)

    def _on_timer(self) -> bool:
        from gi.repository import GLib
        try:
            self._handle(self._policy.on_timer(time.monotonic()))
        except Exception:
            log.exception("cursor timer failed")
        return GLib.SOURCE_REMOVE

    def _apply(self, visible: bool) -> None:
        if visible == self._shown:
            return
        self._shown = visible
        self._window.set_cursor(self._arrow if visible else self._hidden)
        log.debug("input: cursor visible=%s", visible)


class KeyRouter:
    def __init__(self, window, navigator):
        from gi.repository import Gtk
        self._window = window
        self._nav = navigator
        ctl = Gtk.EventControllerKey()   # bubble phase: focused entries get keys first
        ctl.connect("key-pressed", self._on_key)
        window.add_controller(ctl)

    def _on_key(self, _ctl, keyval, _keycode, state) -> bool:
        from gi.repository import Gdk, Gtk
        focus = self._window.get_focus()
        if isinstance(focus, Gtk.Editable) and Gdk.keyval_name(keyval) != "Escape":
            return False
        return route_key(self._nav, Gdk.keyval_name(keyval) or "", state)


# ---- dev-only touch target checker ----------------------------------------

def check_targets_enabled() -> bool:
    return os.environ.get("CALPI_CHECK_TARGETS") == "1"


def check_targets(root, min_size: int = MIN_TARGET) -> list[str]:
    """Walk the widget tree; log and return violations (dev only)."""
    from gi.repository import Gtk
    bad: list[str] = []

    def clickable(w) -> bool:
        if isinstance(w, Gtk.Button):
            return True
        ctls = w.observe_controllers()
        for i in range(ctls.get_n_items()):
            if isinstance(ctls.get_item(i), Gtk.GestureClick):
                return True
        return False

    def walk(w):
        if w is None or not w.get_mapped() or w.has_css_class("target-exempt"):
            return
        if clickable(w):
            width, height = w.get_width(), w.get_height()
            if min(width, height) < min_size:
                msg = f"{type(w).__name__} {width}x{height}"
                bad.append(msg)
                log.warning("input: small target %s", msg)
        child = w.get_first_child()
        while child is not None:
            walk(child)
            child = child.get_next_sibling()

    walk(root)
    return bad


def install_target_checker(navigator) -> None:
    """After each navigator.show, check the visible screen 2 s later."""
    from gi.repository import GLib
    orig = navigator.show

    def show(name, **params):
        orig(name, **params)

        def later():
            screen = navigator.get(navigator.current)
            if screen is not None:
                check_targets(screen)
            return GLib.SOURCE_REMOVE
        GLib.timeout_add_seconds(2, later)

    navigator.show = show
